"""Testes do Context: inside / outside / no_area (stateless por frame)."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "vision_integration"))

from context import CONTEXT_INSIDE, CONTEXT_NO_AREA, CONTEXT_OUTSIDE, evaluate

P0 = (100.0, 100.0, 300.0, 400.0)        # centro (200, 250)
FORA = (1000.0, 100.0, 1200.0, 400.0)     # centro (1100, 250)
AREA = {"x1": 0.0, "y1": 0.0, "x2": 800.0, "y2": 600.0}

# --- 1) dentro ---------------------------------------------------------------
assert evaluate(P0, AREA) == CONTEXT_INSIDE
print("[TESTE 1] centro dentro da área -> inside")

# --- 2) fora -----------------------------------------------------------------
assert evaluate(FORA, AREA) == CONTEXT_OUTSIDE
print("[TESTE 2] centro fora da área -> outside")

# --- 3) sem área configurada -------------------------------------------------
assert evaluate(P0, None) == CONTEXT_NO_AREA
assert evaluate(P0, {}) == CONTEXT_NO_AREA
print("[TESTE 3] sem área -> no_area (NÃO é outside)")

# --- 4) outside != no_area ---------------------------------------------------
assert CONTEXT_OUTSIDE != CONTEXT_NO_AREA
print("[TESTE 4] outside e no_area são estados distintos")

# --- 5) saída da área: estado refletido no próximo frame (stateless) ---------
frame1 = evaluate((100.0, 100.0, 300.0, 400.0), AREA)   # dentro
frame2 = evaluate((700.0, 100.0, 900.0, 400.0), AREA)   # saiu (centro 800,250)
# centro 800 está na borda x2=800 -> ainda dentro (borda inclusa)
assert frame2 == CONTEXT_INSIDE
frame3 = evaluate((710.0, 100.0, 910.0, 400.0), AREA)   # centro 810 -> fora
assert frame3 == CONTEXT_OUTSIDE
print("[TESTE 5] saída da área: sem contadores, refletido imediatamente")

# --- 6) retângulo com coordenadas invertidas é normalizado --------------------
INV = {"x1": 800.0, "y1": 600.0, "x2": 0.0, "y2": 0.0}
assert evaluate(P0, INV) == CONTEXT_INSIDE
print("[TESTE 6] área com x1>x2 normalizada (min/max)")

print("[OK] context: todos os testes passaram.")
