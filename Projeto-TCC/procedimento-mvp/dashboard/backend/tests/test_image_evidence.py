"""Tests for image evidence storage.

- Testes de `image_store` são puros (não tocam o banco).
- Testes de endpoint usam um SQLite em memória isolado via
  `app.dependency_overrides`, portanto rodam sem PostgreSQL.
"""

from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path

import pytest

# Define um DATABASE_URL mínimo ANTES de importar qualquer módulo `app.*`
# que construa o engine (app.database). `setdefault` NÃO sobrescreve um valor
# já existente, preservando a configuração de integração (PostgreSQL) quando
# presente no ambiente.
os.environ.setdefault("DATABASE_URL", "sqlite://")

from app import image_store

TEST_PNG = bytes(
    [
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
        0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,
        0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
        0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53,
        0x64, 0x65, 0x00, 0x00, 0x00, 0x0C, 0x49, 0x44,
        0x41, 0x54, 0x78, 0x9C, 0x63, 0x00, 0x01, 0x00,
        0x00, 0x05, 0x00, 0x01, 0x0D, 0x0A, 0x2D, 0xB4,
        0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4E, 0x44,
        0xAE, 0x42, 0x60, 0x82,
    ]
)


def test_get_image_dir_creates_directory():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["TCC_MVP_ROOT"] = tmp
        try:
            image_dir = image_store.get_image_dir()
            assert image_dir.is_dir()
        finally:
            os.environ.pop("TCC_MVP_ROOT", None)


def test_save_image_evidence_valid_file():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["TCC_MVP_ROOT"] = tmp
        try:
            rec = image_store.save_image_evidence(
                TEST_PNG,
                camera_code="camera_1",
                occurrence_id=1,
                mime_type="image/png",
            )
            assert rec["camera_code"] == "camera_1"
            assert rec["occurrence_id"] == 1
            assert rec["mime_type"] == "image/png"
            assert rec["file_name"].endswith(".png")
            assert rec["sha256"] == image_store.compute_sha256(TEST_PNG)
            image_path = Path(rec["image_path"])
            assert image_path.is_file()
            assert image_path.read_bytes() == TEST_PNG
        finally:
            os.environ.pop("TCC_MVP_ROOT", None)


def test_save_image_evidence_invalid_file_raises_value_error():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["TCC_MVP_ROOT"] = tmp
        try:
            with pytest.raises(ValueError):
                image_store.save_image_evidence(
                    b"not an image",
                    camera_code="camera_1",
                    occurrence_id=1,
                )
        finally:
            os.environ.pop("TCC_MVP_ROOT", None)


def test_save_image_evidence_rejects_non_image_mime():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["TCC_MVP_ROOT"] = tmp
        try:
            with pytest.raises(ValueError):
                image_store.save_image_evidence(
                    TEST_PNG,
                    camera_code="camera_1",
                    occurrence_id=1,
                    mime_type="text/plain",
                )
        finally:
            os.environ.pop("TCC_MVP_ROOT", None)


# ============================================================
# Endpoints (POST/GET /api/images) com SQLite isolado
# ============================================================

@pytest.fixture()
def api_client(tmp_path, monkeypatch):
    """TestClient com get_db sobrescrito para um SQLite em memória isolado.

    Cria apenas a tabela `image_evidence`. Restaura o tipo original da PK
    (BigInteger) no teardown para não afetar outros testes.
    """
    from sqlalchemy import Integer, create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from fastapi.testclient import TestClient

    import app.database as database_module
    from app.main import app
    from app.models import ImageEvidence

    # Salva imagens em dir temporário (não suja o projeto durante o teste).
    monkeypatch.setenv("TCC_MVP_ROOT", str(tmp_path))

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # SQLite não faz autoincrement em BIGINT; Integer -> rowid autoincrementável.
    # (Em PostgreSQL o schema usa GENERATED ... AS IDENTITY — não afeta produção.)
    id_column = ImageEvidence.__table__.c.id
    original_type = id_column.type
    id_column.type = Integer()
    ImageEvidence.__table__.create(bind=engine, checkfirst=True)

    TestingSessionLocal = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[database_module.get_db] = override_get_db
    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()
        ImageEvidence.__table__.drop(bind=engine, checkfirst=True)
        id_column.type = original_type
        engine.dispose()


def test_post_images_valid_returns_201(api_client):
    r = api_client.post(
        "/api/images",
        files={"image": ("ev.png", io.BytesIO(TEST_PNG), "image/png")},
        data={"occurrence_id": "1", "camera_code": "camera_1"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["occurrence_id"] == 1
    assert body["camera_code"] == "camera_1"
    assert body["mime_type"] == "image/png"
    assert body["sha256"] == image_store.compute_sha256(TEST_PNG)
    assert "image_path" not in body  # caminho absoluto nunca exposto


def test_post_images_rejects_non_image(api_client):
    r = api_client.post(
        "/api/images",
        files={"image": ("ev.txt", io.BytesIO(TEST_PNG), "text/plain")},
        data={"occurrence_id": "1", "camera_code": "camera_1"},
    )
    assert r.status_code == 422


def test_post_images_rejects_garbage_bytes(api_client):
    r = api_client.post(
        "/api/images",
        files={"image": ("ev.bin", io.BytesIO(b"not an image"), "application/octet-stream")},
        data={"occurrence_id": "1", "camera_code": "camera_1"},
    )
    assert r.status_code == 422


def test_get_image_by_id_roundtrip(api_client):
    created = api_client.post(
        "/api/images",
        files={"image": ("ev.png", io.BytesIO(TEST_PNG), "image/png")},
        data={"occurrence_id": "7", "camera_code": "camera_2"},
    )
    assert created.status_code == 201, created.text
    image_id = created.json()["id"]

    r = api_client.get(f"/api/images/{image_id}")
    assert r.status_code == 200
    assert r.json()["id"] == image_id
    assert r.json()["camera_code"] == "camera_2"


@pytest.fixture()
def e2e_client(tmp_path, monkeypatch):
    """TestClient com SQLite isolado contendo TODAS as tabelas do fluxo.

    Semeia 1 câmera + 1 event_type válidos. Permite exercitar:
    POST /api/observations/ingest -> observation_ids REAIS ->
    POST /api/images (vincula à ocorrência) -> GET /api/images/{id}.
    """
    from sqlalchemy import Integer, create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from fastapi.testclient import TestClient

    import app.database as database_module
    from app.main import app
    from app.models import (
        Camera, Epi, EventType, ImageEvidence, Observation, ObservationBatch, RiskArea,
    )
    from sqlalchemy import JSON as SqliteJSON

    monkeypatch.setenv("TCC_MVP_ROOT", str(tmp_path))

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # SQLite não faz autoincrement em BIGINT; Integer -> rowid autoincrementável.
    # (Em PostgreSQL o schema usa GENERATED ... AS IDENTITY — não afeta produção.)
    models = (ImageEvidence, Observation, ObservationBatch, Camera, EventType, RiskArea, Epi)
    originals = {}
    for model in models:
        id_col = model.__table__.c.id
        originals[model] = id_col.type
        id_col.type = Integer()
    # JSONB é PostgreSQL-only; SQLite usa JSON. (Teste apenas; schema real intacto.)
    raw_col = ObservationBatch.__table__.c.raw_detections
    originals[("raw", ObservationBatch)] = raw_col.type
    raw_col.type = SqliteJSON()

    # Ordem respeita FKs.
    Epi.__table__.create(bind=engine, checkfirst=True)
    Camera.__table__.create(bind=engine, checkfirst=True)
    EventType.__table__.create(bind=engine, checkfirst=True)
    RiskArea.__table__.create(bind=engine, checkfirst=True)
    ObservationBatch.__table__.create(bind=engine, checkfirst=True)
    Observation.__table__.create(bind=engine, checkfirst=True)
    ImageEvidence.__table__.create(bind=engine, checkfirst=True)

    TestingSessionLocal = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )

    # Seeds mínimos: 1 epi + 1 câmera + 1 event_type (FK epi_id NOT NULL).
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    seed = TestingSessionLocal()
    try:
        epi = Epi(code="capacete", name="Capacete", created_at=now)
        seed.add(epi)
        seed.add(Camera(code="camera_1", name="Câmera 1", created_at=now))
        seed.flush()
        seed.add(
            EventType(
                code="pessoa_sem_capacete",
                description="x",
                epi_id=epi.id,
                compliant=False,
                created_at=now,
            )
        )
        seed.commit()
    finally:
        seed.close()

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[database_module.get_db] = override_get_db
    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()
        for model in models:
            model.__table__.drop(bind=engine, checkfirst=True)
            model.__table__.c.id.type = originals[model]
        raw_col.type = originals[("raw", ObservationBatch)]
        engine.dispose()


def _ingest_payload():
    return {
        "camera_id": "camera_1",
        "raw_detections": {"person": []},
        "observations": [
            {
                "event": "pessoa_sem_capacete",
                "message": "operário sem capacete",
                "metadata": {
                    "label": "person",
                    "confidence": 0.9,
                    "bbox": [10.0, 10.0, 100.0, 200.0],
                    "person_ref": 0,
                    "context": "inside",
                    "conf_pessoa": 0.9,
                },
            }
        ],
    }


def test_ingest_returns_real_observation_ids(e2e_client):
    r = e2e_client.post("/api/observations/ingest", json=_ingest_payload())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["observations_created"] == 1
    assert len(body["observation_ids"]) == 1
    assert body["observation_ids"][0] > 0  # id REAL persistido (não provisório)


def test_full_flow_ingest_then_image_link_then_get(e2e_client):
    """Ocorrência -> id REAL -> imagem vinculada -> recuperada."""
    # 1) Ocorrência persistida -> id real
    ing = e2e_client.post("/api/observations/ingest", json=_ingest_payload())
    assert ing.status_code == 201, ing.text
    real_occ_id = ing.json()["observation_ids"][0]

    # 2) Evidência de imagem vinculada à ocorrência REAL
    img = e2e_client.post(
        "/api/images",
        files={"image": ("frame.png", io.BytesIO(TEST_PNG), "image/png")},
        data={"occurrence_id": str(real_occ_id), "camera_code": "camera_1"},
    )
    assert img.status_code == 201, img.text
    assert img.json()["occurrence_id"] == real_occ_id
    image_id = img.json()["id"]

    # 3) Recuperação: metadados da imagem apontam à ocorrência persistida
    got = e2e_client.get(f"/api/images/{image_id}")
    assert got.status_code == 200
    assert got.json()["occurrence_id"] == real_occ_id
    assert "image_path" not in got.json()  # caminho absoluto nunca exposto


def test_get_image_by_id_not_found(api_client):
    r = api_client.get("/api/images/999999")
    assert r.status_code == 404


# ============================================================
# Listagem por ocorrência + conteúdo binário
# ============================================================

def _upload_to_occurrence(client, occurrence_id: int, camera_code="camera_1"):
    return client.post(
        "/api/images",
        files={"image": ("frame.png", io.BytesIO(TEST_PNG), "image/png")},
        data={"occurrence_id": str(occurrence_id), "camera_code": camera_code},
    )


def test_list_by_occurrence_single(e2e_client):
    ing = e2e_client.post("/api/observations/ingest", json=_ingest_payload())
    assert ing.status_code == 201, ing.text
    occ = ing.json()["observation_ids"][0]
    up = _upload_to_occurrence(e2e_client, occ)
    assert up.status_code == 201, up.text

    r = e2e_client.get(f"/api/images/by-occurrence/{occ}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["occurrence_id"] == occ
    assert body["items"][0]["id"] == up.json()["id"]
    assert "image_path" not in body["items"][0]  # sem caminho absoluto


def test_list_by_occurrence_multiple(e2e_client):
    ing = e2e_client.post("/api/observations/ingest", json=_ingest_payload())
    assert ing.status_code == 201, ing.text
    occ = ing.json()["observation_ids"][0]
    ids = set()
    for _ in range(2):
        up = _upload_to_occurrence(e2e_client, occ)
        assert up.status_code == 201, up.text
        ids.add(up.json()["id"])
    assert len(ids) == 2

    r = e2e_client.get(f"/api/images/by-occurrence/{occ}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2
    assert {it["id"] for it in body["items"]} == ids


def test_list_by_occurrence_empty_for_valid_occurrence(e2e_client):
    ing = e2e_client.post("/api/observations/ingest", json=_ingest_payload())
    assert ing.status_code == 201, ing.text
    occ = ing.json()["observation_ids"][0]

    r = e2e_client.get(f"/api/images/by-occurrence/{occ}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 0
    assert body["items"] == []


def test_list_by_occurrence_unknown_occurrence_404(e2e_client):
    r = e2e_client.get("/api/images/by-occurrence/999999")
    assert r.status_code == 404


def test_content_returns_bytes_and_mime(e2e_client):
    ing = e2e_client.post("/api/observations/ingest", json=_ingest_payload())
    assert ing.status_code == 201, ing.text
    occ = ing.json()["observation_ids"][0]
    up = _upload_to_occurrence(e2e_client, occ)
    assert up.status_code == 201, up.text
    image_id = up.json()["id"]

    r = e2e_client.get(f"/api/images/{image_id}/content")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("image/png")
    assert r.content == TEST_PNG  # bytes idênticos aos enviados


def test_content_unknown_image_404(e2e_client):
    r = e2e_client.get("/api/images/999999/content")
    assert r.status_code == 404


def test_content_missing_file_404(e2e_client, tmp_path):
    from app import image_store as image_store_module

    ing = e2e_client.post("/api/observations/ingest", json=_ingest_payload())
    assert ing.status_code == 201, ing.text
    occ = ing.json()["observation_ids"][0]
    up = _upload_to_occurrence(e2e_client, occ)
    assert up.status_code == 201, up.text
    image_id = up.json()["id"]

    # Localiza o arquivo real via dir autorizado + file_name (API não expõe path).
    stored = image_store_module.get_image_dir() / up.json()["file_name"]
    assert stored.is_file()
    stored.unlink()  # arquivo removido após o registro

    r = e2e_client.get(f"/api/images/{image_id}/content")
    assert r.status_code == 404
    assert "tmp" not in r.text and "TCC" not in r.text  # sem caminho interno


def test_content_confined_to_image_dir(e2e_client):
    # Registro cujo image_path aponta para FORA de data/images deve ser
    # recusado (404), mesmo que o arquivo exista. Simula DB adulterado.
    from sqlalchemy import select

    from app import image_store as image_store_module
    from app.models import ImageEvidence

    ing = e2e_client.post("/api/observations/ingest", json=_ingest_payload())
    assert ing.status_code == 201, ing.text
    occ = ing.json()["observation_ids"][0]
    up = _upload_to_occurrence(e2e_client, occ)
    assert up.status_code == 201, up.text
    image_id = up.json()["id"]

    outside = Path(tempfile.gettempdir()) / "tcc_evidence_outside.png"
    outside.write_bytes(TEST_PNG)
    try:
        db = e2e_client  # TestClient não expõe sessão; usa override abaixo
        # Atualiza o image_path diretamente via nova sessão no engine do teste:
        # o fixture não expõe a sessão, então reabre via dependency override.
        from app.main import app as _app

        override = _app.dependency_overrides
        assert override, "fixture e2e_client deve registrar dependency_overrides"
        get_db_fn = next(iter(override.values()))
        session = next(get_db_fn())
        try:
            row = session.get(ImageEvidence, image_id)
            assert row is not None
            row.image_path = str(outside)
            session.commit()
        finally:
            session.close()

        r = e2e_client.get(f"/api/images/{image_id}/content")
        assert r.status_code == 404
    finally:
        outside.unlink(missing_ok=True)


def test_metadata_endpoint_still_works(e2e_client):
    ing = e2e_client.post("/api/observations/ingest", json=_ingest_payload())
    assert ing.status_code == 201, ing.text
    occ = ing.json()["observation_ids"][0]
    up = _upload_to_occurrence(e2e_client, occ)
    assert up.status_code == 201, up.text
    image_id = up.json()["id"]

    r = e2e_client.get(f"/api/images/{image_id}")
    assert r.status_code == 200
    assert r.json()["id"] == image_id
    assert r.json()["occurrence_id"] == occ