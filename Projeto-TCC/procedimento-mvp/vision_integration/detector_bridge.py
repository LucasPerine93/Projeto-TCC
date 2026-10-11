"""Ponte NÃO-bloqueante entre o callback do detector e a ingestão HTTP.

Fluxo por frame (o detector continua dono do callback):
    on_detect_all(detections)
        -> process_frame()            (síncrono: pipeline + EventLog, como hoje)
        -> bridge.submit(detections, events, risk_area=...)
             enfileira em fila LIMITADA (fila cheia -> descarta com contador;
             o detector NUNCA espera rede nem recebe exceção)
        -> worker daemon (um): build_ingest_payload() + send_batch()

Reutiliza os módulos existentes (adaptador ingest_payload e cliente
ingest_http.send_batch) — NÃO importa banco, State Machine nem vision_bridge.

Política de falhas (herdada de send_batch):
    - retry apenas em conexão recusada (nunca chegou ao servidor);
    - timeout/5xx => "unknown" sem reenvio automático;
    - fila limitada (max_queue) => crescimento limitado por construção;
    - exceções do worker são capturadas e contadas (nunca sobem ao detector).
"""
from __future__ import annotations

import queue
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from config import DEFAULT_CAMERA_ID  # noqa: E402

DEFAULT_MAX_QUEUE = 32


class DetectorIngestBridge:
    """Fila limitada + worker daemon para envio assíncrono de observações."""

    def __init__(
        self,
        *,
        camera_id: Optional[str] = None,
        api_base: Optional[str] = None,
        timeout: float = 10.0,
        max_queue: int = DEFAULT_MAX_QUEUE,
        send_fn=None,  # injeção para testes: send_fn(payload, **kw) -> resultado
        model_name: Optional[str] = None,
        model_version: Optional[str] = None,
        image_min_interval_s: float = 30.0,
    ) -> None:
        if max_queue < 1:
            raise ValueError("max_queue deve ser >= 1.")
        if image_min_interval_s < 0:
            raise ValueError("image_min_interval_s não pode ser negativo.")
        self.camera_id = camera_id if camera_id is not None else DEFAULT_CAMERA_ID
        self.api_base = api_base
        self.timeout = timeout
        self._send_fn = send_fn
        # Identificação do lote em observation_batches.model_name (opcional;
        # usado pelo simulador p/ marcar dados sintéticos — sem migração).
        self.model_name = model_name
        self.model_version = model_version
        # Guarda de upload repetido: (occurrence_id -> monotonic do último
        # upload). Evita N imagens da MESMA ocorrência persistida em rajadas
        # do worker. Limite: IDs distintos de observações da mesma condição
        # contínua NÃO são deduplicados aqui (identidade temporal é decisão
        # da camada occurrence/event_generator, não desta ponte).
        self.image_min_interval_s = float(image_min_interval_s)
        self._last_image_at: dict = {}
        self._q: queue.Queue = queue.Queue(maxsize=max_queue)
        self._sentinel = object()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        # Contadores observáveis (testes/monitoração).
        self.submitted = 0
        self.dropped = 0
        self.sent = 0
        self.failed = 0
        # Evidências de imagem (best-effort; só quando frame é fornecido).
        self.images_sent = 0
        self.images_failed = 0

    # ------------------------------------------------------------------ #
    def submit(
        self,
        detections: dict,
        events: list,
        *,
        risk_area: Optional[dict] = None,
        received_at=None,
        frame: Optional[bytes] = None,
    ) -> bool:
        """Enfileira UM ciclo; True = aceito, False = fila cheia (descartado).

        received_at é capturado AQUI (chave de idempotência estável do ciclo).
        frame (bytes JPEG/PNG do ciclo) é OPCIONAL: quando fornecido, após a
        ocorrência ser persistida o worker envia a evidência de imagem ao
        endpoint existente /api/images, vinculada ao observations.id REAL.
        Sem frame, apenas a ocorrência é registrada (nenhuma imagem fabricada).
        """
        item = {
            "detections": detections,
            "events": events,
            "risk_area": risk_area,
            "received_at": received_at
            if received_at is not None
            else datetime.now(timezone.utc),
            "frame": frame,
        }
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run, name="tcc-ingest-bridge", daemon=True
                )
                self._thread.start()
            try:
                self._q.put_nowait(item)
            except queue.Full:
                self.dropped += 1
                return False
            self.submitted += 1
            return True

    # ------------------------------------------------------------------ #
    def _run(self) -> None:
        while True:
            item = self._q.get()
            try:
                if item is self._sentinel:
                    return
                self._process_item(item)
            finally:
                self._q.task_done()

    def _process_item(self, item: dict) -> None:
        try:
            build_fn = self._importar_adaptador()
            send_fn = self._send_fn
            if send_fn is None:
                from ingest_http import send_batch  # noqa: PLC0415

                send_fn = send_batch
            payload = build_fn(
                item["detections"],
                item["events"],
                camera_id=self.camera_id,
                received_at=item["received_at"],
                risk_area=item["risk_area"],
                model_name=self.model_name,
                model_version=self.model_version,
            )
            result = send_fn(payload, api_base=self.api_base, timeout=self.timeout)
            status = getattr(result, "status", "unknown")
            if status in ("created", "duplicate"):
                self.sent += 1
                # Vincula a evidência de imagem à ocorrência REAL persistida.
                # Uma ocorrência por frame; usa o 1º observation_id (id real,
                # nunca provisório). Sem frame ou sem id => nenhuma imagem.
                frame = item.get("frame")
                obs_ids = getattr(result, "observation_ids", ()) or ()
                if frame and obs_ids:
                    self._upload_evidence(frame, int(obs_ids[0]))
            else:
                self.failed += 1
        except Exception as exc:  # noqa: BLE001 — worker nunca derruba o detector
            self.failed += 1
            print(f"[VISION] ingest bridge: ciclo descartado ({exc!r})")

    def _upload_evidence(self, frame: bytes, occurrence_id: int) -> None:
        """POST /api/images (best-effort) após a ocorrência persistida.

        Reusa send_image_evidence (ingest_http). Falha aqui NÃO desfaz a
        ocorrência — apenas incrementa o contador e loga (sem silenciar).

        Guarda: uploads da MESMA ocorrência dentro de `image_min_interval_s`
        são pulados (só o log registra o pulo; contadores intactos).
        """
        now = time.monotonic()
        last = self._last_image_at.get(occurrence_id)
        if last is not None and (now - last) < self.image_min_interval_s:
            print(
                f"[VISION] evidência de imagem pulada (occ={occurrence_id}): "
                f"upload recente há {now - last:.1f}s"
            )
            return
        self._last_image_at[occurrence_id] = now
        try:
            from ingest_http import send_image_evidence  # noqa: PLC0415

            ok = send_image_evidence(
                frame,
                occurrence_id,
                self.camera_id,
                api_base=self.api_base,
                timeout=self.timeout,
            )
        except Exception as exc:  # noqa: BLE001 — evidência é best-effort
            print(f"[VISION] evidência de imagem falhou (occ={occurrence_id}): {exc!r}")
            ok = False
        if ok:
            self.images_sent += 1
        else:
            self.images_failed += 1

    @staticmethod
    def _importar_adaptador():
        """Import preguiçoso do adaptador existente (ingest_payload)."""
        from ingest_payload import build_ingest_payload  # noqa: PLC0415

        return build_ingest_payload

    # ------------------------------------------------------------------ #
    def flush(self, timeout: float = 5.0) -> bool:
        """Espera a fila esvaziar E o worker terminar (para testes).

        True = tudo processado dentro do prazo.
        """
        deadline = datetime.now(timezone.utc).timestamp() + timeout
        while not (self._q.empty() and getattr(self._q, "unfinished_tasks", 0) == 0):
            if datetime.now(timezone.utc).timestamp() > deadline:
                return False
            threading.Event().wait(0.01)
        return True

    def close(self, timeout: float = 5.0) -> None:
        """Encerra o worker (drena o que já foi enfileirado, dentro do prazo)."""
        if self._thread is None or not self._thread.is_alive():
            return
        self.flush(timeout)
        try:
            self._q.put_nowait(self._sentinel)
        except queue.Full:
            try:  # abre espaço para o sentinel sem perder item processado
                self._q.get_nowait()
                self._q.task_done()
            except queue.Empty:
                pass
            try:
                self._q.put_nowait(self._sentinel)
            except queue.Full:
                pass
        self._thread.join(timeout=timeout)

    @property
    def stats(self) -> dict:
        return {
            "submitted": self.submitted,
            "dropped": self.dropped,
            "sent": self.sent,
            "failed": self.failed,
            "queued": self._q.qsize(),
            "images_sent": self.images_sent,
            "images_failed": self.images_failed,
        }
