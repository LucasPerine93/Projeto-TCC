"""Teste CONTROLADO de ponta a ponta (sem camera fisica).

Valida a cadeia:
    payload de deteccao (simulado)
        -> vision_integration.process_frame()  (pipeline REAL)
        -> ObservationEvent                  (gerado pelo pipeline REAL)
        -> build_ingest_payload()            (adaptador REAL)
        -> POST /api/observations/ingest    (endpoint REAL)
        -> PostgreSQL                       (persistencia REAL)

Apenas a ORIGEM da deteccao e simulada (payload controlado). Nada do
pipeline/ingest/schema/banco e simulado.

Casos: A (com capacete), B (sem capacete), C (>1 deteccao), D (nenhuma
conformidade), E (evento invalido/rollback), F (raw_detections preservado),
G (mapeamentos), H (EventLog + isolamento SM), I (repeticao 3 payloads).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# 1) Setup de importacao: vision_integration + event_arch + backend
# ---------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent
RAIZ = HERE.parent  # repo root

sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "vision_integration"))
sys.path.insert(0, str(RAIZ / "event_arch"))
sys.path.insert(0, str(RAIZ / "dashboard" / "backend"))

os.chdir(RAIZ / "dashboard" / "backend")
from dotenv import load_dotenv  # noqa: E402
load_dotenv()

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from vision_integration.pipeline import process_frame  # noqa: E402
from vision_integration.ingest_payload import build_ingest_payload  # noqa: E402

from event_log import EventLog  # noqa: E402
from event_debounce import EventDebounce  # noqa: E402

client = TestClient(app)

_CREATED_BATCHES = []


def _track(batch_id):
    _CREATED_BATCHES.append(batch_id)


def _cleanup():
    """Remove apenas batches/observations criados por este teste (seeds intactos)."""
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


# ---------------------------------------------------------------------------
# 2) Guardas de arquitetura: pipeline NAO pode tocar State Machine / ingest
# ---------------------------------------------------------------------------
import state_machine as sm_mod  # noqa: E402
import event_ingest as ei_mod  # noqa: E402

sm_original = sm_mod.ProcedureStateMachine.process_event
ingest_original = ei_mod.ingerir_evento
_sm_calls = {"n": 0}


def _sm_espia(self, event):
    _sm_calls["n"] += 1
    return sm_original(self, event)


def _ingest_espia(*a, **k):
    _sm_calls["n"] += 1
    return ingest_original(*a, **k)


sm_mod.ProcedureStateMachine.process_event = _sm_espia
ei_mod.ingerir_evento = _ingest_espia

# Guarda extra: modulos do vision_integration NAO importam SM/ingest/bridge.
_vi_dir = RAIZ / "vision_integration"
for _f in _vi_dir.glob("*.py"):
    for _line in _f.read_text(encoding="utf-8").splitlines():
        _s = _line.strip()
        if (_s.startswith("import ") or _s.startswith("from ")) and any(
            p in _s for p in ("state_machine", "event_ingest", "vision_bridge")
        ):
            raise AssertionError(_f.name + " importa modulo proibido: " + _s)
print("[GUARDA] vision_integration sem imports de SM/ingest/bridge")


# ---------------------------------------------------------------------------
# 3) Area de risco cobrindo a regiao de teste (coordenadas do frame)
# ---------------------------------------------------------------------------
AREA = {"x1": 0.0, "y1": 0.0, "x2": 1000.0, "y2": 1000.0}


def make_log(tmpdir):
    return EventLog(Path(tmpdir) / "e2e_obs.jsonl")


def make_debounce():
    """Debounce REAL (nao desabilitado) — contrato v3.4.2."""
    return EventDebounce()


# ---------------------------------------------------------------------------
# 4) Helpers de assercao de DB
# ---------------------------------------------------------------------------
def _scalar(sql, params=None):
    db = SessionLocal()
    try:
        return db.execute(text(sql), params or {}).scalar_one()
    finally:
        db.close()


def _query(sql, params=None):
    db = SessionLocal()
    try:
        return db.execute(text(sql), params or {}).mappings().all()
    finally:
        db.close()


# ===========================================================================
# CASO A — pessoa com capacete
# ===========================================================================
def test_caso_A_pessoa_com_capacete(tmp_path):
    log = make_log(str(tmp_path))
    deb = make_debounce()
    payload = {
        "person": [{"confidence": 0.93, "bounding_box_xyxy": [150.0, 150.0, 350.0, 450.0]}],
        "helmet": [{"confidence": 0.90, "bounding_box_xyxy": [190.0, 100.0, 310.0, 170.0]}],
    }
    n_written, events = process_frame(payload, log, deb, risk_area=AREA)
    assert any(e.event == "pessoa_com_capacete" for e in events), [e.event for e in events]
    assert any(e.event == "pessoa_sem_colete" for e in events), [e.event for e in events]

    ing = build_ingest_payload(payload, events, camera_id="camera_1",
                               model_name="ei-model-1127250-2")
    resp = client.post("/api/observations/ingest", json=ing.model_dump())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    _track(body["batch_id"])
    bid = body["batch_id"]

    rows = _query(
        "SELECT et.code, o.person_ref, o.context, o.source FROM observations o "
        "JOIN event_types et ON et.id = o.event_type_id "
        "WHERE o.batch_id = :bid ORDER BY o.id",
        {"bid": bid},
    )
    codes = [r["code"] for r in rows]
    assert "pessoa_com_capacete" in codes
    assert "pessoa_sem_colete" in codes
    for r in rows:
        assert r["source"] == "visao_computacional"
        assert r["context"] == "inside"
    print("[CASO A] batch_id=" + str(bid) + ", observations=" + str(len(rows)) + ", codes=" + str(codes))


# ===========================================================================
# CASO B — pessoa sem capacete (conf_epi/bbox_epi NULL)
# ===========================================================================
def test_caso_B_pessoa_sem_capacete(tmp_path):
    log = make_log(str(tmp_path))
    deb = make_debounce()
    payload = {
        "person": [{"confidence": 0.91, "bounding_box_xyxy": [50.0, 50.0, 200.0, 400.0]}],
    }
    n_written, events = process_frame(payload, log, deb, risk_area=AREA)
    assert any(e.event == "pessoa_sem_capacete" for e in events), [e.event for e in events]

    ing = build_ingest_payload(payload, events, camera_id="camera_1")
    resp = client.post("/api/observations/ingest", json=ing.model_dump())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    _track(body["batch_id"])
    bid = body["batch_id"]

    rows = _query(
        "SELECT et.code, o.conf_epi, o.epi_bbox_x1, o.epi_bbox_y1 "
        "FROM observations o JOIN event_types et ON et.id = o.event_type_id "
        "WHERE o.batch_id = :bid AND et.code = 'pessoa_sem_capacete'",
        {"bid": bid},
    )
    assert len(rows) == 1
    r = rows[0]
    assert r["conf_epi"] is None, "conf_epi esperado NULL, veio " + str(r["conf_epi"])
    assert r["epi_bbox_x1"] is None, "epi_bbox X esperado NULL, veio " + str(r["epi_bbox_x1"])
    assert r["epi_bbox_y1"] is None
    print("[CASO B] batch_id=" + str(bid) + ", pessoa_sem_capacete conf_epi=NULL, bbox_epi=NULL")


# ===========================================================================
# CASO C — mais de uma deteccao (2 pessoas + EPIs: sem cruzamento)
# ===========================================================================
def test_caso_C_multiplas_pessoas(tmp_path):
    log = make_log(str(tmp_path))
    deb = make_debounce()
    payload = {
        "person": [
            {"confidence": 0.93, "bounding_box_xyxy": [100.0, 100.0, 300.0, 400.0]},
            {"confidence": 0.92, "bounding_box_xyxy": [500.0, 100.0, 700.0, 400.0]},
        ],
        "helmet": [{"confidence": 0.90, "bounding_box_xyxy": [150.0, 50.0, 250.0, 120.0]}],
    }
    n_written, events = process_frame(payload, log, deb, risk_area=AREA)
    codes = sorted(e.event for e in events)
    assert codes == sorted([
        "pessoa_com_capacete", "pessoa_sem_colete",
        "pessoa_sem_capacete", "pessoa_sem_colete",
    ]), codes
    refs = [e.metadata["person_ref"] for e in events]
    assert refs == [0, 0, 1, 1], refs

    ing = build_ingest_payload(payload, events, camera_id="camera_1")
    resp = client.post("/api/observations/ingest", json=ing.model_dump())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    _track(body["batch_id"])
    assert body["observations_created"] == 4
    bid = body["batch_id"]

    rows = _query(
        "SELECT o.person_ref, et.code FROM observations o "
        "JOIN event_types et ON et.id = o.event_type_id "
        "WHERE o.batch_id = :bid ORDER BY o.id",
        {"bid": bid},
    )
    assert [r["person_ref"] for r in rows] == [0, 0, 1, 1]
    print("[CASO C] batch_id=" + str(bid) + ", 4 observacoes, refs=[0,0,1,1] sem cruzamento")


# ===========================================================================
# CASO D — nenhuma conformidade (payload valido, sem observacoes)
# ===========================================================================
def test_caso_D_nenhuma_conformidade(tmp_path):
    log = make_log(str(tmp_path))
    deb = make_debounce()
    payload = {
        "person": [{"confidence": 0.93, "bounding_box_xyxy": [5000.0, 5000.0, 5200.0, 5400.0]}],
    }
    n_written, events = process_frame(payload, log, deb, risk_area=AREA)
    assert events == [], events

    ing = build_ingest_payload(payload, events, camera_id="camera_1")
    resp = client.post("/api/observations/ingest", json=ing.model_dump())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    _track(body["batch_id"])
    assert body["observations_created"] == 0
    bid = body["batch_id"]

    cnt = _scalar("SELECT COUNT(*) FROM observations WHERE batch_id = :bid", {"bid": bid})
    assert cnt == 0
    print("[CASO D] batch_id=" + str(bid) + " criado com 0 observations (fora da area)")


# ===========================================================================
# CASO E — evento invalido (rollback total, nenhum batch parcial)
# ===========================================================================
def test_caso_E_evento_invalido_rollback(tmp_path):
    from app.schemas import IngestBatchIn, IngestObservationIn, IngestMetadata
    md = IngestMetadata(
        label="person", confidence=0.9,
        bbox=[10.0, 10.0, 100.0, 200.0],
        camera_id="camera_1", person_ref=0, context="inside",
        conf_pessoa=0.9, conf_epi=None, bbox_epi=None,
    )
    ing = IngestBatchIn(
        camera_id="camera_1",
        raw_detections={"person": [{"confidence": 0.9, "bounding_box_xyxy": [10.0, 10.0, 100.0, 200.0]}]},
        model_name="ei-model-1127250-2",
        observations=[IngestObservationIn(event="evento_que_nao_existe",
                                          message="invalido", metadata=md)],
    )
    before_b = _scalar("SELECT COUNT(*) FROM observation_batches")
    before_o = _scalar("SELECT COUNT(*) FROM observations")
    resp = client.post("/api/observations/ingest", json=ing.model_dump())
    assert resp.status_code == 422, resp.text
    assert _scalar("SELECT COUNT(*) FROM observation_batches") == before_b, "batch parcial criado!"
    assert _scalar("SELECT COUNT(*) FROM observations") == before_o, "observation parcial criada!"
    print("[CASO E] evento invalido -> 422, rollback total (batches/obs inalterados)")


# ===========================================================================
# CASO F — raw_detections preservado no PostgreSQL
# ===========================================================================
def test_caso_F_raw_detections_preservado(tmp_path):
    log = make_log(str(tmp_path))
    deb = make_debounce()
    payload = {
        "person": [{"confidence": 0.93, "bounding_box_xyxy": [150.0, 150.0, 350.0, 450.0]}],
        "helmet": [{"confidence": 0.90, "bounding_box_xyxy": [190.0, 100.0, 310.0, 170.0]}],
        "vest": [{"confidence": 0.88, "bounding_box_xyxy": [190.0, 250.0, 310.0, 380.0]}],
    }
    _, events = process_frame(payload, log, deb, risk_area=AREA)
    ing = build_ingest_payload(payload, events, camera_id="camera_1",
                               model_name="ei-model-1127250-2")
    resp = client.post("/api/observations/ingest", json=ing.model_dump())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    _track(body["batch_id"])

    raw = _query(
        "SELECT raw_detections, model_name FROM observation_batches WHERE id = :bid",
        {"bid": body["batch_id"]},
    )
    assert len(raw) == 1
    rd = raw[0]["raw_detections"]
    assert rd["person"][0]["confidence"] == 0.93
    assert rd["person"][0]["bounding_box_xyxy"] == [150.0, 150.0, 350.0, 450.0]
    assert rd["helmet"][0]["confidence"] == 0.90
    assert rd["helmet"][0]["bounding_box_xyxy"] == [190.0, 100.0, 310.0, 170.0]
    assert rd["vest"][0]["confidence"] == 0.88
    assert rd["vest"][0]["bounding_box_xyxy"] == [190.0, 250.0, 310.0, 380.0]
    assert raw[0]["model_name"] == "ei-model-1127250-2"
    print("[CASO F] raw_detections preservado integralmente no PostgreSQL")


# ===========================================================================
# CASO G — mapeamentos camera_1 -> cameras.id e evento -> event_types.id
# ===========================================================================
def test_caso_G_mapeamentos(tmp_path):
    log = make_log(str(tmp_path))
    deb = make_debounce()
    payload = {
        "person": [{"confidence": 0.93, "bounding_box_xyxy": [150.0, 150.0, 350.0, 450.0]}],
        "helmet": [{"confidence": 0.90, "bounding_box_xyxy": [190.0, 100.0, 310.0, 170.0]}],
    }
    _, events = process_frame(payload, log, deb, risk_area=AREA)
    ing = build_ingest_payload(payload, events, camera_id="camera_1")
    resp = client.post("/api/observations/ingest", json=ing.model_dump())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    _track(body["batch_id"])
    bid = body["batch_id"]

    cam_id = _scalar("SELECT id FROM cameras WHERE code = 'camera_1'")
    bid_camera = _scalar("SELECT camera_id FROM observation_batches WHERE id = :bid", {"bid": bid})
    assert bid_camera == cam_id, "camera_id " + str(bid_camera) + " != cameras.id " + str(cam_id)

    for code in ("pessoa_com_capacete", "pessoa_sem_colete"):
        et_id = _scalar("SELECT id FROM event_types WHERE code = :c", {"c": code})
        cnt = _scalar(
            "SELECT COUNT(*) FROM observations o WHERE o.batch_id = :bid AND o.event_type_id = :eid",
            {"bid": bid, "eid": et_id},
        )
        assert cnt == 1, code + ": esperado 1, veio " + str(cnt)
    print("[CASO G] camera_1 -> cameras.id=" + str(cam_id) + "; eventos mapeados para event_types.id")


# ===========================================================================
# CASO H — EventLog + isolamento da State Machine
# ===========================================================================
def test_caso_H_eventlog_e_isolamento(tmp_path):
    # Zera o contador: sob pytest, scripts standalone importados na coleta
    # (ex.: test_state_machine.py) executam process_event no import e
    # poluiriam a contagem antes deste teste.
    _sm_calls["n"] = 0
    log = make_log(str(tmp_path))
    deb = make_debounce()
    payload = {
        "person": [{"confidence": 0.93, "bounding_box_xyxy": [150.0, 150.0, 350.0, 450.0]}],
        "helmet": [{"confidence": 0.90, "bounding_box_xyxy": [190.0, 100.0, 310.0, 170.0]}],
    }
    _, events = process_frame(payload, log, deb, risk_area=AREA)

    records = [json.loads(l) for l in log.path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(records) >= 1
    for r in records:
        assert r["status"] == "observation"
        assert r["source"] == "visao_computacional"
        assert r["previous_step"] == 0
        assert r["current_step"] == 0
        assert r["event"] in ("pessoa_com_capacete", "pessoa_sem_capacete",
                              "pessoa_com_colete", "pessoa_sem_colete")
    assert _sm_calls["n"] == 0, "State Machine chamada " + str(_sm_calls["n"]) + "x"
    print("[CASO H] EventLog status=observation/source=visao/steps=0/0; SM=0 chamadas")

    sm_mod.ProcedureStateMachine.process_event = sm_original
    ei_mod.ingerir_evento = ingest_original


# ===========================================================================
# CASO I — repeticao: 3 payloads consecutivos (pipeline -> API -> DB)
# ===========================================================================
def test_caso_I_repeticao_3_payloads(tmp_path):
    log = make_log(str(tmp_path))
    for i in range(3):
        payload = {
            "person": [{"confidence": 0.93, "bounding_box_xyxy": [150.0, 150.0, 350.0, 450.0]}],
            "helmet": [{"confidence": 0.90, "bounding_box_xyxy": [190.0, 100.0, 310.0, 170.0]}],
        }
        _, events = process_frame(payload, log, None, risk_area=AREA)
        ing = build_ingest_payload(payload, events, camera_id="camera_1")
        resp = client.post("/api/observations/ingest", json=ing.model_dump())
        assert resp.status_code == 201, "iter " + str(i) + ": " + resp.text
        _track(resp.json()["batch_id"])
    print("[CASO I] 3 payloads consecutivos -> pipeline -> API -> DB (todos OK)")


# ===========================================================================
# CASO J — camada temporal (occurrence) -> API -> DB -> consulta -> reenvio
# ===========================================================================
def test_caso_J_occurrence_confirmada_persiste_e_consulta(tmp_path):
    from datetime import datetime, timezone

    from vision_integration.occurrence import OccurrenceTracker

    log = make_log(str(tmp_path))
    deb = make_debounce()
    tr = OccurrenceTracker(confirm_frames=2, resolve_frames=2)
    payload = {
        "person": [{"confidence": 0.93, "bounding_box_xyxy": [150.0, 150.0, 350.0, 450.0]}],
        # sem helmet -> evidencia de ausencia; vest presente (estavel)
        "vest": [{"confidence": 0.88, "bounding_box_xyxy": [190.0, 250.0, 310.0, 380.0]}],
    }
    # Frame 1: ausencia ainda NAO confirmada -> nada emitido/persistido.
    n1, ev1 = process_frame(payload, log, deb, risk_area=AREA, occurrence=tr)
    assert n1 == 0 and ev1 == [], (n1, ev1)
    # Frame 2: confirmada -> UMA observacao.
    n2, ev2 = process_frame(payload, log, deb, risk_area=AREA, occurrence=tr)
    assert n2 == 1 and ev2[0].event == "pessoa_sem_capacete", ev2

    received = datetime.now(timezone.utc)
    ing = build_ingest_payload(
        payload, ev2, camera_id="camera_1", received_at=received, risk_area=AREA
    )
    resp = client.post("/api/observations/ingest", json=ing.model_dump(mode="json"))
    assert resp.status_code == 201, resp.text
    bid = resp.json()["batch_id"]
    _track(bid)

    # Reenvio do MESMO ciclo -> idempotente (nao duplica registros).
    resp2 = client.post("/api/observations/ingest", json=ing.model_dump(mode="json"))
    assert resp2.status_code == 201, resp2.text
    assert resp2.json()["duplicate"] is True
    assert resp2.json()["batch_id"] == bid

    # Consulta -> registro unico com campos preservados.
    body = client.get(
        "/api/observations",
        params={"event_type_code": "pessoa_sem_capacete", "limit": 200},
    ).json()
    mine = [i for i in body["items"] if i["batch_id"] == bid]
    assert len(mine) == 1, mine
    assert mine[0]["camera_code"] == "camera_1"
    assert mine[0]["compliant"] is False
    # risk_area_id exposto = valor persistido no batch (nada fabricado).
    db_ra = _scalar(
        "SELECT risk_area_id FROM observation_batches WHERE id = :bid", {"bid": bid}
    )
    assert mine[0]["risk_area_id"] == db_ra
    print(
        "[CASO J] occurrence (2 frames) -> API -> DB -> consulta -> reenvio idempotente"
    )


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
            test_caso_A_pessoa_com_capacete(Path(tmp))
            test_caso_B_pessoa_sem_capacete(Path(tmp))
            test_caso_C_multiplas_pessoas(Path(tmp))
            test_caso_D_nenhuma_conformidade(Path(tmp))
            test_caso_E_evento_invalido_rollback(Path(tmp))
            test_caso_F_raw_detections_preservado(Path(tmp))
            test_caso_G_mapeamentos(Path(tmp))
            test_caso_H_eventlog_e_isolamento(Path(tmp))
            test_caso_I_repeticao_3_payloads(Path(tmp))
            test_caso_J_occurrence_confirmada_persiste_e_consulta(Path(tmp))
    finally:
        # Sempre limpar: no modo script o fixture autouse do pytest não roda.
        _cleanup()
    print("\n[OK] teste e2e de integracao: todos os casos passaram.")
