"""Integracao HTTP ISOLADA: pipeline -> socket TCP real -> PostgreSQL de TESTE.

Fluxo (dados sinteticos, sem camera/Arduino/Raspberry):
    deteccoes controladas -> process_frame() -> build_ingest_payload()
    -> send_batch() via socket TCP real -> uvicorn REAL em porta efemera
    -> POST /api/observations/ingest -> PostgreSQL tcc_ppe_test

ISOLAMENTO (executa no import, ANTES de qualquer `app.*`):
  - valida a URL derivada (dbname == 'tcc_ppe_test') ANTES de conectar;
  - trava anti-tiro: aborta a coleta se current_database() != 'tcc_ppe_test';
  - banco de teste ausente/inacessivel => RuntimeError claro (preparar banco
    com schema+seed); nunca cria banco sozinho, nunca altera a .env,
    nunca toca o tcc_ppe.
  - NOTA: este teste deve rodar em sessao pytest separada dos testes do
    backend (ex.: `pytest tests/test_ingest_http_isolated.py`), porque
    o backend fixa DATABASE_URL no import (get_settings lru_cache +
    engine criada no import de app.database). Executar junto com
    backend/tests/test_*.py na mesma sessao prende a engine no banco
    que for importado primeiro.

Limpeza: rastreia batch_ids criados (por id, nao por prefixo) e apaga
observations + batches no teardown de cada teste, garantindo banco de
teste limpo mesmo quando uma assercao falha.

Limitacao: nao executar em paralelo (ex.: pytest-xdist) compartilhando o
mesmo tcc_ppe_test — os testes usam o mesmo camera_id seed e contagens
globais de batches/observations.
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

HERE = Path(__file__).resolve().parent
RAIZ = HERE.parent
BACKEND_DIR = RAIZ / "dashboard" / "backend"

for _p in (str(RAIZ), str(RAIZ / "vision_integration"), str(RAIZ / "event_arch"), str(BACKEND_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Trava contra engine presa: se app.config/app.database já foram importados
# nesta sessão pytest (ex.: coletou backend/tests/* junto), a engine já está
# vinculada ao banco importado primeiro (get_settings tem lru_cache + engine
# é criada no import). Nesse caso abortamos em vez de arriscar escrita no
# banco errado — rode este arquivo em sessão pytest separada.
if "app.database" in sys.modules or "app.config" in sys.modules:
    raise RuntimeError(
        "app.database/app.config já importado nesta sessão pytest; "
        "a engine pode estar presa a outro banco. Rode "
        "tests/test_ingest_http_isolated.py em sessão separada "
        "(ex.: pytest tests/test_ingest_http_isolated.py)."
    )

# A proteção real é a validação da URL derivada (dbname) + a trava
# anti-tiro (`current_database() == 'tcc_ppe_test'`) + rodar este arquivo em
# sessão pytest separada dos testes do backend.

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_DIR / ".env", override=False)

_base_url = os.getenv("DATABASE_URL", "").strip()
if not _base_url:
    raise RuntimeError("DATABASE_URL ausente na .env; abortando teste isolado.")
_bp = urlparse(_base_url)
if not _bp.username or not _bp.hostname:
    raise RuntimeError("DATABASE_URL da .env sem usuario/host; abortando.")
_netloc = f"{_bp.username}:{(_bp.password or '')}@{_bp.hostname}:{_bp.port or 5432}"
_test_url = urlunparse((_bp.scheme, _netloc, "/tcc_ppe_test", "", "", ""))
# Defesa em profundidade: valida a URL derivada antes mesmo de conectar.
if urlparse(_test_url).path.lstrip("/") != "tcc_ppe_test":
    raise RuntimeError("Falha interna ao derivar URL de teste; abortando.")
os.environ["DATABASE_URL"] = _test_url

from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from vision_integration.ingest_http import (  # noqa: E402
    process_and_ingest,
    send_batch,
)
from vision_integration.ingest_payload import build_ingest_payload  # noqa: E402

from event_log import EventLog  # noqa: E402
from event_debounce import EventDebounce  # noqa: E402

try:
    with engine.connect() as _conn:
        _current_db = _conn.execute(text("SELECT current_database()")).scalar()
except OperationalError as exc:
    raise RuntimeError(
        "Banco de teste 'tcc_ppe_test' inacessivel. Prepare o banco "
        "(CREATE DATABASE + schema.sql + seed.sql) e rode novamente. "
        f"Detalhe: {exc}"
    ) from exc
print(f"[isolated-http] connected_db={_current_db}")
if _current_db != "tcc_ppe_test":
    raise RuntimeError(f"ABORTADO: banco {_current_db!r}; esperado 'tcc_ppe_test'.")
# Defesa extra: a engine efetivamente em uso tambem precisa apontar para o
# banco de teste (nao basta a env). Se alguem trocar a env depois, isto pega.
if urlparse(str(engine.url)).path.lstrip("/") != "tcc_ppe_test":
    raise RuntimeError("ABORTADO: engine aponta para banco inesperado.")

import pytest  # noqa: E402

_CREATED_BATCHES: list[int] = []


def _scalar(sql: str):
    db = SessionLocal()
    try:
        return db.execute(text(sql)).scalar()
    finally:
        db.close()


def _track(batch_id: int) -> None:
    _CREATED_BATCHES.append(int(batch_id))


def _cleanup_tracked() -> int:
    if not _CREATED_BATCHES:
        return 0
    ids = list(_CREATED_BATCHES)
    db = SessionLocal()
    try:
        # Ordem respeita o FK observations.batch_id -> observation_batches.id.
        db.execute(text("DELETE FROM observations WHERE batch_id = ANY(:ids)"), {"ids": ids})
        db.execute(text("DELETE FROM observation_batches WHERE id = ANY(:ids)"), {"ids": ids})
        db.commit()
        return len(ids)
    finally:
        db.close()
        _CREATED_BATCHES.clear()


@pytest.fixture(autouse=True)
def _garante_limpeza():
    yield
    _cleanup_tracked()


def _porta_livre() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    porta = s.getsockname()[1]
    s.close()
    return porta


@pytest.fixture(scope="module")
def _servidor():
    import uvicorn

    porta = _porta_livre()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=porta, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{porta}/health", timeout=1) as resp:
                if resp.status == 200:
                    break
        except Exception:  # noqa: BLE001
            time.sleep(0.1)
    else:
        raise RuntimeError("uvicorn de teste nao ficou pronto em 20s")
    yield f"http://127.0.0.1:{porta}"
    server.should_exit = True
    thread.join(timeout=10)


PAYLOAD = {
    "person": [{"confidence": 0.93, "bounding_box_xyxy": [150, 150, 350, 450]}],
    "helmet": [{"confidence": 0.90, "bounding_box_xyxy": [190, 100, 310, 170]}],
}
AREA = {"x1": 0, "y1": 0, "x2": 1000, "y2": 1000}


def _novo_received_at():
    """Timestamp único por teste: chave (camera_id, received_at) não colide.

    Motivo: T1 e T2 usavam o mesmo _RUN_AT de módulo; a idempotência do
    servidor então mascarava vazamento entre testes. Cada teste gera o seu.
    """
    return datetime.now(timezone.utc)


def test_t1_isolado_envio_real_cria_batch(_servidor, tmp_path):
    run_at = _novo_received_at()
    before_b = _scalar("SELECT count(*) FROM observation_batches")
    before_o = _scalar("SELECT count(*) FROM observations")
    try:
        out = process_and_ingest(PAYLOAD, log=EventLog(Path(tmp_path) / "t1.jsonl"),
                                 debounce=EventDebounce(), risk_area=AREA,
                                 received_at=run_at, api_base=_servidor)
        assert out["status"] == "created", out
        assert out["events"] == 2, out
        assert out["batch_id"] is not None
        _track(out["batch_id"])
        assert _scalar("SELECT count(*) FROM observation_batches") == before_b + 1
        assert _scalar("SELECT count(*) FROM observations") == before_o + 2
    finally:
        _cleanup_tracked()


def test_t2_isolado_reenvio_e_idempotente(_servidor, tmp_path):
    run_at = _novo_received_at()
    before_b = _scalar("SELECT count(*) FROM observation_batches")
    before_o = _scalar("SELECT count(*) FROM observations")
    try:
        out1 = process_and_ingest(PAYLOAD, log=EventLog(Path(tmp_path) / "t2a.jsonl"),
                                  debounce=EventDebounce(), risk_area=AREA,
                                  received_at=run_at, api_base=_servidor)
        assert out1["status"] in ("created", "duplicate"), out1
        if out1["batch_id"] is not None:
            _track(out1["batch_id"])
        mid_b = _scalar("SELECT count(*) FROM observation_batches")
        mid_o = _scalar("SELECT count(*) FROM observations")
        out2 = process_and_ingest(PAYLOAD, log=EventLog(Path(tmp_path) / "t2b.jsonl"),
                                  debounce=EventDebounce(), risk_area=AREA,
                                  received_at=run_at, api_base=_servidor)
        assert out2["status"] == "duplicate", out2
        assert _scalar("SELECT count(*) FROM observation_batches") == mid_b
        assert _scalar("SELECT count(*) FROM observations") == mid_o
    finally:
        _cleanup_tracked()
        assert _scalar("SELECT count(*) FROM observation_batches") == before_b
        assert _scalar("SELECT count(*) FROM observations") == before_o


def test_t3_isolado_sem_area_nao_envia(_servidor, tmp_path):
    run_at = _novo_received_at()
    try:
        before_b = _scalar("SELECT count(*) FROM observation_batches")
        out = process_and_ingest(PAYLOAD, log=EventLog(Path(tmp_path) / "t3.jsonl"),
                                 debounce=EventDebounce(), risk_area=None,
                                 received_at=run_at, api_base=_servidor)
        assert out["status"] == "no_events", out
        assert out["events"] == 0
        assert out["batch_id"] is None
        assert _scalar("SELECT count(*) FROM observation_batches") == before_b
    finally:
        _cleanup_tracked()


def test_t4_isolado_servidor_inacessivel_unreachable():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    porta_morta = s.getsockname()[1]
    s.close()
    payload = build_ingest_payload(PAYLOAD, [], camera_id="camera_1")
    result = send_batch(payload, api_base=f"http://127.0.0.1:{porta_morta}", connect_attempts=2)
    assert result.status == "unreachable", result
    assert result.batch_id is None


def test_t5_isolado_camera_desconhecida_rejected(_servidor):
    try:
        before_b = _scalar("SELECT count(*) FROM observation_batches")
        before_o = _scalar("SELECT count(*) FROM observations")
        payload = build_ingest_payload(PAYLOAD, [], camera_id="camera_inexistente")
        result = send_batch(payload, api_base=_servidor)
        assert result.status == "rejected", result
        assert "404" in result.detail, result.detail
        assert _scalar("SELECT count(*) FROM observation_batches") == before_b
        assert _scalar("SELECT count(*) FROM observations") == before_o
    finally:
        _cleanup_tracked()
