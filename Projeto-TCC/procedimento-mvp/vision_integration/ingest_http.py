"""Transporte HTTP da ingestão observacional: pipeline -> POST da API.

Fecha o gap entre build_ingest_payload() e POST /api/observations/ingest
(antes, apenas os testes usavam o TestClient in-process). Somente stdlib
(urllib) — sem dependências novas.

Fluxo de UM ciclo on_detect_all (process_and_ingest):
    detections -> process_frame() -> build_ingest_payload() -> send_batch()

Política anti-duplicação (camadas):
  1) debounce da própria pipeline (evento, camera_id, person_ref) suprime
     ciclos repetidos iguais;
  2) envio SOMENTE com ao menos 1 evento (sem batches vazios);
  3) retry APENAS em falha de CONEXÃO (recusada/DNS): o pedido nunca chegou
     ao servidor, então reenviar é seguro;
  4) timeout/5xx => desfecho "unknown": NÃO reenviar automaticamente
     (o servidor pode ter commitado);
  5) idempotência server-side: o MESMO (camera_id, received_at) reenviado
     devolve o batch existente com duplicate=True — reenvio manual também
     é seguro (process_and_ingest sempre define received_at por ciclo).

Separações preservadas: NÃO importa state_machine, event_ingest nem
vision_bridge; person_ref continua efêmero (nunca identidade); as regras
de contexto/indeterminado do event_generator continuam intactas.

Configuração: variável de ambiente INGEST_API_BASE ou argumento api_base;
padrão http://127.0.0.1:8000.
"""
from __future__ import annotations

import json
import os
import secrets
import socket
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "event_arch"))

from config import DEFAULT_CAMERA_ID  # noqa: E402
from ingest_payload import build_ingest_payload  # noqa: E402  (também expõe app.schemas)
from pipeline import process_frame  # noqa: E402

DEFAULT_API_BASE = "http://127.0.0.1:8000"
INGEST_PATH = "/api/observations/ingest"
IMAGE_PATH = "/api/images"


class SendResult(NamedTuple):
    """Resultado de send_batch().

    status:
      created     -> 201, batch novo persistido
      duplicate   -> 201, servidor reconheceu reenvio (batch existente)
      rejected    -> 4xx determinístico (nada persistido; corrigir payload)
      unknown     -> timeout/5xx (desfecho ambíguo: NÃO reenviar às cegas)
      unreachable -> conexão nunca estabelecida (nada persistido; seguro
                     tentar mais tarde)

    observation_ids: IDs reais (observations.id) criados neste lote, na ordem
      de inserção — permitem vincular evidência de imagem à ocorrência EXATA
      persistida. Vazio em duplicate/falha (nada novo criado).
    """

    status: str
    batch_id: Optional[int]
    detail: str
    observation_ids: tuple = ()


def send_batch(
    payload,
    *,
    api_base: Optional[str] = None,
    timeout: float = 10.0,
    connect_attempts: int = 2,
) -> SendResult:
    """POST /api/observations/ingest com política anti-duplicação.

    payload: IngestBatchIn (ou dict já serializado).
    """
    base = (api_base or os.getenv("INGEST_API_BASE") or DEFAULT_API_BASE).rstrip("/")
    url = base + INGEST_PATH
    data = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}

    attempt = 1
    while True:
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
            parsed = json.loads(raw) if raw else {}
            obs_ids = tuple(int(x) for x in parsed.get("observation_ids", []) or [])
            if parsed.get("duplicate"):
                return SendResult(
                    "duplicate",
                    parsed.get("batch_id"),
                    "reenvio reconhecido pelo servidor (idempotência)",
                    obs_ids,
                )
            n = parsed.get("observations_created", 0)
            return SendResult(
                "created", parsed.get("batch_id"), f"{n} observação(ões)", obs_ids
            )
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8")[:300]
            except Exception:  # noqa: BLE001 — corpo ilegível não altera o desfecho
                detail = ""
            if 400 <= exc.code < 500:
                # Determinístico (404/422): nada persistido; reenviar não resolve.
                return SendResult("rejected", None, f"HTTP {exc.code}: {detail}")
            # 5xx: resposta recebida mas desfecho no servidor ambíguo.
            return SendResult("unknown", None, f"HTTP {exc.code}: {detail}")
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, (ConnectionRefusedError, socket.gaierror)):
                if attempt < connect_attempts:
                    attempt += 1
                    continue
                return SendResult(
                    "unreachable",
                    None,
                    f"conexão recusada após {connect_attempts} tentativa(s): {reason}",
                )
            return SendResult(
                "unknown",
                None,
                f"erro de rede ambíguo (não reenviar automaticamente): {reason!r}",
            )
        except (TimeoutError, socket.timeout) as exc:
            return SendResult(
                "unknown",
                None,
                f"timeout sem resposta (não reenviar automaticamente): {exc}",
            )
        except (ConnectionRefusedError, socket.gaierror) as exc:
            if attempt < connect_attempts:
                attempt += 1
                continue
            return SendResult(
                "unreachable",
                None,
                f"conexão recusada após {connect_attempts} tentativa(s): {exc}",
            )
        except OSError as exc:
            # Outra falha de rede com desfecho ambíguo -> não reenviar às cegas.
            return SendResult(
                "unknown",
                None,
                f"erro de rede ambíguo (não reenviar automaticamente): {exc!r}",
            )


def send_image_evidence(
    image_bytes: bytes,
    occurrence_id: int,
    camera_code: str,
    *,
    filename: str = "evidence.jpg",
    mime_type: str = "image/jpeg",
    api_base: Optional[str] = None,
    timeout: float = 10.0,
) -> bool:
    """POST /api/images — vincula a evidência de imagem à ocorrência REAL.

    Reusa o endpoint existente (upload multipart) já implementado no backend.
    `occurrence_id` deve ser um observations.id persistido (nunca provisório).

    Retorna True quando o servidor confirmou o registro (201); False em
    qualquer falha (rede/4xx/5xx). A falha NÃO afeta a ocorrência já
    persistida — apenas registra o problema no stderr (sem silenciar).
    """
    if not image_bytes or occurrence_id is None:
        return False
    base = (api_base or os.getenv("INGEST_API_BASE") or DEFAULT_API_BASE).rstrip("/")
    url = base + IMAGE_PATH
    boundary = "----tccimage" + secrets.token_hex(8)
    body = _multipart_body(
        boundary,
        fields={
            "occurrence_id": str(int(occurrence_id)),
            "camera_code": str(camera_code),
        },
        file_field="image",
        filename=filename,
        mime_type=mime_type,
        content=image_bytes,
    )
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    try:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
        return True
    except Exception as exc:  # noqa: BLE001 — evidência é best-effort
        print(f"[VISION] evidência de imagem não registrada (occ={occurrence_id}): {exc!r}")
        return False


def _multipart_body(
    boundary: str,
    *,
    fields: dict,
    file_field: str,
    filename: str,
    mime_type: str,
    content: bytes,
) -> bytes:
    """Monta um corpo multipart/form-data (sem dependências externas)."""
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n"
            ).encode("utf-8")
        )
    parts.append(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{file_field}"; '
            f'filename="{filename}"\r\n'
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode("utf-8")
    )
    parts.append(content)
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts)


def process_and_ingest(
    detections: dict,
    *,
    log,
    debounce=None,
    camera_id=None,
    risk_area=None,
    model_name=None,
    model_version=None,
    received_at=None,
    api_base=None,
    timeout=10.0,
    occurrence=None,
) -> dict:
    """UM ciclo on_detect_all completo: pipeline -> adaptador -> HTTP.

    - Envia SOMENTE se a pipeline gerou eventos; 0 eventos => "no_events"
      e nada é enviado (sem batches vazios no banco). Observações de
      contexto indeterminado/fora/sem área continuam nunca sendo geradas
      (regra do event_generator — inalterada aqui).
    - received_at (padrão: agora em UTC) identifica o ciclo e é a chave de
      idempotência no servidor; em reenvio manual, REUSE o mesmo valor.
    - Não toca a State Machine; person_ref segue efêmero (sem identidade).
    - camera_id deve existir no banco (seed: camera_1), senão 404 => "rejected".
    - occurrence (opcional): OccurrenceTracker da camada temporal — quando
      fornecido, process_frame emite apenas transições confirmadas.
    - risk_area: repassada ao adaptador para preservar risk_area_id no server.

    Retorna dict: status, events (enviadas), batch_id, detail.
    """
    camera = camera_id if camera_id is not None else DEFAULT_CAMERA_ID
    _, events = process_frame(
        detections,
        log=log,
        debounce=debounce,
        camera_id=camera,
        risk_area=risk_area,
        occurrence=occurrence,
    )
    if not events:
        return {
            "status": "no_events",
            "events": 0,
            "batch_id": None,
            "detail": "nenhum evento (fora/sem área, indeterminado ou debounced)",
        }

    payload = build_ingest_payload(
        detections,
        events,
        camera_id=camera,
        model_name=model_name,
        model_version=model_version,
        received_at=(
            received_at if received_at is not None else datetime.now(timezone.utc)
        ),
        risk_area=risk_area,
    )
    result = send_batch(payload, api_base=api_base, timeout=timeout)
    return {
        "status": result.status,
        "events": len(events),
        "batch_id": result.batch_id,
        "detail": result.detail,
    }
