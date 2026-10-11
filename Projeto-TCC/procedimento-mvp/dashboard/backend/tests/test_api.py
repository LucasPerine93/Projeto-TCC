"""Testes mínimos da base do backend.

Regras:
- não inserem dados fictícios no PostgreSQL;
- não apagam dados existentes;
- apenas consultam os endpoints e validam status/formato/seed.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


# ============================================================
# /health
# ============================================================

def test_health_returns_200_and_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ============================================================
# /health/db
# ============================================================

def test_health_db_returns_200_and_database_name() -> None:
    response = client.get("/health/db")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    # Banco EFETIVAMENTE configurado (sem hardcode de ambiente): o nome
    # reportado deve ser o dbname da DATABASE_URL ativa (tcc_ppe ou
    # tcc_ppe_test conforme onde os testes foram executados).
    from urllib.parse import urlparse

    from app.config import get_settings

    esperado = urlparse(get_settings().database_url).path.lstrip("/")
    assert esperado
    assert body["database"] == esperado


# ============================================================
# /api/cameras
# ============================================================

def test_cameras_returns_200_and_seed_camera() -> None:
    response = client.get("/api/cameras")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)

    codes = [c["code"] for c in body]
    assert "camera_1" in codes

    camera = next(c for c in body if c["code"] == "camera_1")
    assert camera["name"] == "Câmera 1"
    assert camera["active"] is True
    assert set(camera.keys()) >= {"id", "code", "name", "location", "active"}


# ============================================================
# /api/epis
# ============================================================

def test_epis_returns_200_and_seed_epis() -> None:
    response = client.get("/api/epis")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)

    by_code = {e["code"]: e for e in body}
    assert "helmet" in by_code
    assert "vest" in by_code
    assert by_code["helmet"]["name"] == "Capacete"
    assert by_code["vest"]["name"] == "Colete"


# ============================================================
# /api/event-types
# ============================================================

def test_event_types_returns_200_and_seed_events() -> None:
    response = client.get("/api/event-types")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)

    codes = {e["code"] for e in body}
    expected = {
        "pessoa_com_capacete",
        "pessoa_sem_capacete",
        "pessoa_com_colete",
        "pessoa_sem_colete",
    }
    assert expected.issubset(codes)

    by_code = {e["code"]: e for e in body}
    assert by_code["pessoa_com_capacete"]["epi_code"] == "helmet"
    assert by_code["pessoa_com_capacete"]["compliant"] is True
    assert by_code["pessoa_sem_capacete"]["compliant"] is False
    assert by_code["pessoa_com_colete"]["epi_code"] == "vest"
    assert by_code["pessoa_sem_colete"]["compliant"] is False


# ============================================================
# /api/risk-areas
# ============================================================

def test_risk_areas_returns_200_and_list_format() -> None:
    response = client.get("/api/risk-areas")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    # O seed não cria áreas de risco; a lista pode ser vazia,
    # mas cada item (se existir) deve ter o formato esperado.
    for area in body:
        assert set(area.keys()) >= {
            "id",
            "camera_id",
            "camera_code",
            "name",
            "x1",
            "y1",
            "x2",
            "y2",
            "active",
        }
        assert area["x2"] > area["x1"]
        assert area["y2"] > area["y1"]
