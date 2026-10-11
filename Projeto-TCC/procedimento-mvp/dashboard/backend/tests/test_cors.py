"""Tests de CORS do backend (middleware).

Valida que o upload de imagem via navegador (POST multipart /api/images) é
autorizado APENAS para as origens configuradas, preservando os métodos GET
já existentes. Roda sem PostgreSQL (usa a app importada; nenhum endpoint de
banco é chamado — apenas preflight/respostas do middleware).

Origem autorizada padrão: http://localhost:5173 (frontend Vite em dev).
"""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)

ALLOWED = "http://localhost:5173"
UNAUTHORIZED = "http://evil.example.com"


def _preflight(origin: str, method: str = "POST", requested_method: str = "POST"):
    return client.options(
        "/api/images",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": requested_method,
            "Access-Control-Request-Headers": "content-type",
        },
    )


def test_preflight_authorized_origin_allows_post():
    r = _preflight(ALLOWED, requested_method="POST")
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == ALLOWED
    allowed_methods = r.headers.get("access-control-allow-methods", "")
    assert "POST" in allowed_methods
    assert "GET" in allowed_methods  # métodos existentes preservados
    # Content-Type (multipart/form-data) permitido para o upload.
    allowed_headers = r.headers.get("access-control-allow-headers", "").lower()
    assert "content-type" in allowed_headers or allowed_headers == "*"


def test_preflight_authorized_origin_allows_get():
    r = _preflight(ALLOWED, requested_method="GET")
    allowed_methods = r.headers.get("access-control-allow-methods", "")
    assert "GET" in allowed_methods


def test_preflight_unauthorized_origin_blocked():
    r = _preflight(UNAUTHORIZED, requested_method="POST")
    # Origem não autorizada: sem access-control-allow-origin -> browser bloqueia.
    assert r.headers.get("access-control-allow-origin") != UNAUTHORIZED


def test_actual_post_from_authorized_origin_includes_cors_headers():
    # Sessão SQLite isolada p/ o POST realmente persistir (201) sem Postgres.
    from sqlalchemy import Integer, create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from fastapi.testclient import TestClient as TC

    import app.main as main_module
    import app.database as database_module
    from app.models import ImageEvidence

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    id_col = ImageEvidence.__table__.c.id
    original_type = id_col.type
    id_col.type = Integer()
    ImageEvidence.__table__.create(bind=engine, checkfirst=True)
    TestingSessionLocal = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )

    def _db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[main_module.get_db] = _db
    try:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            import os as _os

            old_root = _os.environ.get("TCC_MVP_ROOT")
            _os.environ["TCC_MVP_ROOT"] = tmp
            client_no_raise = TC(app, raise_server_exceptions=False)
            r = client_no_raise.post(
                "/api/images",
                headers={"Origin": ALLOWED},
                files={"image": ("x.png", open_png(), "image/png")},
                data={"occurrence_id": "1", "camera_code": "camera_1"},
            )
            if old_root is None:
                _os.environ.pop("TCC_MVP_ROOT", None)
            else:
                _os.environ["TCC_MVP_ROOT"] = old_root
    finally:
        app.dependency_overrides.clear()
        ImageEvidence.__table__.drop(bind=engine, checkfirst=True)
        id_col.type = original_type
        engine.dispose()
    # Upload aceito; o middleware anexa CORS à resposta de sucesso.
    assert r.status_code == 201, r.text
    assert r.headers.get("access-control-allow-origin") == ALLOWED


def open_png():
    # PNG mínimo (assinatura + IHDR + IDAT + IEND) p/ passar na validação.
    return bytes(
        [
            0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
            0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,
            0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
            0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53,
            0x64, 0x00, 0x00, 0x00, 0x0C, 0x49, 0x44, 0x41,
            0x54, 0x78, 0x9C, 0x63, 0x00, 0x01, 0x00, 0x00,
            0x05, 0x00, 0x01, 0x0D, 0x0A, 0x2D, 0xB4, 0x00,
            0x00, 0x00, 0x00, 0x49, 0x45, 0x4E, 0x44, 0xAE,
            0x42, 0x60, 0x82,
        ]
    )


def test_actual_get_from_authorized_origin_includes_cors_headers():
    r = client.get("/health", headers={"Origin": ALLOWED})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == ALLOWED


def test_unauthorized_origin_get_not_exposed():
    r = client.get("/health", headers={"Origin": UNAUTHORIZED})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") != UNAUTHORIZED