"""Testes do Event Generator: conformidade gerada a partir de associação+contexto.

Regras congeladas (v3.4.2): associado->com_*; ausente+inside->sem_*;
indeterminado/fora/sem área -> NENHUM evento.
"""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "vision_integration"))

from association import (
    STATUS_ASSOCIADO,
    STATUS_AUSENTE,
    STATUS_INDETERMINADO,
    EpiMatch,
    PersonAssociation,
)
from event_generator import generate

P0 = (100.0, 100.0, 300.0, 400.0)


def pessoa(ref=0, conf=0.93, helmet=None, vest=None, cam="camera_1"):
    return PersonAssociation(
        person_ref=ref,
        bbox=P0,
        confidence=conf,
        camera_id=cam,
        helmet=helmet or EpiMatch(STATUS_AUSENTE),
        vest=vest or EpiMatch(STATUS_AUSENTE),
    )


OK_HELMET = EpiMatch(STATUS_ASSOCIADO, 0.88, (150.0, 50.0, 250.0, 120.0))
OK_VEST = EpiMatch(STATUS_ASSOCIADO, 0.91, (150.0, 250.0, 250.0, 350.0))
INDET = EpiMatch(STATUS_INDETERMINADO)
INSIDE = {0: "inside"}

# --- 1) associado -> com_* (confidence = min) --------------------------------
# pessoa() tem vest=AUSENTE por padrão -> 2 eventos: com_capacete + sem_colete
events = generate([pessoa(helmet=OK_HELMET)], INSIDE)
assert len(events) == 2
assert events[0].event == "pessoa_com_capacete"
assert events[1].event == "pessoa_sem_colete"
assert events[0].metadata["confidence"] == min(0.93, 0.88) == 0.88
assert events[0].metadata["label"] == "helmet"        # detecção bruta subjacente
assert events[0].metadata["conf_pessoa"] == 0.93
assert events[0].metadata["conf_epi"] == 0.88
assert events[0].metadata["bbox_epi"] == [150.0, 50.0, 250.0, 120.0]
print("[TESTE 1] helmet associado -> pessoa_com_capacete (min conf)")

# --- 2) ausente+inside -> sem_* (confidence = pessoa) ------------------------
# pessoa() com vest associado -> helmet ausente: sem_capacete + com_colete
events = generate([pessoa(vest=OK_VEST)], INSIDE)
assert len(events) == 2
assert events[0].event == "pessoa_sem_capacete"
assert events[0].metadata["confidence"] == 0.93       # só a pessoa existe
assert events[0].metadata["label"] == "person"
assert events[0].metadata["conf_epi"] is None
print("[TESTE 2] helmet ausente dentro da área -> pessoa_sem_capacete")

# --- 3) vest: com_* e sem_* --------------------------------------------------
events = generate([pessoa(vest=OK_VEST)], INSIDE)
assert events[1].event == "pessoa_com_colete"
assert events[1].metadata["confidence"] == min(0.93, 0.91)
events = generate([pessoa()], INSIDE)   # ambos ausentes
assert [e.event for e in events] == ["pessoa_sem_capacete", "pessoa_sem_colete"]
print("[TESTE 3] vest: com_colete / sem_colete")

# --- 4) ambos associados -> 2 eventos ---------------------------------------
events = generate([pessoa(helmet=OK_HELMET, vest=OK_VEST)], INSIDE)
assert sorted(e.event for e in events) == [
    "pessoa_com_capacete", "pessoa_com_colete",
]
print("[TESTE 4] helmet+vest: 2 eventos com_*")

# --- 5) indeterminado -> NENHUM evento --------------------------------------
# helmet indeterminado NÃO gera nem com_* nem sem_*; vest ausente gera sem_*.
events = generate([pessoa(helmet=INDET)], INSIDE)
assert [e.event for e in events] == ["pessoa_sem_colete"]
# ambos indeterminados -> nenhum evento
events = generate([pessoa(helmet=INDET, vest=INDET)], INSIDE)
assert events == []
print("[TESTE 5] indeterminado: nenhum com_*/sem_* (sem conclusão falsa)")

# --- 6) fora da área -> nenhum evento ---------------------------------------
events = generate([pessoa(helmet=OK_HELMET)], {0: "outside"})
assert events == []
events = generate([pessoa()], {0: "outside"})
assert events == []
print("[TESTE 6] outside: nenhuma conformidade")

# --- 7) sem área -> nenhum evento -------------------------------------------
events = generate([pessoa(helmet=OK_HELMET)], {0: "no_area"})
assert events == []
print("[TESTE 7] no_area: nenhuma conformidade")

# --- 8) EPI sem pessoa -> lista vazia de associações -> nenhum evento --------
events = generate([], {})
assert events == []
print("[TESTE 8] EPI sem pessoa: nenhum evento de conformidade")

# --- 9) metadata completo e categorias separadas ----------------------------
e = generate([pessoa(helmet=OK_HELMET)], INSIDE)[0].metadata
assert set(e) == {
    "label", "confidence", "bbox", "camera_id",
    "person_ref", "context", "conf_pessoa", "conf_epi", "bbox_epi",
}
assert e["camera_id"] == "camera_1"   # integração, não modelo
assert e["person_ref"] == 0           # derivado, efêmero
assert e["context"] == "inside"
print("[TESTE 9] metadata: modelo | integração | derivados, completos")

# --- 10) duas pessoas: conformidades independentes ---------------------------
from association import PersonAssociation as PA
p0 = pessoa(ref=0, helmet=OK_HELMET)
p1 = PA(person_ref=1, bbox=(500.0, 100.0, 700.0, 400.0), confidence=0.91,
        camera_id="camera_1", helmet=EpiMatch(STATUS_AUSENTE),
        vest=OK_VEST)
events = generate([p0, p1], {0: "inside", 1: "inside"})
assert len(events) == 4
assert [e.metadata["person_ref"] for e in events] == [0, 0, 1, 1]
assert events[0].event == "pessoa_com_capacete" and events[1].event == "pessoa_sem_colete"
assert events[2].event == "pessoa_sem_capacete" and events[3].event == "pessoa_com_colete"
print("[TESTE 10] 2 pessoas: 4 eventos independentes, sem cruzamento")

print("[OK] event_generator: todos os testes passaram.")
