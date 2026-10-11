"""Configuração de testes do backend do dashboard.

NÃO sobrescreve um DATABASE_URL já definido no ambiente: quando houver
PostgreSQL de teste configurado (ex.: variável de ambiente do CI), os testes
de integração (test_ingest.py, test_api.py) rodam contra ele. Quando ausente,
aponta para um SQLite em memória apenas para permitir a importação dos módulos
`app.*` e a execução dos testes que não tocam o banco (ex.: image_store e os
endpoints que usam `dependency_overrides`).
"""

import os

os.environ.setdefault(
    "DATABASE_URL",
    "sqlite+pysqlite://",  # banco em memória; evita depender de PostgreSQL
)
