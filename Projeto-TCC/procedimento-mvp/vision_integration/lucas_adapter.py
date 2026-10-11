"""Adaptador Lucas -> MVP (Etapa 1 minima, SEM tocar no detector real).

Transforma o RESULTADO ja calculado pelo detector do Lucas em
ObservationEvent padronizados do MVP. NAO reimplementa geometria,
NAO reavalia associacao, NAO decide contexto.

Entradas (formato que o detector do Lucas JA produz hoje):
  - operarios: lista de objetos/dicts no formato de
    python/detector.py::Operario — box_xyxy, tem_colete (bool),
    tem_capacete (bool), risco_detectado (bool).
    Campos OPCIONAIS (extensao futura, Etapa 2): conf_pessoa,
    conf_capacete/conf_colete, bbox_capacete/bbox_colete.
    Ausentes -> adaptacao explicita (sem inventar dados):
      conf_pessoa ausente -> confidence = 0.5 (piso do gate do parser,
        marcado em metadata como "confidence_source": "fallback");
      bbox/conf do EPI ausente + tem_*=True -> evento com_* com
        conf_epi=None, bbox_epi=None (veredicto do Lucas preservado).
  - camera_id: configuracao da integracao (ex. "camera_1"), nunca do modelo.
  - risk_area: dict {x1,y1,x2,y2} JA em pixels do frame, ou None
    (conversao canvas->frame feita por risk_area_mapper.py, fora daqui).

Regras (veredicto do Lucas preservado 1:1):
  - contexto deriva de risco_detectado + presenca da area:
    com area + risco=True -> inside; com area + risco=False -> outside;
    sem area -> no_area (sem evento, mesmo que risco=True).
  - so "inside" gera eventos (igual ao event_generator do MVP).
  - tem_*=True -> pessoa_com_* (label helmet/vest);
    tem_*=False -> pessoa_sem_* (label person, ausencia observada);
    tem_*=None/"indeterminado" -> NENHUM evento (nunca afirmar o incerto).
  - lista vazia/None -> [] sem erro.

Saida: (events, diagnostics) — events: List[ObservationEvent] no contrato
de observation.py; diagnostics: contadores tecnicos (nao e registro
oficial de conformidade).
"""
from pathlib import Path
import sys
from typing import Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from context import CONTEXT_INSIDE, CONTEXT_NO_AREA, CONTEXT_OUTSIDE
from observation import ObservationEvent

FALLBACK_CONFIDENCE = 0.5  # piso do gate do parser; marcado como fallback

_EVENTOS = {
    ("helmet", True): ("pessoa_com_capacete", "helmet", "capacete", True),
    ("helmet", False): ("pessoa_sem_capacete", "person", "capacete", False),
    ("vest", True): ("pessoa_com_colete", "vest", "colete", True),
    ("vest", False): ("pessoa_sem_colete", "person", "colete", False),
}


def _ler(obj, chave: str, default=None):
    if isinstance(obj, dict):
        return obj.get(chave, default)
    return getattr(obj, chave, default)


def _num4(valor) -> Optional[List[float]]:
    if not isinstance(valor, (list, tuple)) or len(valor) != 4:
        return None
    try:
        nums = [float(v) for v in valor]
    except (TypeError, ValueError):
        return None
    if any(v != v or v in (float("inf"), float("-inf")) for v in nums):
        return None
    x1, y1, x2, y2 = nums
    if not (x2 > x1 and y2 > y1):
        return None
    return nums


def _num01(valor) -> Optional[float]:
    if type(valor) not in (int, float):  # bool excluido de proposito
        return None
    num = float(valor)
    if not 0.0 <= num <= 1.0 or num != num:
        return None
    return num


def _tem(valor) -> Optional[bool]:
    """Normaliza tem_colete/tem_capacete: True/False; None/texto -> None."""
    if valor is None:
        return None
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, str) and valor.strip().lower() in (
        "indeterminado", "indeterminate", "none", "null", "unknown",
    ):
        return None
    if isinstance(valor, dict) and valor.get("indeterminado") is True:
        return None
    return bool(valor)


def _evento(
    tipo: str,
    tem: bool,
    person_ref: int,
    bbox_pessoa: List[float],
    camera_id: Optional[str],
    context: str,
    conf_pessoa: Optional[float],
    conf_epi: Optional[float],
    bbox_epi: Optional[List[float]],
) -> ObservationEvent:
    codigo, label, palavra, associado = _EVENTOS[(tipo, tem)]
    fontes = []
    if conf_pessoa is not None:
        base_pessoa = conf_pessoa
    else:
        base_pessoa = FALLBACK_CONFIDENCE
        fontes.append("fallback:conf_pessoa")
    if associado:
        confidence = min(base_pessoa, conf_epi) if conf_epi is not None else base_pessoa
        if conf_epi is None:
            fontes.append("fallback:conf_epi-ausente")
        verbo = "associado"
    else:
        confidence = base_pessoa  # sem_*: so a pessoa existe (convencao MVP)
        verbo = "nao associado"
    message = (
        f"Pessoa {person_ref}: {palavra} {verbo} dentro da area de risco "
        f"(veredicto do detector)."
    )
    metadata: Dict = {
        "label": label,
        "confidence": confidence,
        "bbox": list(bbox_pessoa),
        "camera_id": camera_id,
        "person_ref": person_ref,
        "context": context,
        "conf_pessoa": conf_pessoa,
        "conf_epi": conf_epi,
        "bbox_epi": list(bbox_epi) if bbox_epi else None,
        "origem_veredicto": "lucas_detector",
    }
    if fontes:
        metadata["confidence_source"] = "+".join(fontes)
    return ObservationEvent(codigo, message, metadata)


def adapt_lucas_operarios(
    operarios,
    camera_id: Optional[str] = None,
    risk_area: Optional[Dict] = None,
) -> Tuple[List[ObservationEvent], Dict[str, int]]:
    """Converte lista de Operario do Lucas em ObservationEvent do MVP."""
    diagnostics = {"pessoas": 0, "dentro": 0, "fora": 0, "indeterminados": 0, "eventos": 0}
    if not operarios:
        return [], diagnostics
    tem_area = isinstance(risk_area, dict) and all(
        k in risk_area for k in ("x1", "y1", "x2", "y2")
    )
    events: List[ObservationEvent] = []
    for ref, op in enumerate(list(operarios)):
        diagnostics["pessoas"] += 1
        bbox = _num4(_ler(op, "box_xyxy"))
        if bbox is None:
            diagnostics["indeterminados"] += 1
            continue  # bbox invalida: sem base geometrica -> sem evento
        risco = bool(_ler(op, "risco_detectado", False))
        if not tem_area:
            context = CONTEXT_NO_AREA
        elif risco:
            context = CONTEXT_INSIDE
        else:
            context = CONTEXT_OUTSIDE
        if context != CONTEXT_INSIDE:
            diagnostics["fora"] += 1
            continue  # fora/sem area: nenhuma regra de EPI se aplica
        diagnostics["dentro"] += 1
        tem_cap = _tem(_ler(op, "tem_capacete"))
        tem_col = _tem(_ler(op, "tem_colete"))
        conf_pessoa = _num01(_ler(op, "conf_pessoa", _ler(op, "confidence")))
        pares = (
            ("helmet", tem_cap, _num01(_ler(op, "conf_capacete")),
             _num4(_ler(op, "bbox_capacete"))),
            ("vest", tem_col, _num01(_ler(op, "conf_colete")),
             _num4(_ler(op, "bbox_colete"))),
        )
        for tipo, tem, conf_epi, bbox_epi in pares:
            if tem is None:
                diagnostics["indeterminados"] += 1
                continue  # indeterminado -> nenhum evento
            events.append(_evento(
                tipo, tem, ref, bbox, camera_id, context,
                conf_pessoa, conf_epi, bbox_epi,
            ))
    diagnostics["eventos"] = len(events)
    return events, diagnostics
