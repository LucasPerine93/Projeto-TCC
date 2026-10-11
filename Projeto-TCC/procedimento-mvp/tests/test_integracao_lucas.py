"""Testes da Etapa 2: detector REAL do Lucas -> integracao_lucas -> MVP.

Tudo com dados SIMULADOS/stubs: nenhum hardware, rede real ou banco
(dev/prod/teste). O detector.py REAL e importado com stubs da lib
`arduino` (sem camera/modelo). A ponte HTTP usa send_fn injetado.
Casos 1-12 da Etapa 2, secao 6.
"""
from pathlib import Path
import inspect
import sys
import tempfile
import types

HERE = Path(__file__).resolve().parent
RAIZ_MVP = HERE.parent
sys.path.insert(0, str(RAIZ_MVP / "vision_integration"))
sys.path.insert(0, str(RAIZ_MVP / "event_arch"))

import integracao_lucas as hook
from event_debounce import EventDebounce
from event_log import EventLog
from detector_bridge import DetectorIngestBridge

P0 = (100.0, 100.0, 300.0, 400.0)
HELM = (150.0, 50.0, 250.0, 120.0)
VEST = (150.0, 250.0, 250.0, 350.0)
AREA = {"x1": 0.0, "y1": 0.0, "x2": 800.0, "y2": 600.0}

PASSOS = []


def _ok(nome):
    PASSOS.append(nome)
    print(f"[{nome}] OK")


def _log_tmp():
    tmp = tempfile.TemporaryDirectory()
    return tmp, EventLog(Path(tmp.name) / "e2.jsonl")


# --- importar detector REAL do Lucas com stubs -------------------------------
def _carregar_detector_real():
    todos = sorted((RAIZ_MVP.parent).glob("**/python/detector.py"))
    todos = [p for p in todos if RAIZ_MVP not in p.parents]
    assert todos, "detector.py do Lucas nao encontrado"
    # Preferir a copia mais recente (main(4)); ignorar snapshots antigos.
    def _chave(p):
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0
    alvos = sorted(todos, key=_chave)
    pasta = alvos[-1].parent
    if str(pasta) not in sys.path:
        sys.path.insert(0, str(pasta))

    class _Cam:
        def __init__(self, **kw):
            pass

    class _Det:
        def __init__(self, **kw):
            self.cb = None
            self.por_classe = {}
        def on_detect(self, label, cb):
            self.por_classe[label] = cb
        def on_detect_all(self, cb):
            self.cb = cb

    class _UI:
        def on_message(self, *a, **k):
            pass
        def send_message(self, *a, **k):
            pass

    for nome, cls in {
        "arduino": None, "arduino.app_bricks": None,
        "arduino.app_bricks.video_objectdetection": _Det,
        "arduino.app_peripherals": None,
        "arduino.app_peripherals.camera": _Cam,
        "arduino.app_bricks.web_ui": _UI,
    }.items():
        mod = types.ModuleType(nome)
        if cls is not None:
            attr = nome.rsplit(".", 1)[1]
            nc = {"video_objectdetection": "VideoObjectDetection",
                  "camera": "Camera", "web_ui": "WebUI"}[attr]
            setattr(mod, nc, cls)
        sys.modules[nome] = mod
    sys.modules["arduino"].app_bricks = sys.modules["arduino.app_bricks"]
    sys.modules["arduino"].app_peripherals = sys.modules["arduino.app_peripherals"]
    sys.modules["arduino.app_bricks"].video_objectdetection = \
        sys.modules["arduino.app_bricks.video_objectdetection"]
    sys.modules["arduino.app_bricks"].web_ui = \
        sys.modules["arduino.app_bricks.web_ui"]
    sys.modules["arduino.app_peripherals"].camera = \
        sys.modules["arduino.app_peripherals.camera"]
    import servidor as servidor_lucas  # noqa: E402
    import detector as det_lucas  # noqa: E402  (REAL do Lucas, com stubs)
    return det_lucas, servidor_lucas


det_lucas, servidor_lucas = _carregar_detector_real()
print(f"[setup] detector real: {det_lucas.__file__}")

# --- 0) detector real preserva conf/bbox no Operario --------------------------
spec = {"person": [{"confidence": 0.93, "bounding_box_xyxy": P0}],
        "helmet": [{"confidence": 0.90, "bounding_box_xyxy": HELM}],
        "vest": [{"confidence": 0.88, "bounding_box_xyxy": VEST}]}
ops = det_lucas.organizar_dado(dict(spec), [0, 0, 800, 600], True)
assert ops and len(ops) == 1, ops
o = ops[0]
assert o.tem_capacete is True and o.tem_colete is True and o.risco_detectado is True
assert o.conf_pessoa == 0.93 and o.conf_capacete == 0.90 and o.conf_colete == 0.88
assert tuple(o.bbox_capacete) == HELM and tuple(o.bbox_colete) == VEST
_ok("CASO 0 detector real preserva conf/bbox (Etapa 2)")

# --- 0b) callback publicado: 1 argumento -> Operario -> hook -----------------
# O contrato atual do Lucas é on_detect_all(operario_detectado), sem frame.
# Espiamos somente o hook para não escrever JSONL, fazer rede ou tocar banco.
assert list(inspect.signature(det_lucas.operario_detectado).parameters) == ["specs_frame"]
capturado = {}
processar_original = det_lucas._processar_operarios
risco_original = servidor_lucas.risco
box_original = servidor_lucas.box_risco
ultimo_original = det_lucas.ultimo_alerta

def _espia_callback(operarios, **kwargs):
    capturado["operarios"] = operarios
    capturado["kwargs"] = kwargs
    return {"ok": True, "eventos": 0, "descartado_bridge": False}

try:
    det_lucas._processar_operarios = _espia_callback
    servidor_lucas.risco = True
    servidor_lucas.box_risco = [0, 0, 800, 600]
    det_lucas.ultimo_alerta = 0
    retorno = det_lucas.operario_detectado(dict(spec))
    assert retorno is capturado["operarios"]
    assert len(capturado["operarios"]) == 1
    assert capturado["operarios"][0].tem_capacete is True
    assert capturado["operarios"][0].tem_colete is True
    assert capturado["operarios"][0].risco_detectado is True
    assert capturado["kwargs"]["specs_frame"] == spec
    assert capturado["kwargs"]["box_risco"] == [0, 0, 800, 600]
    assert capturado["kwargs"]["area_ativa"] is True
    assert "frame" not in capturado["kwargs"]
finally:
    det_lucas._processar_operarios = processar_original
    servidor_lucas.risco = risco_original
    servidor_lucas.box_risco = box_original
    det_lucas.ultimo_alerta = ultimo_original
_ok("CASO 0b callback atual: Operario -> hook, sem frame presumido")

# --- 1/2/3) com EPIs / sem colete / sem ambos --------------------------------
tmp, log = _log_tmp()
hook.resetar()
hook.configurar(log=log, debounce=EventDebounce(), camera_id="camera_1",
                risk_area=dict(AREA))
ops = det_lucas.organizar_dado(dict(spec), [0, 0, 800, 600], True)
r = hook.processar_operarios(ops, specs_frame=dict(spec),
                             box_risco=[0, 0, 800, 600], area_ativa=True)
assert r["ok"] and r["eventos"] == 2, r  # caso 1: com tudo
hook.configurar(log=log, debounce=EventDebounce(), camera_id="camera_1",
                risk_area=dict(AREA))  # debounce isolado por caso
spec2 = {"person": [{"confidence": 0.93, "bounding_box_xyxy": P0}],
         "helmet": [{"confidence": 0.90, "bounding_box_xyxy": HELM}]}
ops2 = det_lucas.organizar_dado(dict(spec2), [0, 0, 800, 600], True)
r2 = hook.processar_operarios(ops2, specs_frame=dict(spec2),
                              box_risco=[0, 0, 800, 600], area_ativa=True)
assert r2["eventos"] == 2, r2  # caso 2: com capacete, sem colete
hook.configurar(log=log, debounce=EventDebounce(), camera_id="camera_1",
                risk_area=dict(AREA))  # debounce isolado por caso
spec3 = {"person": [{"confidence": 0.91, "bounding_box_xyxy": P0}]}
ops3 = det_lucas.organizar_dado(dict(spec3), [0, 0, 800, 600], True)
r3 = hook.processar_operarios(ops3, specs_frame=dict(spec3),
                              box_risco=[0, 0, 800, 600], area_ativa=True)
assert r3["eventos"] == 2, r3  # caso 3: sem ambos (2 sem_*)
hook.resetar(); tmp.cleanup()
_ok("CASOS 1-3 com EPIs / sem colete / sem ambos")

# --- 4/5) indeterminado (tem=None) e sem pessoa -------------------------------
tmp, log = _log_tmp()
hook.resetar()
hook.configurar(log=log, debounce=EventDebounce(), risk_area=dict(AREA))
r = hook.processar_operarios(
    [{"box_xyxy": P0, "tem_capacete": None, "tem_colete": False,
      "risco_detectado": True}], box_risco=[0, 0, 800, 600], area_ativa=True)
assert r["eventos"] == 1, r  # caso 4: so o colete gera (sem_colete)
r = hook.processar_operarios([], box_risco=[0, 0, 800, 600], area_ativa=True)
assert r["eventos"] == 0, r  # caso 5a: lista vazia
ops_vazio = det_lucas.organizar_dado({"person": []}, [0, 0, 800, 600], True)
r = hook.processar_operarios(ops_vazio, specs_frame={"person": []},
                             box_risco=[0, 0, 800, 600], area_ativa=True)
assert r["eventos"] == 0, r  # caso 5b: detector retorna None sem pessoa
hook.resetar(); tmp.cleanup()
_ok("CASOS 4-5 indeterminado e sem pessoa")

# --- 6) sem conf/bbox opcionais -> fallback, sem excecao ----------------------
tmp, log = _log_tmp()
hook.resetar()
hook.configurar(log=log, debounce=EventDebounce(), risk_area=dict(AREA))
r = hook.processar_operarios(
    [{"box_xyxy": P0, "tem_capacete": True, "tem_colete": True,
      "risco_detectado": True}], box_risco=[0, 0, 800, 600], area_ativa=True)
assert r["ok"] and r["eventos"] == 2, r
hook.resetar(); tmp.cleanup()
_ok("CASO 6 fallback sem conf/bbox opcionais")

# --- 7) excecao nao interrompe o callback -------------------------------------
tmp, log = _log_tmp()
hook.resetar()
hook.configurar(log=log, debounce=EventDebounce(), risk_area=dict(AREA))
r = hook.processar_operarios([{"box_xyxy": "INVALIDO", "tem_capacete": True,
                               "tem_colete": True, "risco_detectado": True}],
                             box_risco=[0, 0, 800, 600], area_ativa=True)
assert r["ok"] and r["eventos"] == 0, r  # bbox invalida: 0 eventos, sem raise
r = hook.processar_operarios("lixo-nao-lista", box_risco="lixo", area_ativa=True)
assert r["ok"], r  # entrada absurda: capturada, callback vivo
assert hook.estado()["ciclos"] >= 2
hook.resetar(); tmp.cleanup()
_ok("CASO 7 excecao capturada, callback vivo")


# --- 8) falha HTTP nao bloqueia a camera --------------------------------------
tmp, log = _log_tmp()
hook.resetar()

def _falha(payload, api_base=None, timeout=None):
    raise TimeoutError("rede simulada")

ponte = DetectorIngestBridge(send_fn=_falha, max_queue=8)
hook.configurar(log=log, debounce=EventDebounce(), ponte=ponte,
                risk_area=dict(AREA))
ops = det_lucas.organizar_dado(dict(spec), [0, 0, 800, 600], True)
r = hook.processar_operarios(ops, specs_frame=dict(spec),
                             box_risco=[0, 0, 800, 600], area_ativa=True)
assert r["ok"] and r["eventos"] == 2, r  # log local OK apesar da falha HTTP
ponte.flush(5.0)
assert ponte.stats["failed"] == 1 and ponte.stats["sent"] == 0, ponte.stats
hook.resetar(); tmp.cleanup()
_ok("CASO 8 falha HTTP: log local OK, worker conta falha, camera livre")

# --- 9) debounce + ocorrencia --------------------------------------------------
tmp, log = _log_tmp()
hook.resetar()
hook.configurar(log=log, debounce=EventDebounce(), risk_area=dict(AREA))
ops = det_lucas.organizar_dado(dict(spec3), [0, 0, 800, 600], True)
a = hook.processar_operarios(ops, specs_frame=dict(spec3),
                             box_risco=[0, 0, 800, 600], area_ativa=True)
b = hook.processar_operarios(ops, specs_frame=dict(spec3),
                             box_risco=[0, 0, 800, 600], area_ativa=True)
assert a["eventos"] == 2 and b["eventos"] == 0, (a, b)  # debounce imediato
from occurrence import OccurrenceTracker
tmpd, logd = _log_tmp()
hook.resetar()
hook.configurar(log=logd, debounce=EventDebounce(),
                occurrence=OccurrenceTracker(confirm_frames=2, resolve_frames=2),
                risk_area=dict(AREA))
f1 = hook.processar_operarios(ops, specs_frame=dict(spec3),
                              box_risco=[0, 0, 800, 600], area_ativa=True)
f2 = hook.processar_operarios(ops, specs_frame=dict(spec3),
                              box_risco=[0, 0, 800, 600], area_ativa=True)
assert f1["eventos"] == 0 and f2["eventos"] == 2, (f1, f2)  # confirma em 2
hook.resetar(); tmp.cleanup(); tmpd.cleanup()
_ok("CASO 9 debounce + occurrence (2 frames)")

# --- 10+12) payload/area: canvas->frame + fora/sem area ------------------------
from risk_area_mapper import map_box_canvas_to_frame
conv = map_box_canvas_to_frame({"x1": 0, "y1": 0, "x2": 720, "y2": 460})
assert conv == {"x1": 0.0, "y1": 0.0, "x2": 720.0, "y2": 480.0}, conv
tmp, log = _log_tmp()
hook.resetar()
hook.configurar(log=log, debounce=EventDebounce(), risk_area=dict(AREA))
ops_fora = det_lucas.organizar_dado(dict(spec), [0, 0, 800, 600], False)
assert ops_fora[0].risco_detectado is False
r = hook.processar_operarios(ops_fora, specs_frame=dict(spec),
                             box_risco=[0, 0, 800, 600], area_ativa=True)
assert r["eventos"] == 0, r  # fora -> nada
r = hook.processar_operarios(ops_fora, specs_frame=dict(spec),
                             box_risco=None, area_ativa=False)
assert r["eventos"] == 0, r  # sem area -> nada (no_area explicito)
hook.resetar(); tmp.cleanup()
_ok("CASOS 10+12 area canvas->frame; fora/sem area: 0 eventos")

# --- 11) EPI nao aciona a SM de montagem ---------------------------------------
import state_machine as sm_mod
import event_ingest as ei_mod
chamadas = {"n": 0}
_orig_sm = sm_mod.ProcedureStateMachine.process_event
_orig_ing = ei_mod.ingerir_evento

def _espia_sm(self, event):
    chamadas["n"] += 1
    return _orig_sm(self, event)

def _espia_ing(*a, **k):
    chamadas["n"] += 1
    return _orig_ing(*a, **k)

sm_mod.ProcedureStateMachine.process_event = _espia_sm
ei_mod.ingerir_evento = _espia_ing
try:
    tmp, log = _log_tmp()
    hook.resetar()
    hook.configurar(log=log, debounce=EventDebounce(), risk_area=dict(AREA))
    ops = det_lucas.organizar_dado(dict(spec), [0, 0, 800, 600], True)
    hook.processar_operarios(ops, specs_frame=dict(spec),
                             box_risco=[0, 0, 800, 600], area_ativa=True)
    assert chamadas["n"] == 0, chamadas
    hook.resetar(); tmp.cleanup()
finally:
    sm_mod.ProcedureStateMachine.process_event = _orig_sm
    ei_mod.ingerir_evento = _orig_ing
_ok("CASO 11 SM/ingest procedural com 0 chamadas no fluxo EPI")

print(f"[OK] integracao_lucas: {len(PASSOS)} blocos passaram (casos 0-12).")
