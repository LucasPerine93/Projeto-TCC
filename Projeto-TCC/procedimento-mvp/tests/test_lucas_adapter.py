"""Testes da Etapa 1: lucas_adapter + risk_area_mapper (dados SIMULADOS).

NENHUM teste toca hardware, rede, detector real ou banco (dev/prod/teste).
Usa o formato que python/detector.py do Lucas JA produz (Operario:
box_xyxy, tem_colete, tem_capacete, risco_detectado) montado manualmente.

Casos: pessoa sem EPI, indeterminado, ausencia de pessoa, conversao
canvas->frame da area de risco.
"""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "vision_integration"))

from lucas_adapter import FALLBACK_CONFIDENCE, adapt_lucas_operarios
from risk_area_mapper import (
    DEFAULT_CANVAS_SIZE,
    DEFAULT_FRAME_SIZE,
    map_box_canvas_to_frame,
    map_point_canvas_to_frame,
)

P0 = (100.0, 100.0, 300.0, 400.0)  # centro (200, 250)
AREA_FRAME = {"x1": 0.0, "y1": 0.0, "x2": 800.0, "y2": 600.0}


def op(box=P0, cap=True, col=True, risco=True, **extra):
    base = {"box_xyxy": box, "tem_capacete": cap, "tem_colete": col,
            "risco_detectado": risco}
    base.update(extra)
    return base


# --- 1) pessoa COM EPIs dentro -> 2 eventos com_* ---------------------------
evs, dg = adapt_lucas_operarios([op()], camera_id="camera_1", risk_area=AREA_FRAME)
assert [e.event for e in evs] == ["pessoa_com_capacete", "pessoa_com_colete"], dg
assert all(e.metadata["context"] == "inside" for e in evs)
assert all(e.metadata["origem_veredicto"] == "lucas_detector" for e in evs)
assert evs[0].metadata["label"] == "helmet" and evs[1].metadata["label"] == "vest"
assert evs[0].metadata["confidence"] == FALLBACK_CONFIDENCE  # sem conf -> piso
assert "fallback" in evs[0].metadata["confidence_source"]
print("[TESTE 1] com EPIs dentro: 2 com_*, inside, fallback marcado")

# --- 2) pessoa SEM EPIs dentro -> 2 eventos sem_* ----------------------------
evs, dg = adapt_lucas_operarios(
    [op(cap=False, col=False)], camera_id="camera_1", risk_area=AREA_FRAME)
assert [e.event for e in evs] == ["pessoa_sem_capacete", "pessoa_sem_colete"]
assert all(e.metadata["label"] == "person" for e in evs)  # ausencia via pessoa
assert all(e.metadata["conf_epi"] is None and e.metadata["bbox_epi"] is None
           for e in evs)
print("[TESTE 2] sem EPIs dentro: 2 sem_* (ausencia observada)")

# --- 3) misto: sem capacete + com colete; conf preservada -------------------
evs, dg = adapt_lucas_operarios([op(
    cap=False, col=True, conf_pessoa=0.93, conf_colete=0.88,
    bbox_colete=(150.0, 250.0, 250.0, 350.0))],
    camera_id="camera_1", risk_area=AREA_FRAME)
por = {e.event: e for e in evs}
assert set(por) == {"pessoa_sem_capacete", "pessoa_com_colete"}, por
assert por["pessoa_sem_capacete"].metadata["confidence"] == 0.93
assert por["pessoa_com_colete"].metadata["confidence"] == min(0.93, 0.88)
assert por["pessoa_com_colete"].metadata["bbox_epi"] == [150.0, 250.0, 250.0, 350.0]
print("[TESTE 3] misto: sem_*=conf_pessoa; com_*=min(); bbox_epi preservada")

# --- 4) indeterminado (tem=None) -> NENHUM evento p/ aquele EPI -------------
evs, dg = adapt_lucas_operarios(
    [op(cap=None, col=False)], camera_id="camera_1", risk_area=AREA_FRAME)
assert [e.event for e in evs] == ["pessoa_sem_colete"], evs
assert dg["indeterminados"] == 1 and dg["eventos"] == 1, dg
evs, _ = adapt_lucas_operarios(
    [op(cap="indeterminado", col={"indeterminado": True})],
    camera_id="camera_1", risk_area=AREA_FRAME)
assert evs == [], evs
print("[TESTE 4] indeterminado: nenhum evento (nunca afirmar o incerto)")

# --- 5) ausencia de pessoa -> [] sem erro ------------------------------------
for vazio in ([], None, ()):
    evs, dg = adapt_lucas_operarios(vazio, camera_id="camera_1", risk_area=AREA_FRAME)
    assert evs == [] and dg["eventos"] == 0, (vazio, dg)
print("[TESTE 5] sem pessoa: [] sem erro")

# --- 6) fora da area / sem area -> nenhum evento ----------------------------
evs, dg = adapt_lucas_operarios([op(risco=False)], camera_id="camera_1",
                                risk_area=AREA_FRAME)
assert evs == [] and dg["fora"] == 1, dg
evs, dg = adapt_lucas_operarios([op()], camera_id="camera_1", risk_area=None)
assert evs == [], dg
print("[TESTE 6] outside/no_area: nenhum evento de conformidade")

# --- 7) bbox invalida -> indeterminada, sem evento ---------------------------
evs, dg = adapt_lucas_operarios([op(box=(0, 0, 0, 0))], camera_id="camera_1",
                                risk_area=AREA_FRAME)
assert evs == [] and dg["indeterminados"] == 1, dg
print("[TESTE 7] bbox invalida: sem evento, contada como indeterminada")

# --- 8) canvas->frame: 720x460 -> 720x480 (escala so em Y) -------------------
box_canvas = {"x1": 0, "y1": 0, "x2": 720, "y2": 460}
conv = map_box_canvas_to_frame(box_canvas)
assert conv == {"x1": 0.0, "y1": 0.0, "x2": 720.0, "y2": 480.0}, conv
px, py = map_point_canvas_to_frame(360, 230)
assert abs(px - 360.0) < 1e-9 and abs(py - 240.0) < 1e-9, (px, py)
print("[TESTE 8] canvas 720x460 -> frame 720x480: X mantido, Y x480/460")

# --- 9) cantos invertidos normalizados; invalida rejeitada -------------------
inv = map_box_canvas_to_frame({"x1": 720, "y1": 460, "x2": 0, "y2": 0})
assert inv == conv, inv
for ruim in (None, {}, {"x1": 1}, [1, 2, 3],
             {"x1": "a", "y1": 0, "x2": 1, "y2": 1}):
    try:
        map_box_canvas_to_frame(ruim)
    except ValueError:
        pass
    else:
        raise AssertionError(f"deveria rejeitar: {ruim!r}")
print("[TESTE 9] invertida normalizada; invalida rejeitada sem inventar")

# --- 10) contrato ObservationEvent (event != label, 9 campos) ----------------
evs, _ = adapt_lucas_operarios([op()], camera_id="camera_1", risk_area=AREA_FRAME)
for e in evs:
    assert e.event in {"pessoa_com_capacete", "pessoa_sem_capacete",
                       "pessoa_com_colete", "pessoa_sem_colete"}
    assert e.event != e.metadata["label"]
    assert e.metadata["person_ref"] == 0  # efemero, intra-frame
    for campo in ("label", "confidence", "bbox", "camera_id", "person_ref",
                  "context", "conf_pessoa", "conf_epi", "bbox_epi"):
        assert campo in e.metadata, campo
print("[TESTE 10] contrato: event=regra, label bruto no metadata, 9 campos")

print("[OK] lucas_adapter + risk_area_mapper: todos os testes passaram.")
print(f"     (canvas {DEFAULT_CANVAS_SIZE}, frame {DEFAULT_FRAME_SIZE})")
