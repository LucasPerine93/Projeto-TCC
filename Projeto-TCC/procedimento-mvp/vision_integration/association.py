"""Association Engine: associação geométrica pessoa <-> EPI DENTRO de um frame.

Heurística EXPERIMENTAL (plano v3.4.2): sem tracking, sem identidade entre
frames. Regras determinísticas e testáveis — calibrar com imagens reais do
cenário (podem produzir falso positivo/negativo; não é verdade universal).

Regras:
  - região-helmet da pessoa P: x em [x1,x2], y em [y1-0.35h, y1+0.35h]
  - região-vest da pessoa P:    x em [x1,x2], y em [y1+0.30h, y1+0.85h]
  - candidato: CENTRO da bbox do EPI dentro da região
  - EPI em 2 regiões -> pessoa com menor distância (centro-EPI x centro-região)
  - 2 candidatos com confidence empatada (diferença < TIE_MARGIN) -> indeterminado
  - sem candidato + EPI do tipo sem dono no frame -> indeterminado
  - sem candidato + todos os EPIs do tipo atribuídos (ou nenhum) -> ausente
"""
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from adapter import NormalizedDetection

TIE_MARGIN = 0.05  # margem de empate de confidence (provisória, experimental)

STATUS_ASSOCIADO = "associado"
STATUS_AUSENTE = "ausente"
STATUS_INDETERMINADO = "indeterminado"

# (offset_topo, offset_base) em frações da altura da pessoa (h = y2 - y1)
REGION_RATIOS = {
    "helmet": (-0.35, 0.35),
    "vest": (0.30, 0.85),
}


@dataclass(frozen=True)
class EpiMatch:
    """Resultado da associação de um tipo de EPI para uma pessoa."""
    status: str                              # associado | ausente | indeterminado
    confidence: Optional[float] = None       # confidence do modelo no EPI
    bbox: Optional[Tuple[float, float, float, float]] = None


@dataclass(frozen=True)
class PersonAssociation:
    """Uma pessoa do frame atual + seus EPIs avaliados individualmente."""
    person_ref: int          # índice efêmero DENTRO deste frame (NÃO é identidade)
    bbox: Tuple[float, float, float, float]
    confidence: float
    camera_id: Optional[str]  # injetado pelo Adapter (configuração)
    helmet: EpiMatch
    vest: EpiMatch


def _center(bbox) -> Tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def _region(person_bbox, kind: str) -> Tuple[float, float, float, float]:
    x1, y1, x2, y2 = person_bbox
    h = y2 - y1
    top_off, base_off = REGION_RATIOS[kind]
    return (x1, y1 + top_off * h, x2, y1 + base_off * h)


def _point_in(pt: Tuple[float, float], region) -> bool:
    cx, cy = pt
    x1, y1, x2, y2 = region
    return x1 <= cx <= x2 and y1 <= cy <= y2


def _dist(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _match_kind(
    persons: List[PersonAssociation],
    epis: List[NormalizedDetection],
    kind: str,
) -> Dict[int, EpiMatch]:
    """Avalia um tipo de EPI para cada pessoa (determinístico)."""
    # 1) Cada EPI -> pessoa cuja região contém o centro (empate -> menor distância).
    assignments: Dict[int, List[NormalizedDetection]] = {p.person_ref: [] for p in persons}
    unassigned: List[NormalizedDetection] = []
    for epi in epis:
        c = _center(epi.bbox)
        cands = [p for p in persons if _point_in(c, _region(p.bbox, kind))]
        if not cands:
            unassigned.append(epi)
            continue
        best = min(cands, key=lambda p: _dist(c, _center(_region(p.bbox, kind))))
        assignments[best.person_ref].append(epi)

    # 2) Status por pessoa.
    result: Dict[int, EpiMatch] = {}
    for p in persons:
        cands = sorted(
            assignments[p.person_ref],
            key=lambda d: d.confidence,
            reverse=True,
        )
        if len(cands) >= 2 and (cands[0].confidence - cands[1].confidence) < TIE_MARGIN:
            result[p.person_ref] = EpiMatch(STATUS_INDETERMINADO)
        elif cands:
            result[p.person_ref] = EpiMatch(
                STATUS_ASSOCIADO, cands[0].confidence, cands[0].bbox
            )
        elif unassigned:
            # Existe EPI do tipo no frame sem dono claro -> não determinável.
            result[p.person_ref] = EpiMatch(STATUS_INDETERMINADO)
        else:
            result[p.person_ref] = EpiMatch(STATUS_AUSENTE)
    return result


def associate(detections: List[NormalizedDetection]) -> List[PersonAssociation]:
    """Avalia cada pessoa do frame de forma independente (sem memória entre frames)."""
    persons_det = [d for d in detections if d.label.lower() == "person"]
    helmets = [d for d in detections if d.label.lower() == "helmet"]
    vests = [d for d in detections if d.label.lower() == "vest"]

    persons = [
        PersonAssociation(
            person_ref=ref,
            bbox=d.bbox,
            confidence=d.confidence,
            camera_id=d.camera_id,
            helmet=EpiMatch(STATUS_INDETERMINADO),
            vest=EpiMatch(STATUS_INDETERMINADO),
        )
        # Ordem do payload define o índice: mesma entrada -> mesmos person_ref.
        for ref, d in enumerate(persons_det)
    ]

    helmet_matches = _match_kind(persons, helmets, "helmet")
    vest_matches = _match_kind(persons, vests, "vest")

    return [
        PersonAssociation(
            person_ref=p.person_ref,
            bbox=p.bbox,
            confidence=p.confidence,
            camera_id=p.camera_id,
            helmet=helmet_matches[p.person_ref],
            vest=vest_matches[p.person_ref],
        )
        for p in persons
    ]
