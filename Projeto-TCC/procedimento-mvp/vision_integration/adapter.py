"""Adapter: payload on_detect_all -> detecções normalizadas.

Responsabilidade EXCLUSIVA: traduzir/validar o formato do payload e anexar o
camera_id de configuração. NÃO aplica threshold de confiança (o gate de
confidence é do event_parser.parse_detection — contrato v3.4.2) e NÃO associa
pessoa com EPI.

Entrada (on_detect_all):
    {"person": [{"confidence": float, "bounding_box_xyxy": (x1,y1,x2,y2)}],
     "helmet": [...], "vest": [...]}
"""
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "event_arch"))

from event_parser import parse_detection

BBox = Tuple[float, float, float, float]


@dataclass(frozen=True)
class NormalizedDetection:
    """Uma detecção normalizada (uma bounding box válida do frame)."""
    label: str            # rótulo bruto do modelo ("person"/"helmet"/"vest")
    confidence: float     # confidence ORIGINAL do modelo (preservada)
    bbox: BBox            # (x1, y1, x2, y2) em pixels do frame
    camera_id: Optional[str]  # injetado pela configuração da integração


def adapt(payload: Dict, camera_id: Optional[str] = None) -> List[NormalizedDetection]:
    """Normaliza o dicionário do on_detect_all em detecções válidas.

    Valida apenas ESTRUTURA (chaves e formatos). Payload vazio -> [].
    Entradas malformadas são descartadas silenciosamente.
    A filtragem por confidence acontece no gate() (event_parser).
    """
    if not isinstance(payload, dict):
        return []
    out: List[NormalizedDetection] = []
    for label, items in payload.items():
        if not isinstance(label, str) or not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            conf = item.get("confidence")
            if type(conf) not in (int, float):   # bool excluído
                continue
            bbox = item.get("bounding_box_xyxy")
            if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                continue
            try:
                x1, y1, x2, y2 = (float(v) for v in bbox)
            except (TypeError, ValueError):
                continue
            out.append(NormalizedDetection(
                label=label,
                confidence=float(conf),
                bbox=(x1, y1, x2, y2),
                camera_id=camera_id,
            ))
    return out


def gate(det: NormalizedDetection, threshold: float = 0.5) -> bool:
    """Gate ÚNICO de confiança — delegado ao event_parser.parse_detection.

    Mantém o contrato congelado: o parser é o único responsável pelo
    threshold (0.5 provisório). Este módulo NÃO mantém limiar próprio.
    """
    tipo, _ = parse_detection(
        {
            "label": det.label,
            "confidence": det.confidence,
            "bbox": list(det.bbox),
            "camera_id": det.camera_id,
        },
        threshold=threshold,
    )
    return tipo == "accepted"
