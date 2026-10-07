"""Context: contexto da pessoa em relação à área de risco (UM frame).

Estados:
  inside  -> existe área configurada e o CENTRO da bbox está dentro
  outside -> existe área configurada e o centro está fora
  no_area -> não existe área configurada para esta análise

STATELESS: calculado a cada frame; saída da área é refletida imediatamente
(no frame seguinte a pessoa vira "outside" — sem contadores nem histórico).

Aproximação EXPERIMENTAL: point-in-rectangle aplicado ao centro da bbox
(pessoa grande atravessando a área sem o centro dentro => "fora" falso).
Evolução futura (fora desta etapa): qualquer vértice / % de sobreposição.
"""
from typing import Dict, Optional

CONTEXT_INSIDE = "inside"
CONTEXT_OUTSIDE = "outside"
CONTEXT_NO_AREA = "no_area"


def evaluate(person_bbox, risk_area: Optional[Dict[str, float]]) -> str:
    """Centro da bbox da pessoa -> ponto dentro/fora do retângulo da área."""
    if not risk_area:
        return CONTEXT_NO_AREA
    try:
        ax1 = float(risk_area["x1"])
        ay1 = float(risk_area["y1"])
        ax2 = float(risk_area["x2"])
        ay2 = float(risk_area["y2"])
    except (KeyError, TypeError, ValueError):
        return CONTEXT_NO_AREA

    x1, y1, x2, y2 = person_bbox
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0

    rx1, rx2 = min(ax1, ax2), max(ax1, ax2)
    ry1, ry2 = min(ay1, ay2), max(ay1, ay2)
    if rx1 <= cx <= rx2 and ry1 <= cy <= ry2:
        return CONTEXT_INSIDE
    return CONTEXT_OUTSIDE
