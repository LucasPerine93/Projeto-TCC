"""Testes da ingestão observacional (POST /api/observations/ingest).

Usam transações com rollback: limpam APENAS batches/observations criados
pelo próprio teste (ids registrados). Seeds (câmera/event_types) intactos.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.database import SessionLocal
from app.main import app

client = TestClient(app)

_CREATED_BATCHES: list[int] = []


def _track(batch_id: int) -> None:
    _CREATED_BATCHES.append(batch_id)


def _cleanup() -> None:
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


def _batch_count() -> int:
    db = SessionLocal()
    try:
        return int(db.execute(text("SELECT COUNT(*) FROM observation_batches")).scalar())
    finally:
        db.close()


def _obs_count() -> int:
    db = SessionLocal()
    try:
        return int(db.execute(text("SELECT COUNT(*) FROM observations")).scalar())
    finally:
        db.close()


def _payload(**over) -> dict:
    base = {
        "camera_id": "camera_1",
        "raw_detections": {
            "person": [{"confidence": 0.93, "bounding_box_xyxy": [150.0, 150.0, 350.0, 450.0]}],
            "helmet": [{"confidence": 0.9, "bounding_box_xyxy": [190.0, 100.0, 310.0, 170.0]}],
        },
        "model_name": "ei-model-1127250-2",
        "model_version": None,
        "observations": [
            {
                "event": "pessoa_com_capacete",
                "message": "Pessoa 0: capacete associado dentro da área de risco.",
                "metadata": {
                    "label": "helmet",
                    "confidence": 0.9,
                    "bbox": [150.0, 150.0, 350.0, 450.0],
                    "camera_id": "camera_1",
                    "person_ref": 0,
                    "context": "inside",
                    "conf_pessoa": 0.93,
                    "conf_epi": 0.9,
                    "bbox_epi": [190.0, 100.0, 310.0, 170.0],
                },
            }
        ],
    }
    base.update(over)
    return base


def test_ingest_lote_valido_cria_batch_e_observation() -> None:
    try:
        r = client.post("/api/observations/ingest", json=_payload())
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["observations_created"] == 1
        _track(body["batch_id"])
    finally:
        _cleanup()


def test_ingest_lote_vazio_cria_batch_sem_observations() -> None:
    try:
        r = client.post("/api/observations/ingest", json=_payload(observations=[]))
        assert r.status_code == 201, r.text
        assert r.json()["observations_created"] == 0
        _track(r.json()["batch_id"])
    finally:
        _cleanup()


def test_ingest_camera_inexistente_falha_sem_gravar() -> None:
    before_b, before_o = _batch_count(), _obs_count()
    r = client.post("/api/observations/ingest", json=_payload(camera_id="camera_x"))
    assert r.status_code == 404
    assert _batch_count() == before_b
    assert _obs_count() == before_o


def test_ingest_evento_desconhecido_faz_rollback_total() -> None:
    before_b, before_o = _batch_count(), _obs_count()
    bad = _payload()
    bad["observations"][0]["event"] = "evento_que_nao_existe"
    r = client.post("/api/observations/ingest", json=bad)
    assert r.status_code == 422
    assert _batch_count() == before_b
    assert _obs_count() == before_o


def test_ingest_confidence_invalida_rejeitada() -> None:
    bad = _payload()
    bad["observations"][0]["metadata"]["confidence"] = 1.5
    r = client.post("/api/observations/ingest", json=bad)
    assert r.status_code == 422


def test_ingest_bbox_invalida_rejeitada() -> None:
    bad = _payload()
    bad["observations"][0]["metadata"]["bbox"] = [1, 2, 3]
    r = client.post("/api/observations/ingest", json=bad)
    assert r.status_code == 422


def test_ingest_transacao_mista_faz_rollback() -> None:
    before_b, before_o = _batch_count(), _obs_count()
    mixed = _payload()
    good = dict(mixed["observations"][0])
    bad = {
        "event": "evento_que_nao_existe",
        "message": "ruim",
        "metadata": dict(good["metadata"]),
    }
    mixed["observations"] = [good, bad]
    r = client.post("/api/observations/ingest", json=mixed)
    assert r.status_code == 422
    assert _batch_count() == before_b
    assert _obs_count() == before_o


def test_ingest_sem_epi_aceita_nulls() -> None:
    try:
        md = {
            "label": "person",
            "confidence": 0.88,
            "bbox": [10.0, 10.0, 100.0, 200.0],
            "camera_id": "camera_1",
            "person_ref": 0,
            "context": "inside",
            "conf_pessoa": 0.88,
            "conf_epi": None,
            "bbox_epi": None,
        }
        p = _payload(observations=[{
            "event": "pessoa_sem_capacete",
            "message": "Pessoa 0: capacete não associado dentro da área de risco.",
            "metadata": md,
        }])
        r = client.post("/api/observations/ingest", json=p)
        assert r.status_code == 201, r.text
        _track(r.json()["batch_id"])
    finally:
        _cleanup()


def test_ingest_reenvio_mesmo_received_at_e_idempotente() -> None:
    """Reenvio do MESMO lote (camera_id + received_at) não duplica registros."""
    try:
        before_b, before_o = _batch_count(), _obs_count()
        # Timestamp fixo compartilhado pelas 2 chamadas = chave de idempotência.
        received = datetime.now(timezone.utc).isoformat()
        p = _payload(received_at=received)

        r1 = client.post("/api/observations/ingest", json=p)
        assert r1.status_code == 201, r1.text
        _track(r1.json()["batch_id"])

        r2 = client.post("/api/observations/ingest", json=p)
        assert r2.status_code == 201, r2.text

        n_obs = len(p["observations"])
        assert r1.json()["duplicate"] is False
        assert r1.json()["observations_created"] == n_obs
        assert r2.json()["duplicate"] is True
        assert r2.json()["observations_created"] == 0
        assert r2.json()["batch_id"] == r1.json()["batch_id"]
        # Exatamente 1 batch novo e n_obs observations novas (nada duplicado).
        assert _batch_count() == before_b + 1
        assert _obs_count() == before_o + n_obs
    finally:
        _cleanup()
