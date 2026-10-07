"""Teste END-TO-END: detector real do Lucas -> on_detect_all -> process_frame.

Valida o caminho completo SEM hardware/câmera:
  - importa o python/detector.py REAL do projeto do Lucas (biblioteca arduino
    substituída por stubs determinísticos: sem câmera, sem modelo);
  - confirma que on_detect_all foi registrado no VideoObjectDetection;
  - dispara o callback com um payload consolidado real (formato da API);
  - verifica registros em data/procedure_events.jsonl (status=observation);
  - confirma que NENHUMA chamada chega à State Machine / ingest / vision_bridge.

Ambientação: cada teste roda em processo próprio (python tests/<nome>.py).
"""
from pathlib import Path
import contextlib
import io
import json
import os
import sys
import tempfile
import types

HERE = Path(__file__).resolve().parent
RAIZ_MVP = HERE.parent
TCC_ROOT = RAIZ_MVP.parent

sys.path.insert(0, str(RAIZ_MVP))
sys.path.insert(0, str(RAIZ_MVP / "event_arch"))

# --- 1) Localizar o detector.py real do projeto do Lucas (portável) ----------
env_lucas = os.environ.get("TCC_LUCAS_ROOT")
if env_lucas:
    DIR_PYTHON_LUCAS = Path(env_lucas)
else:
    candidatos = sorted(
        p for p in TCC_ROOT.glob("**/python/detector.py")
        if RAIZ_MVP not in p.parents  # ignora o próprio projeto Victor
    )
    assert candidatos, (
        "detector.py do projeto do Lucas não encontrado. "
        "Defina TCC_LUCAS_ROOT apontando para a pasta python/ dele."
    )
    DIR_PYTHON_LUCAS = candidatos[0].parent
print(f"[E2E] detector do Lucas: {DIR_PYTHON_LUCAS / 'detector.py'}")

# --- 2) Stubs da biblioteca arduino (sem câmera, sem modelo, sem WebUI real) --
class _StubCamera:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

class _StubVideoObjectDetection:
    """Espelha só a superfície usada pelo detector: on_detect + on_detect_all."""
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.handlers = {}
        self.callback_all = None
        _STUBS["deteccao"] = self

    def on_detect(self, label, callback):
        self.handlers[label] = callback

    def on_detect_all(self, callback):
        self.callback_all = callback

class _StubWebUI:
    def on_message(self, *args, **kwargs):
        pass
    def send_message(self, *args, **kwargs):
        pass

_STUBS = {}

def _instalar_stubs():
    nomes = {
        "arduino": None,
        "arduino.app_bricks": None,
        "arduino.app_bricks.video_objectdetection": _StubVideoObjectDetection,
        "arduino.app_peripherals": None,
        "arduino.app_peripherals.camera": _StubCamera,
        "arduino.app_bricks.web_ui": _StubWebUI,
    }
    for nome, cls in nomes.items():
        mod = types.ModuleType(nome)
        if cls is not None:
            attr = nome.rsplit(".", 1)[1]
            # nome da classe esperado pelo import: Camera / VideoObjectDetection / WebUI
            nome_classe = {"video_objectdetection": "VideoObjectDetection",
                           "camera": "Camera", "web_ui": "WebUI"}[attr]
            setattr(mod, nome_classe, cls)
        sys.modules[nome] = mod
    # atributos de submódulo (from a.b import c)
    sys.modules["arduino"].app_bricks = sys.modules["arduino.app_bricks"]
    sys.modules["arduino"].app_peripherals = sys.modules["arduino.app_peripherals"]
    sys.modules["arduino.app_bricks"].video_objectdetection = sys.modules[
        "arduino.app_bricks.video_objectdetection"]
    sys.modules["arduino.app_bricks"].web_ui = sys.modules["arduino.app_bricks.web_ui"]
    sys.modules["arduino.app_peripherals"].camera = sys.modules["arduino.app_peripherals.camera"]

_instalar_stubs()

# --- 3) Importar o detector REAL (captura a saída do registro) ---------------
sys.path.insert(0, str(DIR_PYTHON_LUCAS))
saida_import = io.StringIO()
with contextlib.redirect_stdout(saida_import):
    import detector          # executa o detector.py real do Lucas
    import servidor          # módulo real (servidor.py) com WebUI stub

texto_import = saida_import.getvalue()
assert "[VISION] on_detect_all registrado -> vision_integration.process_frame" in texto_import, (
    f"registro do on_detect_all não confirmado. saída:\n{texto_import}"
)
print("[E2E] detector importado; on_detect_all registrado no VideoObjectDetection")

# --- 4) Pontes reais criadas pelo detector -----------------------------------
assert detector.RAIZ_MVP is not None
assert detector.log_observacional.path == RAIZ_MVP / "data" / "procedure_events.jsonl"
assert detector.debounce_observacional is not None
deteccao_stub = _STUBS["deteccao"]
assert deteccao_stub.callback_all is not None
# on_detect legados preservados (não removidos nesta etapa)
assert set(deteccao_stub.handlers) == {"person", "helmet", "vest"}
print("[E2E] log -> data/procedure_events.jsonl | debounce observacional ativo")
print("[E2E] callbacks on_detect legados (person/helmet/vest) preservados")

texto_import = saida_import.getvalue()

# --- 5) Spies: o fluxo observacional NÃO pode tocar SM/ingest/bridge ---------
import state_machine
import event_ingest
import vision_bridge

_chamadas = {"sm": 0, "ingest": 0, "bridge": 0}
_orig_sm = state_machine.ProcedureStateMachine.process_event
_orig_ingest = event_ingest.ingerir_evento
_orig_bridge = vision_bridge.process_detection

def _sm_espia(self, event):
    _chamadas["sm"] += 1
    return _orig_sm(self, event)

def _ingest_espia(*a, **k):
    _chamadas["ingest"] += 1
    return _orig_ingest(*a, **k)

def _bridge_espia(*a, **k):
    _chamadas["bridge"] += 1
    return _orig_bridge(*a, **k)

state_machine.ProcedureStateMachine.process_event = _sm_espia
event_ingest.ingerir_evento = _ingest_espia
vision_bridge.process_detection = _bridge_espia

# --- 6) Adaptador da área de risco (servidor.py -> context.py) ---------------
servidor.risco = 0
servidor.centro = None
servidor.width = None
servidor.height = None
assert detector._risk_area_atual() is None
print("[E2E] risk_area sem marcação -> None (no_area)")

# Área desenhada no canvas (formato do servidor: centro + dimensões negativas)
servidor.centro = (400.0, 300.0)   # ((x1+x2)/2, (y1+y2)/2)
servidor.width = -600.0            # x1 - x2 (negativo)
servidor.height = -400.0           # y1 - y2 (negativo)
servidor.risco = 1
area = detector._risk_area_atual()
assert area == {"x1": 100.0, "y1": 100.0, "x2": 700.0, "y2": 500.0}, area
print(f"[E2E] risk_area convertida: {area}")

# --- 7) Payload real do on_detect_all (formato da API) -----------------------
P0 = (150.0, 150.0, 350.0, 450.0)     # centro (250,300) -> dentro da área
P1 = (450.0, 150.0, 650.0, 450.0)     # centro (550,300) -> dentro da área
HELMET_P0 = (190.0, 100.0, 310.0, 170.0)   # centro (250,135) -> região helmet P0
VEST_P1 = (490.0, 250.0, 610.0, 400.0)     # centro (550,325) -> região vest P1

PAYLOAD = {
    "person": [
        {"confidence": 0.93, "bounding_box_xyxy": P0},
        {"confidence": 0.91, "bounding_box_xyxy": P1},
    ],
    "helmet": [{"confidence": 0.90, "bounding_box_xyxy": HELMET_P0}],
    "vest": [{"confidence": 0.88, "bounding_box_xyxy": VEST_P1}],
}

JSONL = RAIZ_MVP / "data" / "procedure_events.jsonl"
offset = JSONL.stat().st_size if JSONL.exists() else 0


def ler_novos():
    if not JSONL.exists():
        return []
    texto = JSONL.read_bytes()[offset:].decode("utf-8")
    return [json.loads(l) for l in texto.splitlines() if l.strip()]


# --- 8) Dispara o callback REAL registrado no detector -----------------------
saida = io.StringIO()
with contextlib.redirect_stdout(saida):
    deteccao_stub.callback_all(PAYLOAD, frame=None)
texto = saida.getvalue()
assert "[VISION] on_detect_all recebido" in texto, texto
n1 = len(ler_novos())
assert n1 == 4, f"esperados 4 registros, veio {n1}"
print("[E2E] callback disparado -> [VISION] on_detect_all recebido -> 4 registros JSONL")

registros = ler_novos()
nomes = [r["event"] for r in registros]
assert nomes == [
    "pessoa_com_capacete", "pessoa_sem_colete",
    "pessoa_sem_capacete", "pessoa_com_colete",
], nomes
for r in registros:
    assert r["status"] == "observation"
    assert r["source"] == "visao_computacional"
    assert r["previous_step"] == 0 and r["current_step"] == 0
    assert r["metadata"]["camera_id"] == "camera_1"   # configuração, não o modelo
    assert r["metadata"]["context"] == "inside"
    assert "timestamp" in r
    # event != label: event é sempre a regra derivada, nunca a detecção bruta
    assert r["event"] in {
        "pessoa_com_capacete", "pessoa_sem_capacete",
        "pessoa_com_colete", "pessoa_sem_colete",
    }
assert [r["metadata"]["person_ref"] for r in registros] == [0, 0, 1, 1]
print("[E2E] JSONL: status/source/steps/metadata/event corretos (event != label)")

# confidence congelada
por_evento = {r["event"]: r["metadata"]["confidence"] for r in registros}
assert por_evento["pessoa_com_capacete"] == min(0.93, 0.90)
assert por_evento["pessoa_com_colete"] == min(0.91, 0.88)
assert por_evento["pessoa_sem_capacete"] == 0.91
assert por_evento["pessoa_sem_colete"] == 0.93
print("[E2E] confidence: min() em com_*; conf_pessoa em sem_*")

# --- 9) Debounce observacional no callback real ------------------------------
saida2 = io.StringIO()
with contextlib.redirect_stdout(saida2):
    deteccao_stub.callback_all(PAYLOAD, frame=None)
assert "conformidades=0" in saida2.getvalue(), saida2.getvalue()
assert len(ler_novos()) == 4, "debounce não pode gerar registros extras"
print("[E2E] 2º disparo imediato: debounced (sem registros novos)")

# --- 10) Sem área -> nenhuma conformidade; frame ignorado sem erro -----------
servidor.risco = 0
tam_prev = JSONL.stat().st_size
saida3 = io.StringIO()
with contextlib.redirect_stdout(saida3):
    deteccao_stub.callback_all(PAYLOAD, frame=b"\xff\xd8fakejpeg")
assert "conformidades=0" in saida3.getvalue()
assert JSONL.stat().st_size == tam_prev, "no_area não pode escrever no log"
print("[E2E] risco=0 (no_area): nenhum evento; frame ignorado sem erro")

# --- 11) Payload malformado não derruba o callback ---------------------------
saida4 = io.StringIO()
with contextlib.redirect_stdout(saida4):
    deteccao_stub.callback_all(None, frame=None)
    deteccao_stub.callback_all({}, frame=None)
assert "[VISION] on_detect_all recebido" in saida4.getvalue()
print("[E2E] payload None/vazio: callback estável, sem exceção")

# --- 12) ISOLAMENTO: 0 chamadas à State Machine / ingest / bridge ------------
assert _chamadas["sm"] == 0, f"process_event chamado {_chamadas['sm']}x"
assert _chamadas["ingest"] == 0, f"ingerir_evento chamado {_chamadas['ingest']}x"
assert _chamadas["bridge"] == 0, f"process_detection chamado {_chamadas['bridge']}x"
print("[E2E] ISOLAMENTO: SM=0, ingest=0, vision_bridge=0")

state_machine.ProcedureStateMachine.process_event = _orig_sm
event_ingest.ingerir_evento = _orig_ingest
vision_bridge.process_detection = _orig_bridge

print("[OK] end-to-end: detector -> on_detect_all -> process_frame -> EventLog.")

