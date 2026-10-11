"""Conexão com o PostgreSQL usando SQLAlchemy 2.x + psycopg 3.

ATENÇÃO: não usamos Base.metadata.create_all(). O schema é criado
manualmente por database/schema.sql e consumido como está.
"""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """Base declarativa apenas para mapeamento (sem create_all)."""


engine: Engine = create_engine(
    get_settings().database_url,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    """Dependência FastAPI: fornece uma sessão e fecha ao final."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_database_connection() -> str:
    """Executa uma consulta simples. Retorna o nome do banco ou lança erro."""
    with engine.connect() as conn:
        return conn.execute(text("SELECT current_database()")).scalar_one()
