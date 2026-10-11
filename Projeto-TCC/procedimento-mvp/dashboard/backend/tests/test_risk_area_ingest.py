"""Teste D — persistência da área de risco e idempotência (banco de testes).

SEGURANÇA: guardas no import — aborta SEM ESCREVER se o banco alvo não
for tcc_ppe_test (protege tcc_ppe e qualquer outro destino não autorizado).

Cobertura: observação inserida; campos preservados; risk_area_id associado
quando as coordenadas casam; NULL quando não há correspondência/área inativa;
consulta via endpoint; idempotência de reenvio; limpeza total no finally
(batches, observations e risk_areas criados por este arquivo).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.database import SessionLocal, engine
from app.main import app

# ---------------------------------------------------------------------------
# Guarda 1: banco de destino confirmado antes de QUALQUER escrita.
# ---------------------------------------------------------------------------
with engine.connect() as _conn:
    _TARGET_DB = _conn.execute(text("SELECT current_database()")).scalar_one()
assert _TARGET_DB == "tcc_ppe_test", (
    f"Banco alvo '{_TARGET_DB}' NÃO é 'tcc_ppe_test' — teste abortado "
    "sem nenhuma escrita. Execute com DATABASE_URL do banco de teste."
)

client = TestClient(app)

_CREATED_BATCHES: list[int] = []
_CREATED_AREAS: list[int] = []
_AREA_NAME = f"teste_risk_{uuid.uuid4().hex[:8]}"


def _camera_pk() -> int:
    db = SessionLocal()
    try:
        pk = db.execute(
            text("SELECT id FROM cameras WHERE code = 'camera_1'")
        ).scalar_one_or_none()
    finally:
        db.close()
    assert pk is not None, "seed camera_1 ausente no banco de teste"
    return int(pk)


def _add_area(*, x1, y1, x2, y2, active=True) -> int:
    db = SessionLocal()
    try:
        area_id = db.execute(
            text(
                "INSERT INTO risk_areas (camera_id, name, x1, y1, x2, y2, active) "
                "VALUES (:cam, :nome, :x1, :y1, :x2, :y2, :active) RETURNING id"
            ),
            {
                "cam": _camera_pk(),
                "nome": _AREA_NAME,
                "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                "active": active,
            },
        ).scalar_one()
        db.commit()
    finally:
        db.close()
    _CREATED_AREAS.append(int(area_id))
    return int(area_id)


def _batch_risk_area(batch_id: int):
    db = SessionLocal()
    try:
        return db.execute(
            text("SELECT risk_area_id FROM observation_batches WHERE id = :bid"),
            {"bid": batch_id},
        ).scalar_one_or_none()
    finally:
        db.close()


def _cleanup() -> None:
    """Remove APENAS o que este arquivo criou (seeds intactos)."""
    if not _CREATED_BATCHES and not _CREATED_AREAS:
        return
    db = SessionLocal()
    try:
        if _CREATED_BATCHES:
            db.execute(
                text("DELETE FROM observations WHERE batch_id = ANY(:ids)"),
                {"ids": _CREATED_BATCHES},
            )
            db.execute(
                text("DELETE FROM observation_batches WHERE id = ANY(:ids)"),
                {"ids": _CREATED_BATCHES},
            )
        if _CREATED_AREAS:
            db.execute(
                text("DELETE FROM risk_areas WHERE id = ANY(:ids)"),
                {"ids": _CREATED_AREAS},
            )
        db.commit()
    finally:
        db.close()
        _CREATED_BATCHES.clear()
        _CREATED_AREAS.clear()


def _payload(**over) -> dict:
    base = {
        "camera_id": "camera_1",
        "raw_detections": {
            "person": [
                {"confidence": 0.93, "bounding_box_xyxy": [150.0, 150.0, 350.0, 450.0]}
            ],
        },
        "observations": [
            {
                "event": "pessoa_sem_capacete",
                "message": "Pessoa 0: capacete não associado dentro da área.",
                "metadata": {
                    "label": "person",
                    "confidence": 0.93,
                    "bbox": [150.0, 150.0, 350.0, 450.0],
                    "camera_id": "camera_1",
                    "person_ref": 0,
                    "context": "inside",
                    "conf_pessoa": 0.93,
                    "conf_epi": None,
                    "bbox_epi": None,
                },
            }
        ],
    }
    base.update(over)
    return base


# ============================================================
# Casos
# ============================================================


def test_risk_area_correspondente_e_preservada_no_batch() -> None:
    try:
        area_id = _add_area(x1=10.0, y1=10.0, x2=600.0, y2=600.0)
        # Coordenadas INVERTIDAS no payload: servidor normaliza min/max.
        payload = _payload(
            risk_area={"x1": 600.0, "y1": 600.0, "x2": 10.0, "y2": 10.0}
        )
        r = client.post("/api/observations/ingest", json=payload)
        assert r.status_code == 201, r.text
        batch_id = r.json()["batch_id"]
        _CREATED_BATCHES.append(batch_id)
        assert _batch_risk_area(batch_id) == area_id
    finally:
        _cleanup()


def test_sem_risk_area_no_payload_permite_null() -> None:
    try:
        r = client.post("/api/observations/ingest", json=_payload())
        assert r.status_code == 201, r.text
        batch_id = r.json()["batch_id"]
        _CREATED_BATCHES.append(batch_id)
        assert _batch_risk_area(batch_id) is None
    finally:
        _cleanup()


def test_coordenadas_sem_correspondencia_nao_inventa_id() -> None:
    try:
        _add_area(x1=10.0, y1=10.0, x2=600.0, y2=600.0)
        payload = _payload(
            risk_area={"x1": 9000.0, "y1": 9000.0, "x2": 9900.0, "y2": 9900.0}
        )
        r = client.post("/api/observations/ingest", json=payload)
        assert r.status_code == 201, r.text
        batch_id = r.json()["batch_id"]
        _CREATED_BATCHES.append(batch_id)
        assert _batch_risk_area(batch_id) is None, "não pode inventar risk_area_id"
    finally:
        _cleanup()


def test_area_inativa_nao_e_associada() -> None:
    try:
        _add_area(x1=5.0, y1=5.0, x2=50.0, y2=50.0, active=False)
        payload = _payload(
            risk_area={"x1": 5.0, "y1": 5.0, "x2": 50.0, "y2": 50.0}
        )
        r = client.post("/api/observations/ingest", json=payload)
        assert r.status_code == 201, r.text
        batch_id = r.json()["batch_id"]
        _CREATED_BATCHES.append(batch_id)
        assert _batch_risk_area(batch_id) is None, "área inativa não pode casar"
    finally:
        _cleanup()


def test_endpoint_de_lista_expoe_risk_area_id() -> None:
    try:
        area_id = _add_area(x1=20.0, y1=20.0, x2=700.0, y2=500.0)
        payload = _payload(
            risk_area={"x1": 20.0, "y1": 20.0, "x2": 700.0, "y2": 500.0}
        )
        r = client.post("/api/observations/ingest", json=payload)
        assert r.status_code == 201, r.text
        batch_id = r.json()["batch_id"]
        _CREATED_BATCHES.append(batch_id)

        body = client.get(
            "/api/observations", params={"camera_code": "camera_1", "limit": 200}
        ).json()
        mine = [i for i in body["items"] if i["batch_id"] == batch_id]
        assert len(mine) == 1
        assert mine[0]["risk_area_id"] == area_id
        assert mine[0]["person_ref"] == 0
        assert mine[0]["event_code"] == "pessoa_sem_capacete"
        assert mine[0]["compliant"] is False
    finally:
        _cleanup()


def test_reenvio_idempotente_nao_duplica_e_mantem_risk_area() -> None:
    try:
        area_id = _add_area(x1=30.0, y1=30.0, x2=400.0, y2=400.0)
        received = datetime.now(timezone.utc).isoformat()
        payload = _payload(
            received_at=received,
            risk_area={"x1": 30.0, "y1": 30.0, "x2": 400.0, "y2": 400.0},
        )
        r1 = client.post("/api/observations/ingest", json=payload)
        assert r1.status_code == 201, r1.text
        _CREATED_BATCHES.append(r1.json()["batch_id"])

        r2 = client.post("/api/observations/ingest", json=payload)
        assert r2.status_code == 201, r2.text
        assert r1.json()["duplicate"] is False
        assert r2.json()["duplicate"] is True
        assert r2.json()["batch_id"] == r1.json()["batch_id"]
        assert r2.json()["observations_created"] == 0
        assert _batch_risk_area(r1.json()["batch_id"]) == area_id
    finally:
        _cleanup()
