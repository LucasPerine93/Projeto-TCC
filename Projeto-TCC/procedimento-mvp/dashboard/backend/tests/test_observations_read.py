"""Testes somente-leitura de GET /api/observations e /api/observations/summary.

Regras (mesmas de test_api.py):
- não inserem dados fictícios no PostgreSQL;
- não apagam dados existentes;
- apenas consultam os endpoints e validam status, formato e consistência
  interna com o conteúdo real (possivelmente vazio) do banco.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.database import SessionLocal
from app.main import app

client = TestClient(app)

_LIST_KEYS = {
    "id",
    "created_at",
    "batch_id",
    "camera_code",
    "camera_name",
    "event_code",
    "event_description",
    "compliant",
    "epi_code",
    "epi_name",
    "context",
    "person_ref",
    "event_confidence",
    "conf_pessoa",
    "conf_epi",
}

_SUMMARY_KEYS = {
    "total_observations",
    "compliant_observations",
    "non_compliant_observations",
    "compliance_rate",
    "by_day",
    "by_camera",
    "by_event_type",
}


# ============================================================
# GET /api/observations
# ============================================================


def test_list_observations_returns_200_and_shape() -> None:
    response = client.get("/api/observations")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) >= {"total", "items"}
    assert isinstance(body["total"], int)
    assert isinstance(body["items"], list)
    assert body["total"] >= len(body["items"])
    assert len(body["items"]) <= 50  # limite padrão
    for item in body["items"]:
        assert set(item.keys()) >= _LIST_KEYS
        assert isinstance(item["compliant"], bool)
        assert 0.0 <= item["event_confidence"] <= 1.0
        assert item["context"] in ("inside", "outside", "no_area", "indeterminate")


def test_list_observations_invalid_limit_returns_422() -> None:
    assert client.get("/api/observations", params={"limit": 0}).status_code == 422
    assert client.get("/api/observations", params={"limit": 201}).status_code == 422
    assert client.get("/api/observations", params={"offset": -1}).status_code == 422


def test_list_observations_unknown_camera_returns_empty() -> None:
    response = client.get(
        "/api/observations", params={"camera_code": "camera_inexistente"}
    )
    assert response.status_code == 200
    assert response.json() == {"total": 0, "items": []}


def test_list_observations_filters_accepted() -> None:
    cases = [
        {"camera_code": "camera_1"},
        {"event_type_code": "pessoa_com_capacete"},
        {"compliant": True},
        {"compliant": False},
        {"date_from": "2020-01-01T00:00:00", "date_to": "2100-01-01T00:00:00"},
        {"camera_code": "camera_1", "compliant": False},
    ]
    for params in cases:
        response = client.get("/api/observations", params=params)
        assert response.status_code == 200, params
        assert isinstance(response.json()["items"], list)


def test_list_observations_invalid_period_returns_422() -> None:
    response = client.get(
        "/api/observations",
        params={
            "date_from": "2026-02-01T00:00:00",
            "date_to": "2026-01-01T00:00:00",
        },
    )
    assert response.status_code == 422


# ============================================================
# GET /api/observations/summary
# ============================================================


def test_summary_returns_200_and_shape() -> None:
    response = client.get("/api/observations/summary")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) >= _SUMMARY_KEYS
    for bucket in ("by_day", "by_camera", "by_event_type"):
        assert isinstance(body[bucket], list)


def test_summary_counts_are_consistent() -> None:
    body = client.get("/api/observations/summary").json()
    total = body["total_observations"]
    compliant = body["compliant_observations"]
    non_compliant = body["non_compliant_observations"]
    assert compliant + non_compliant == total
    if total == 0:
        assert body["compliance_rate"] is None
    else:
        assert body["compliance_rate"] is not None
        assert abs(body["compliance_rate"] - compliant / total) < 0.001


def test_summary_buckets_sum_to_total() -> None:
    body = client.get("/api/observations/summary").json()
    total = body["total_observations"]
    assert sum(b["total"] for b in body["by_day"]) == total
    assert sum(b["total"] for b in body["by_camera"]) == total
    assert sum(b["total"] for b in body["by_event_type"]) == total
    for b in body["by_day"]:
        assert b["compliant"] + b["non_compliant"] == b["total"]
        assert len(b["date"]) == 10  # YYYY-MM-DD


def test_summary_respects_compliant_filter() -> None:
    body = client.get(
        "/api/observations/summary", params={"compliant": True}
    ).json()
    assert body["non_compliant_observations"] == 0
    assert body["compliant_observations"] == body["total_observations"]


def test_summary_invalid_period_returns_422() -> None:
    response = client.get(
        "/api/observations/summary",
        params={
            "date_from": "2026-02-01T00:00:00",
            "date_to": "2026-01-01T00:00:00",
        },
    )
    assert response.status_code == 422


# ============================================================
# CORS (libera o frontend React em http://localhost:5173)
# ============================================================


def test_cors_allows_frontend_origin() -> None:
    response = client.get(
        "/api/cameras", headers={"Origin": "http://localhost:5173"}
    )
    assert response.status_code == 200
    assert (
        response.headers.get("access-control-allow-origin")
        == "http://localhost:5173"
    )


# ============================================================
# Caminho COM dados: ingestão temporária -> leitura -> limpeza.
# Mesmo padrão de test_ingest.py: apaga apenas os batches criados
# por este teste; seeds e dados de terceiros intactos.
# ============================================================

_CREATED_BATCHES: list[int] = []


def _cleanup_read_test() -> None:
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


def _payload_2obs() -> dict:
    """1 lote com 2 observações: 1 conforme + 1 não conforme."""
    base_md = {
        "confidence": 0.9,
        "bbox": [150.0, 150.0, 350.0, 450.0],
        "camera_id": "camera_1",
        "person_ref": 0,
        "context": "inside",
        "conf_pessoa": 0.93,
    }
    return {
        "camera_id": "camera_1",
        "raw_detections": {
            "person": [
                {
                    "confidence": 0.93,
                    "bounding_box_xyxy": [150.0, 150.0, 350.0, 450.0],
                }
            ],
        },
        "observations": [
            {
                "event": "pessoa_com_capacete",
                "message": "Pessoa 0: capacete associado dentro da área.",
                "metadata": {
                    **base_md,
                    "label": "helmet",
                    "conf_epi": 0.9,
                    "bbox_epi": [190.0, 100.0, 310.0, 170.0],
                },
            },
            {
                "event": "pessoa_sem_colete",
                "message": "Pessoa 1: colete não associado dentro da área.",
                "metadata": {
                    **base_md,
                    "label": "person",
                    "person_ref": 1,
                    "conf_epi": None,
                    "bbox_epi": None,
                },
            },
        ],
    }


def test_read_endpoints_with_ingested_data() -> None:
    try:
        r = client.post("/api/observations/ingest", json=_payload_2obs())
        assert r.status_code == 201, r.text
        batch_id = r.json()["batch_id"]
        _CREATED_BATCHES.append(batch_id)

        # --- Lista ---
        body = client.get(
            "/api/observations", params={"camera_code": "camera_1"}
        ).json()
        mine = [i for i in body["items"] if i["batch_id"] == batch_id]
        assert len(mine) == 2
        by_code = {i["event_code"]: i for i in mine}
        assert set(by_code) == {"pessoa_com_capacete", "pessoa_sem_colete"}
        assert by_code["pessoa_com_capacete"]["compliant"] is True
        assert by_code["pessoa_com_capacete"]["epi_code"] == "helmet"
        assert by_code["pessoa_sem_colete"]["compliant"] is False
        assert by_code["pessoa_sem_colete"]["conf_epi"] is None
        assert body["total"] >= 2

        # --- Filtros ---
        only_ok = client.get(
            "/api/observations", params={"compliant": True}
        ).json()
        assert all(i["compliant"] for i in only_ok["items"])
        only_bad = client.get(
            "/api/observations", params={"compliant": False}
        ).json()
        assert all(not i["compliant"] for i in only_bad["items"])
        by_event = client.get(
            "/api/observations",
            params={"event_type_code": "pessoa_com_capacete"},
        ).json()
        assert all(
            i["event_code"] == "pessoa_com_capacete" for i in by_event["items"]
        )

        # --- Resumo ---
        s = client.get(
            "/api/observations/summary", params={"camera_code": "camera_1"}
        ).json()
        assert s["total_observations"] >= 2
        assert (
            s["compliant_observations"] + s["non_compliant_observations"]
            == s["total_observations"]
        )
        assert s["compliance_rate"] is not None
        assert 0.0 <= s["compliance_rate"] <= 1.0
        assert any(b["camera_code"] == "camera_1" for b in s["by_camera"])
        assert any(
            e["event_code"] == "pessoa_com_capacete"
            for e in s["by_event_type"]
        )
        assert sum(b["total"] for b in s["by_day"]) == s["total_observations"]
        assert (
            sum(b["total"] for b in s["by_camera"]) == s["total_observations"]
        )
    finally:
        _cleanup_read_test()