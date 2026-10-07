"""Testes do ObservationEvent e do adaptador fino para EventLog.write().

Somente payloads/objetos falsos — nenhum modelo, câmera ou State Machine.
"""
from pathlib import Path
import json
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "event_arch"))
sys.path.insert(0, str(HERE.parent / "vision_integration"))

from event_log import EventLog
from observation import ObservationEvent, ObservationResult, write_observation

# --- 1) Criação, campos e metadata -------------------------------------------
meta = {
    "label": "helmet",
    "confidence": 0.88,
    "bbox": [100.0, 100.0, 300.0, 400.0],
    "camera_id": "camera_1",
    "person_ref": 0,
    "context": "inside",
    "conf_pessoa": 0.93,
    "conf_epi": 0.88,
    "bbox_epi": [150.0, 50.0, 250.0, 120.0],
}
ev = ObservationEvent("pessoa_com_capacete", "Pessoa 0: capacete associado.", meta)
assert ev.event == "pessoa_com_capacete"
assert ev.message.startswith("Pessoa 0")
assert ev.metadata == meta
print("[TESTE 1] ObservationEvent: campos e metadata preservados")

# event != label (contrato §5): o label bruto vive no metadata, nunca no event.
assert ev.event != ev.metadata["label"]
print("[TESTE 2] event (regra) != label (detecção bruta)")

# --- 3) ObservationResult: contrato exato de EventLog.write() ----------------
res = ObservationResult(ev.event, ev.message)
assert res.status == "observation"
assert res.event == "pessoa_com_capacete"
assert res.message == ev.message
assert res.previous_step == 0 and res.current_step == 0
assert not hasattr(res, "status") or res.status != "advanced"
print("[TESTE 3] ObservationResult: 5 campos, status=observation, steps 0/0")

# NÃO é ProcedureResult (sem herança, sem semântica de procedimento)
from state_machine import ProcedureResult
assert not isinstance(res, ProcedureResult)
print("[TESTE 4] ObservationResult NÃO é ProcedureResult")

# --- 5) Escrita real no EventLog --------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    log = EventLog(Path(tmp) / "obs.jsonl")
    status = write_observation(ev, log)
    assert status == "written"
    registros = [
        json.loads(l)
        for l in log.path.read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    assert len(registros) == 1
    r = registros[0]
    assert r["status"] == "observation"
    assert r["source"] == "visao_computacional"
    assert r["event"] == "pessoa_com_capacete"
    assert r["previous_step"] == 0 and r["current_step"] == 0  # sentinelas
    assert r["metadata"]["person_ref"] == 0
    assert r["metadata"]["context"] == "inside"
    assert "timestamp" in r  # gerado pelo próprio EventLog
    print("[TESTE 5] registro JSONL: status/source/metadata corretos")

    # --- 6) Debounce integrado ao write ---------------------------------------
    class RelogioFalso:
        def __init__(self):
            self.agora = 0.0
        def __call__(self):
            return self.agora
        def avancar(self, s):
            self.agora += s

    from event_debounce import EventDebounce
    relogio = RelogioFalso()
    debounce = EventDebounce(clock=relogio)
    ev2 = ObservationEvent("pessoa_sem_colete", "m", dict(meta, person_ref=1))
    assert write_observation(ev2, log, debounce) == "written"
    assert write_observation(ev2, log, debounce) == "debounced"  # mesma janela
    relogio.avancar(1.1)
    assert write_observation(ev2, log, debounce) == "written"    # após janela
    print("[TESTE 6] debounce no write: bloqueio e liberação por janela")

print("[OK] observation_event: todos os testes passaram.")
