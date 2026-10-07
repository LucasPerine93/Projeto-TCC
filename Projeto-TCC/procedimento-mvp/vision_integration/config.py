"""Configuração da camada de integração observacional (valores PROVISÓRIOS).

camera_id: identificação configurada pela camada de integração — a API
on_detect_all NÃO fornece camera_id (não é propriedade detectada pelo modelo).
risk_area: retângulo da área de risco em coordenadas do FRAME
({"x1","y1","x2","y2"}), ou None quando não há área configurada.
O mapeamento canvas->frame do projeto da visão é calibração futura (fora
desta etapa); aqui as coordenadas são assumidas já em pixels do frame.
"""
from typing import Dict, Optional

DEFAULT_CAMERA_ID = "camera_1"
DEFAULT_RISK_AREA: Optional[Dict[str, float]] = None  # no_area por padrão
