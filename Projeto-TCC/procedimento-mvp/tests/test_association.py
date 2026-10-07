"""Testes da Association Engine: geometria intra-frame, sem tracking.

Heurística experimental — payloads falsos com bboxes fixas.
"""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "vision_integration"))

from adapter import adapt
from association import (
    STATUS_ASSOCIADO,
    STATUS_AUSENTE,
    STATUS_INDETERMINADO,
    associate,
)

# Pessoas: P0 (100,100,300,400) h=300 | P1 (500,100,700,400)
# Regiões helmet de P0: x[100,300] y[-5,205]   (y1-0.35h .. y1+0.35h)
# Regiões vest de P0:   x[100,300] y[190,355]  (y1+0.30h .. y1+0.85h)
P0 = (100.0, 100.0, 300.0, 400.0)
P1 = (500.0, 100.0, 700.0, 400.0)
HELMET_P0 = (150.0, 50.0, 250.0, 120.0)    # centro (200,85)  na região helmet de P0
HELMET_P1 = (550.0, 50.0, 650.0, 120.0)    # centro (600,85)  na região helmet de P1
VEST_P0 = (150.0, 250.0, 250.0, 350.0)     # centro (200,300) na região vest de P0
VEST_P1 = (550.0, 250.0, 650.0, 350.0)     # centro (600,300) na região vest de P1
HELMET_FORA = (900.0, 50.0, 1000.0, 120.0) # centro fora de toda região


def run(payload):
    return associate(adapt(payload, camera_id="camera_1"))


# --- 1) Uma pessoa + um EPI --------------------------------------------------
r = run({"person": [{"confidence": 0.93, "bounding_box_xyxy": P0}],
         "helmet": [{"confidence": 0.90, "bounding_box_xyxy": HELMET_P0}]})
assert len(r) == 1 and r[0].person_ref == 0
assert r[0].helmet.status == STATUS_ASSOCIADO
assert r[0].helmet.confidence == 0.90
assert r[0].helmet.bbox == HELMET_P0
assert r[0].vest.status == STATUS_AUSENTE
print("[TESTE 1] 1 pessoa + helmet: associado; vest: ausente")

# --- 2) Uma pessoa + colete --------------------------------------------------
r = run({"person": [{"confidence": 0.93, "bounding_box_xyxy": P0}],
         "vest": [{"confidence": 0.88, "bounding_box_xyxy": VEST_P0}]})
assert r[0].vest.status == STATUS_ASSOCIADO and r[0].helmet.status == STATUS_AUSENTE
print("[TESTE 2] 1 pessoa + vest: colete associado, capacete ausente")

# --- 3) Duas pessoas com EPIs diferentes (cada um no dono geométrico) --------
r = run({
    "person": [
        {"confidence": 0.93, "bounding_box_xyxy": P0},
        {"confidence": 0.91, "bounding_box_xyxy": P1},
    ],
    "helmet": [{"confidence": 0.90, "bounding_box_xyxy": HELMET_P0}],
    "vest": [{"confidence": 0.88, "bounding_box_xyxy": VEST_P1}],
})
assert len(r) == 2
assert r[0].helmet.status == STATUS_ASSOCIADO
assert r[0].vest.status == STATUS_AUSENTE
assert r[1].vest.status == STATUS_ASSOCIADO
assert r[1].helmet.status == STATUS_AUSENTE
print("[TESTE 3] 2 pessoas, EPIs diferentes: sem cruzamento")

# --- 4) EPIs "trocados" (cada EPI associa à pessoa da sua região) -----------
r = run({
    "person": [
        {"confidence": 0.93, "bounding_box_xyxy": P0},
        {"confidence": 0.91, "bounding_box_xyxy": P1},
    ],
    "helmet": [{"confidence": 0.90, "bounding_box_xyxy": HELMET_P1}],
    "vest": [{"confidence": 0.88, "bounding_box_xyxy": VEST_P0}],
})
assert r[0].helmet.status == STATUS_AUSENTE and r[0].vest.status == STATUS_ASSOCIADO
assert r[1].helmet.status == STATUS_ASSOCIADO and r[1].vest.status == STATUS_AUSENTE
print("[TESTE 4] EPIs trocados: associação segue a geometria")

# --- 5) Pessoa sem EPI nenhum ------------------------------------------------
r = run({"person": [{"confidence": 0.93, "bounding_box_xyxy": P0}]})
assert r[0].helmet.status == STATUS_AUSENTE and r[0].vest.status == STATUS_AUSENTE
print("[TESTE 5] pessoa sem EPI: ambos ausentes (nunca indeterminado)")

# --- 6) EPI sem pessoa associável -> indeterminado --------------------------
r = run({
    "person": [{"confidence": 0.93, "bounding_box_xyxy": P0}],
    "helmet": [{"confidence": 0.90, "bounding_box_xyxy": HELMET_FORA}],
})
assert r[0].helmet.status == STATUS_INDETERMINADO
print("[TESTE 6] EPI fora de toda região: indeterminado (não 'ausente')")

# --- 7) Ambiguidade: 2 helmets na mesma região empatados --------------------
r = run({
    "person": [{"confidence": 0.93, "bounding_box_xyxy": P0}],
    "helmet": [
        {"confidence": 0.90, "bounding_box_xyxy": HELMET_P0},
        {"confidence": 0.92, "bounding_box_xyxy": (160.0, 60.0, 240.0, 110.0)},
    ],
})
assert r[0].helmet.status == STATUS_INDETERMINADO  # diff 0.02 < margem 0.05
print("[TESTE 7] empate de confidence: indeterminado")

# --- 8) 2 candidatos sem empate -> maior confidence vence -------------------
r = run({
    "person": [{"confidence": 0.93, "bounding_box_xyxy": P0}],
    "helmet": [
        {"confidence": 0.60, "bounding_box_xyxy": HELMET_P0},
        {"confidence": 0.95, "bounding_box_xyxy": (160.0, 60.0, 240.0, 110.0)},
    ],
})
assert r[0].helmet.status == STATUS_ASSOCIADO and r[0].helmet.confidence == 0.95
print("[TESTE 8] sem empate: maior confidence associado")

# --- 9) Só EPIs, sem pessoa -> nenhuma associação ---------------------------
r = run({"helmet": [{"confidence": 0.9, "bounding_box_xyxy": HELMET_P0}]})
assert r == []
print("[TESTE 9] EPI sem pessoa: nenhuma associação gerada")

# --- 10) Determinismo: mesmo payload -> mesmos person_ref -------------------
payload = {
    "person": [
        {"confidence": 0.93, "bounding_box_xyxy": P0},
        {"confidence": 0.91, "bounding_box_xyxy": P1},
    ],
}
a1 = run(payload)
a2 = run(payload)
assert [p.person_ref for p in a1] == [p.person_ref for p in a2] == [0, 1]
# person_ref NÃO é identidade entre frames: é só a ordem do payload atual.
print("[TESTE 10] determinismo intra-frame: mesma entrada -> mesmos person_ref")

# --- 11) camera_id vem do Adapter, não do payload ---------------------------
assert r == []  # payload sem EPIs acima; usa o payload do teste 10
a = run(payload)
assert all(p.camera_id == "camera_1" for p in a)
assert "camera_id" not in str(payload)  # o payload de entrada não o contém
print("[TESTE 11] camera_id injetado pela integração (não pelo modelo)")

print("[OK] association: todos os testes passaram.")
