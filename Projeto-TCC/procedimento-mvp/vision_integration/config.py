"""Configuração da camada de integração observacional (valores PROVISÓRIOS).

camera_id: identificação configurada pela camada de integração — a API
on_detect_all NÃO fornece camera_id (não é propriedade detectada pelo modelo).
risk_area: retângulo da área de risco em coordenadas do FRAME
({"x1","y1","x2","y2"}), ou None quando não há área configurada.
O mapeamento canvas->frame do projeto da visão é calibração futura (fora
desta etapa); aqui as coordenadas são assumidas já em pixels do frame.
"""
import os
from typing import Dict, Optional

DEFAULT_CAMERA_ID = "camera_1"
DEFAULT_RISK_AREA: Optional[Dict[str, float]] = None  # no_area por padrão


def _env_int(name: str, default: int) -> int:
    """Lê um inteiro do ambiente; inválido/ausente -> default."""
    raw = os.getenv(name, "").strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value >= 1 else default


# ---------------------------------------------------------------
# Camada temporal de ocorrências (occurrence.py) — PROVISÓRIO.
# Frames CONSECUTIVOS necessários para confirmar/encerrar; valores
# NÃO estatisticamente validados — calibrar com dados do cenário.
# Configuráveis sem alterar código: OCCURRENCE_CONFIRM_FRAMES,
# OCCURRENCE_RESOLVE_FRAMES (>= 1).
# ---------------------------------------------------------------
OCCURRENCE_CONFIRM_FRAMES = _env_int("OCCURRENCE_CONFIRM_FRAMES", 3)
OCCURRENCE_RESOLVE_FRAMES = _env_int("OCCURRENCE_RESOLVE_FRAMES", 2)
