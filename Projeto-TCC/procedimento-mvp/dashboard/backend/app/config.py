"""Configuração da aplicação (variáveis de ambiente)."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# Carrega o arquivo .env (se existir) junto ao requirements.txt.
BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

DEFAULT_MODEL_NAME = "ei-model-1127250-2"
DEFAULT_CORS_ORIGINS = "http://localhost:5173"


class Settings:
    """Configurações carregadas do ambiente."""

    database_url: str
    model_name: str
    cors_origins: list[str]

    def __init__(self) -> None:
        url = os.getenv("DATABASE_URL", "").strip()
        if not url:
            raise RuntimeError(
                "DATABASE_URL não definida. Copie .env.example para .env "
                "e preencha a variável DATABASE_URL."
            )
        self.database_url = url
        self.model_name = os.getenv("MODEL_NAME", DEFAULT_MODEL_NAME).strip() or DEFAULT_MODEL_NAME
        # Origens permitidas para o frontend (separadas por vírgula).
        raw = os.getenv("CORS_ORIGINS", DEFAULT_CORS_ORIGINS).strip() or DEFAULT_CORS_ORIGINS
        self.cors_origins = [o.strip() for o in raw.split(",") if o.strip()] or [
            DEFAULT_CORS_ORIGINS
        ]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
