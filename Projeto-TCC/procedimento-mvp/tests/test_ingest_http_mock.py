"""Teste C — cliente de ingestão HTTP com MOCKS (sem rede, sem banco).

Cobertura: payload válido; payload inválido (validação client-side);
timeout; erro HTTP 4xx/5xx; conexão recusada; reenvio da mesma requisição;
resposta de sucesso/duplicate; ausência de duplicação indevida no cliente;
ponte (detector_bridge): fila limitada, falha capturada, sem exceção ao chamador.

URLENV é MOCKADO (unittest.mock) — nenhum socket real é aberto.
"""
from __future__ import annotations

import io
import json
import socket
import sys
import tempfile
import urllib.error
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "event_arch"))
sys.path.insert(0, str(HERE.parent / "vision_integration"))

from detector_bridge import DetectorIngestBridge  # noqa: E402
from event_log import EventLog  # noqa: E402
from ingest_http import send_batch  # noqa: E402
from ingest_payload import build_ingest_payload  # noqa: E402
from pipeline import process_frame  # noqa: E402

AREA = {"x1": 0.0, "y1": 0.0, "x2": 800.0, "y2": 600.0}
PAYLOAD = {
    "person": [{"confidence": 0.93, "bounding_box_xyxy": (100.0, 100.0, 300.0, 400.0)}],
    "helmet": [{"confidence": 0.90, "bounding_box_xyxy": (150.0, 50.0, 250.0, 120.0)}],
    "vest": [{"confidence": 0.88, "bounding_box_xyxy": (150.0, 250.0, 250.0, 350.0)}],
}


def _payload_ingest():
    """Payload real: pipeline -> adaptador (mesmo caminho do detector)."""
    with tempfile.TemporaryDirectory() as tmp:
        _, events = process_frame(
            PAYLOAD, EventLog(Path(tmp) / "c.jsonl"), None, risk_area=AREA
        )
    assert events, "cenário sintético deveria gerar eventos"
    return build_ingest_payload(
        PAYLOAD, events, camera_id="camera_1", risk_area=AREA
    )


class _FakeResp:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body


def _body_ok(batch_id=7, n=2, duplicate=False):
    return json.dumps(
        {"batch_id": batch_id, "observations_created": n, "duplicate": duplicate}
    ).encode("utf-8")


def _urlopen_ok(req, timeout=None, body=None):
    return _FakeResp(body if body is not None else _body_ok())


def test_envio_valido_retorna_created_e_corpo_correto():
    captured = []

    def fake(req, timeout=None):
        captured.append(req)
        return _FakeResp(_body_ok())

    with mock.patch("urllib.request.urlopen", side_effect=fake):
        out = send_batch(_payload_ingest())
    assert out.status == "created" and out.batch_id == 7
    assert len(captured) == 1, "sem retry em sucesso"
    enviado = json.loads(captured[0].data.decode("utf-8"))
    assert enviado["camera_id"] == "camera_1"
    assert enviado["risk_area"] == {"x1": 0.0, "y1": 0.0, "x2": 800.0, "y2": 600.0}
    assert len(enviado["observations"]) >= 1
    print("[C1] payload válido -> 201 created; corpo JSON correto (risk_area preservada)")


def test_resposta_duplicate_do_servidor():
    with mock.patch(
        "urllib.request.urlopen",
        side_effect=lambda req, timeout=None: _FakeResp(_body_ok(duplicate=True)),
    ):
        out = send_batch(_payload_ingest())
    assert out.status == "duplicate" and out.batch_id == 7
    print("[C2] resposta duplicate do servidor é repassada (sem reenvio)")


def test_erro_http_422_rejected_sem_retry():
    def fake(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 422, "Unprocessable", None,
            io.BytesIO(b'{"detail": "event_type desconhecido"}'),
        )

    with mock.patch("urllib.request.urlopen", side_effect=fake) as m:
        out = send_batch(_payload_ingest())
    assert out.status == "rejected" and "422" in out.detail
    assert m.call_count == 1, "4xx determinístico não deve ser reenviado"
    print("[C3] 422 -> rejected, 1 chamada (sem retry)")


def test_erro_http_500_unknown_sem_retry():
    def fake(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 500, "Internal", None, io.BytesIO(b"")
        )

    with mock.patch("urllib.request.urlopen", side_effect=fake) as m:
        out = send_batch(_payload_ingest())
    assert out.status == "unknown" and "500" in out.detail
    assert m.call_count == 1, "5xx ambíguo não deve ser reenviado às cegas"
    print("[C4] 500 -> unknown (desfecho ambíguo), sem reenvio automatico")


def test_timeout_retorna_unknown_sem_retry():
    def fake(req, timeout=None):
        raise socket.timeout("tempo esgotado")

    with mock.patch("urllib.request.urlopen", side_effect=fake) as m:
        out = send_batch(_payload_ingest(), timeout=0.1)
    assert out.status == "unknown"
    assert m.call_count == 1, "timeout pode ter persistido no servidor"
    print("[C5] timeout -> unknown, sem reenvio (evita duplicacao)")


def test_conexao_recusada_unreachable_com_retry_limitado():
    def fake(req, timeout=None):
        raise urllib.error.URLError(ConnectionRefusedError(111, "recusada"))

    with mock.patch("urllib.request.urlopen", side_effect=fake) as m:
        out = send_batch(_payload_ingest(), connect_attempts=2)
    assert out.status == "unreachable"
    assert m.call_count == 2, "retry limitado apenas p/ conexao nunca estabelecida"
    print("[C6] conexao recusada -> unreachable apos 2 tentativas (limitadas)")


def test_reenvio_mesma_requisicao_body_identico():
    """Reenvio pós-timeout: mesmo body byte a byte (idempotência é do server)."""
    captured = []
    bodies = [_body_ok(), _body_ok(duplicate=True)]

    def fake(req, timeout=None):
        captured.append(req.data)
        return _FakeResp(bodies[len(captured) - 1])

    p = _payload_ingest()
    with mock.patch("urllib.request.urlopen", side_effect=fake):
        out1 = send_batch(p)
        out2 = send_batch(p)
    assert out1.status == "created" and out2.status == "duplicate"
    assert captured[0] == captured[1], "reenvio deve ser byte a byte identico"
    print("[C7] reenvio: body identico; cliente propaga created -> duplicate")


def test_payload_invalido_falha_na_validacao_client_side():
    from pydantic import ValidationError

    with tempfile.TemporaryDirectory() as tmp:
        _, events = process_frame(
            PAYLOAD, EventLog(Path(tmp) / "inv.jsonl"), None, risk_area=AREA
        )
    events[0].metadata["confidence"] = 1.5  # fora de [0,1]
    try:
        build_ingest_payload(PAYLOAD, events, camera_id="camera_1")
    except ValidationError:
        pass
    else:
        raise AssertionError("payload invalido deveria falhar no adaptador")
    print("[C8] payload invalido: rejeitado ANTES da rede (validacao pydantic)")


# ---------------------------------------------------------------
# Ponte (detector_bridge): fila limitada + worker isolado
# ---------------------------------------------------------------
class _FakeSend:
    """send_fn injetado: registra payloads, devolve status controlado."""

    def __init__(self, status="created", raise_exc=None, block=None):
        self.status = status
        self.raise_exc = raise_exc
        self.block = block  # threading.Event opcional p/ travar o worker
        self.calls = []

    def __call__(self, payload, api_base=None, timeout=None):
        if self.block is not None:
            self.block.wait(5)
        if self.raise_exc is not None:
            raise self.raise_exc
        self.calls.append(payload)
        from types import SimpleNamespace

        return SimpleNamespace(status=self.status, batch_id=1, detail="ok")


def _eventos():
    with tempfile.TemporaryDirectory() as tmp:
        _, events = process_frame(
            PAYLOAD, EventLog(Path(tmp) / "br.jsonl"), None, risk_area=AREA
        )
    return events


def test_bridge_envia_sem_bloquear_e_sem_excecao():
    import threading

    fake = _FakeSend()
    bridge = DetectorIngestBridge(send_fn=fake, max_queue=8)
    try:
        aceitos = [
            bridge.submit(PAYLOAD, _eventos(), risk_area=AREA) for _ in range(3)
        ]
        assert all(aceitos)
        assert bridge.flush(5.0), "fila deveria esvaziar no prazo"
        st = bridge.stats
        assert st["submitted"] == 3 and st["sent"] == 3 and st["dropped"] == 0
        assert fake.calls[0].risk_area.x1 == 0.0  # risk_area chega ao adaptador
        assert fake.calls[0].received_at is not None  # chave de idempotência
    finally:
        bridge.close()
    print("[C9] bridge: 3 ciclos enviados, fila drenada, sem exceção ao chamador")


def test_bridge_fila_limitada_descarta_com_contador():
    import threading

    blocker = threading.Event()
    started = threading.Event()

    class _FakeSendStarted(_FakeSend):
        def __call__(self, payload, api_base=None, timeout=None):
            started.set()
            return super().__call__(payload, api_base, timeout)

    fake = _FakeSendStarted(block=blocker)
    bridge = DetectorIngestBridge(send_fn=fake, max_queue=1)
    try:
        assert bridge.submit(PAYLOAD, _eventos()) is True
        assert started.wait(5), "worker deveria iniciar"
        assert bridge.submit(PAYLOAD, _eventos()) is True   # enfileira (fila=1)
        assert bridge.submit(PAYLOAD, _eventos()) is False  # fila cheia -> drop
        assert bridge.stats["dropped"] == 1
    finally:
        blocker.set()
        bridge.close()
    print("[C10] fila limitada: item excedente descartado com contador (sem bloqueio)")


def test_bridge_falha_de_envio_contada_nao_propaga():
    fake = _FakeSend(raise_exc=RuntimeError("falhou"))
    bridge = DetectorIngestBridge(send_fn=fake, max_queue=4)
    try:
        assert bridge.submit(PAYLOAD, _eventos()) is True
        assert bridge.flush(5.0)
        st = bridge.stats
        assert st["failed"] == 1 and st["sent"] == 0
    finally:
        bridge.close()
    print("[C11] exceção no worker: contada como failed, nunca sobe ao detector")
