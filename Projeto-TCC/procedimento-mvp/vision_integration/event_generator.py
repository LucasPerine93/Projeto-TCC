"""Event Generator: associação + contexto -> eventos de conformidade.

Transformação fina (sem associação, sem debounce, sem log, sem câmera, sem
State Machine). Regras (v3.4.2):

  - só o contexto "inside" gera conformidade (outside/no_area -> nenhum)
  - associado  -> pessoa_com_*  (confidence = min(conf_pessoa, conf_epi))
  - ausente    -> pessoa_sem_*  (confidence = conf_pessoa)
  - indeterminado -> NENHUM evento (nunca afirmar conformidade incerta)
  - "não encontrei EPI" != "está sem EPI": sem_* só vem de ausente.

Confidence é CONVENÇÃO de representação — NÃO é probabilidade de conformidade.
"""
from pathlib import Path
import sys
from typing import Dict, List

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from association import (
    STATUS_ASSOCIADO,
    STATUS_AUSENTE,
    PersonAssociation,
)
from context import CONTEXT_INSIDE
from observation import ObservationEvent

# (attr, evento_com, evento_sem, label do metadata quando associado)
_RULES = (
    ("helmet", "pessoa_com_capacete", "pessoa_sem_capacete", "helmet"),
    ("vest", "pessoa_com_colete", "pessoa_sem_colete", "vest"),
)


def generate(
    associations: List[PersonAssociation],
    contexts: Dict[int, str],
) -> List[ObservationEvent]:
    """Gera eventos de conformidade para pessoas dentro da área, por frame."""
    events: List[ObservationEvent] = []
    for assoc in associations:
        context = contexts.get(assoc.person_ref, "no_area")
        if context != CONTEXT_INSIDE:
            continue  # fora/sem área: nenhuma regra de EPI se aplica

        for attr, ev_com, ev_sem, epi_label in _RULES:
            match = getattr(assoc, attr)
            if match.status == STATUS_ASSOCIADO:
                event = ev_com
                confidence = min(assoc.confidence, match.confidence)
                label = epi_label              # detecção bruta subjacente
                conf_epi = match.confidence
                bbox_epi = match.bbox
                word = "capacete" if attr == "helmet" else "colete"
                message = (
                    f"Pessoa {assoc.person_ref}: {word} associado "
                    f"dentro da área de risco."
                )
            elif match.status == STATUS_AUSENTE:
                event = ev_sem
                confidence = assoc.confidence  # sem_*: só a pessoa existe
                label = "person"               # inferência a partir da pessoa
                conf_epi = None
                bbox_epi = None
                word = "capacete" if attr == "helmet" else "colete"
                message = (
                    f"Pessoa {assoc.person_ref}: {word} não associado "
                    f"dentro da área de risco."
                )
            else:
                continue  # indeterminado -> nenhum evento (sem conclusão falsa)

            events.append(ObservationEvent(
                event=event,
                message=message,
                metadata={
                    # --- dados do modelo (detecção bruta) ---
                    "label": label,
                    "confidence": confidence,     # convenção (min / pessoa)
                    "bbox": list(assoc.bbox),     # bbox da PESSOA
                    # --- dados de integração ---
                    "camera_id": assoc.camera_id, # configuração, não do modelo
                    # --- dados derivados da interpretação ---
                    "person_ref": assoc.person_ref,  # efêmero, intra-frame
                    "context": context,
                    "conf_pessoa": assoc.confidence,
                    "conf_epi": conf_epi,
                    "bbox_epi": list(bbox_epi) if bbox_epi else None,
                },
            ))
    return events
