"""Integração REAL por HTTP: pipeline -> socket TCP -> PostgreSQL.

Diferente do test_e2e (TestClient ASGI in-process), AQUI a requisição trafega
por um socket TCP para um uvicorn REAL em porta efêmera — valida o transporte
que o detector usará em produção (vision_integration/ingest_http.py).

Origem das detecções: payload CONTROLADO (mesma metodologia do e2e). A câmera
e o modelo estão BLOQUEADOS neste ambiente (sem a lib `arduino` App Bricks e
sem `cv2`; app detector.py só existe nas outras cópias do projeto). O que
ESTE teste valida é o transporte + persistência + idempotência — não a câmera.

Casos:
  T1 envio real por socket -> batch + observations no banco
  T2 reenvio do MESMO ciclo (received_at) -> duplicate, nada duplicado
  T3 sem área de risco -> nenhum evento -> nada enviado
  T4 servidor inacessível -> unreachable (sem exceção)
  T5 câmera desconhecida -> rejected (404), nada persistido
"""
from __future__ import annotations

import atexit
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# 1) Setup de importacao: vision_integration + event_arch + backend
# ---------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent
RAIZ = HERE.parent

sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "vision_integration"))
sys.path.insert(0, str(RAIZ / "event_arch"))
sys.path.insert(0, str(RAIZ / "dashboard" / "backend"))

os.chdir(RAIZ / "dashboard" / "backend")
from dotenv import load_dotenv  # noqa: E402
load_dotenv()

from sqlalchemy import text  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from vision_integration.ingest_http import (  # noqa: E402
    process_and_ingest,
    send_batch,
)
from vision_integration.ingest_payload import build_ingest_payload  # noqa: E402

from event_log import EventLog  # noqa: E402
from event_debounce import EventDebounce  # noqa: E402

# ---------------------------------------------------------------------------
# 2) uvicorn REAL em porta efêmera (daemon thread) + parada via atexit
# ---------------------------------------------------------------------------
def _porta_livre() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    porta = s.getsockname()[1]
    s.close()
    return porta


def _iniciar_servidor():
    import uvicorn

    porta = _porta_livre()
    config = uvicorn.Config(app, host="127.0.0.1", port=porta, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{porta}/health", timeout=1
            ) as resp:
                if resp.status == 200:
                    return server, thread, porta
        except Exception:  # noqa: BLE001 — ainda subindo
            time.sleep(0.1)
    raise RuntimeError("uvicorn de teste não ficou pronto em 20s")


SERVER, _SERVER_THREAD, PORTA = _iniciar_servidor()
BASE_URL = f"http://127.0.0.1:{PORTA}"


def _parar_servidor() -> None:
    SERVER.should_exit = True
    _SERVER_THREAD.join(timeout=5)


atexit.register(_parar_servidor)

# ---------------------------------------------------------------------------
# 3) Payloads controlados + limpeza (apenas batches deste teste)
# ---------------------------------------------------------------------------
AREA = {"x1": 0.0, "y1": 0.0, "x2": 1000.0, "y2": 1000.0}

# Pessoa dentro da área COM capacete e SEM colete no frame
# -> eventos determinísticos: pessoa_com_capacete + pessoa_sem_colete.
PAYLOAD = {
    "person": [{"confidence": 0.93, "bounding_box_xyxy": [150.0, 150.0, 350.0, 450.0]}],
    "helmet": [{"confidence": 0.90, "bounding_box_xyxy": [190.0, 100.0, 310.0, 170.0]}],
}

# Chave de idempotência do payload do T1 (compartilhada só dentro do T1).
_RUN_AT = datetime.now(timezone.utc)

_CREATED_BATCHES: list[int] = []


def _track(batch_id: int) -> None:
    _CREATED_BATCHES.append(batch_id)


def _cleanup() -> None:
    """Remove APENAS batches criados por este teste (seeds intactos)."""
    if not _CREATED_BATCHES:
        return
    db = SessionLocal()
    try:
        db.execute(
            text("DELETE FROM observations WHERE batch_id = ANY(:ids)"),
            {"ids": _CREATED_BATCHES},
        )
        db.execute(
            text("DELETE FROM observation_batches WHERE id = ANY(:ids)"),
            {"ids": _CREATED_BATCHES},
        )
        db.commit()
    finally:
        db.close()
        _CREATED_BATCHES.clear()


def _scalar(sql: str, params: dict | None = None):
    db = SessionLocal()
    try:
        return db.execute(text(sql), params or {}).scalar_one()
    finally:
        db.close()


def _query(sql: str, params: dict | None = None):
    db = SessionLocal()
    try:
        return db.execute(text(sql), params or {}).mappings().all()
    finally:
        db.close()


# ===========================================================================
# T1 — envio REAL por socket: pipeline -> HTTP -> PostgreSQL
# ===========================================================================
def test_t1_envio_real_por_socket(tmp_path):
    out = process_and_ingest(
        PAYLOAD,
        log=EventLog(Path(tmp_path) / "t1.jsonl"),
        debounce=EventDebounce(),
        risk_area=AREA,
        received_at=_RUN_AT,
        api_base=BASE_URL,
        model_name="teste-integracao-http",
    )
    assert out["status"] == "created", out
    assert out["events"] == 2, out
    bid = out["batch_id"]
    assert bid is not None
    _track(bid)

    rows = _query(
        "SELECT o.person_ref, et.code FROM observations o "
        "JOIN event_types et ON et.id = o.event_type_id "
        "WHERE o.batch_id = :bid ORDER BY o.id",
        {"bid": bid},
    )
    assert {r["code"] for r in rows} == {
        "pessoa_com_capacete",
        "pessoa_sem_colete",
    }, [r["code"] for r in rows]
    # person_ref é índice efêmero do frame — mesma pessoa nos 2 eventos.
    assert all(r["person_ref"] == 0 for r in rows)

    batch = _query(
        "SELECT camera_id, received_at, raw_detections, model_name "
        "FROM observation_batches WHERE id = :bid",
        {"bid": bid},
    )[0]
    assert batch["camera_id"] == 1  # camera_1 do seed mapeada por code
    assert batch["received_at"] is not None
    assert "person" in batch["raw_detections"]  # detecção bruta preservada
    assert batch["model_name"] == "teste-integracao-http"
    print("[T1] batch_id=" + str(bid) + " | 2 observações via socket real")


# ===========================================================================
# T2 — reenvio do MESMO ciclo (received_at) -> duplicate, nada duplicado
# ===========================================================================
def test_t2_reenvio_mesmo_ciclo_e_idempotente(tmp_path):
    # Ciclo PRÓPRIO do T2 (independente do T1: a fixture autouse limpa
    # os batches após cada teste, então T2 não pode depender do T1).
    ciclo = datetime.now(timezone.utc)
    out1 = process_and_ingest(
        PAYLOAD,
        log=EventLog(Path(tmp_path) / "t2a.jsonl"),
        debounce=EventDebounce(),
        risk_area=AREA,
        received_at=ciclo,
        api_base=BASE_URL,
    )
    assert out1["status"] == "created", out1
    _track(out1["batch_id"])

    before_b = _scalar("SELECT count(*) FROM observation_batches")
    before_o = _scalar("SELECT count(*) FROM observations")

    out2 = process_and_ingest(
        PAYLOAD,
        log=EventLog(Path(tmp_path) / "t2b.jsonl"),
        debounce=EventDebounce(),  # debounce novo: a pipeline geraria de novo
        risk_area=AREA,
        received_at=ciclo,  # MESMA chave do 1º envio
        api_base=BASE_URL,
    )
    assert out2["status"] == "duplicate", out2
    assert out2["batch_id"] == out1["batch_id"], out2
    assert _scalar("SELECT count(*) FROM observation_batches") == before_b
    assert _scalar("SELECT count(*) FROM observations") == before_o
    print("[T2] reenvio reconhecido como duplicate; banco inalterado")


# ===========================================================================
# T3 — sem área de risco -> nenhum evento -> nada é enviado
# ===========================================================================
def test_t3_sem_area_nao_envia_nada(tmp_path):
    before_b = _scalar("SELECT count(*) FROM observation_batches")
    out = process_and_ingest(
        PAYLOAD,
        log=EventLog(Path(tmp_path) / "t3.jsonl"),
        debounce=EventDebounce(),
        risk_area=None,  # regra atual: no_area => nenhuma conformidade
        received_at=_RUN_AT,
        api_base=BASE_URL,
    )
    assert out["status"] == "no_events", out
    assert out["events"] == 0
    assert out["batch_id"] is None
    assert _scalar("SELECT count(*) FROM observation_batches") == before_b
    print("[T3] contexto sem área -> 0 eventos -> nenhum lote enviado")


# ===========================================================================
# T4 — servidor inacessível -> unreachable (sem exceção vazando)
# ===========================================================================
def test_t4_servidor_inacessivel_unreachable():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    porta_morta = s.getsockname()[1]
    s.close()  # porta livre -> conexão será recusada

    payload = build_ingest_payload(PAYLOAD, [], camera_id="camera_1")
    result = send_batch(
        payload,
        api_base=f"http://127.0.0.1:{porta_morta}",
        connect_attempts=2,
    )
    assert result.status == "unreachable", result
    assert result.batch_id is None
    print("[T4] porta morta -> unreachable (nada foi processado)")


# ===========================================================================
# T5 — câmera desconhecida -> rejected (404), nada persistido
# ===========================================================================
def test_t5_camera_desconhecida_rejected():
    before_b = _scalar("SELECT count(*) FROM observation_batches")
    payload = build_ingest_payload(PAYLOAD, [], camera_id="camera_inexistente")
    result = send_batch(payload, api_base=BASE_URL)
    assert result.status == "rejected", result
    assert "404" in result.detail, result.detail
    assert _scalar("SELECT count(*) FROM observation_batches") == before_b
    print("[T5] câmera desconhecida -> rejected 404; banco inalterado")


# ===========================================================================
# Fixture de limpeza automatica (apaga apenas batches deste teste)
# ===========================================================================
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _garante_limpeza():
    yield
    _cleanup()


# Executa como script tambem (python tests/<este>)
if __name__ == "__main__":
    try:
        with tempfile.TemporaryDirectory() as tmp:
            test_t1_envio_real_por_socket(Path(tmp))
            test_t2_reenvio_mesmo_ciclo_e_idempotente(Path(tmp))
            test_t3_sem_area_nao_envia_nada(Path(tmp))
            test_t4_servidor_inacessivel_unreachable()
            test_t5_camera_desconhecida_rejected()
    finally:
        # Sempre limpar: no modo script o fixture autouse do pytest não roda.
        _cleanup()
        _parar_servidor()
    print("\n[OK] ingest_http: transporte real por socket validado.")
