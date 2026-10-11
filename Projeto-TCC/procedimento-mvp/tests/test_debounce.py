"""Testes do debounce e da metadata (somente payloads simulados).

Cobre: primeiro evento, repetição imediada, passagem de tempo SEM sleep(),
câmeras diferentes, eventos diferentes e metadata do parse até o EventLog.
"""
from pathlib import Path
import json
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "event_arch"))

from config_loader import load_procedure
from event_debounce import DEFAULT_DEBOUNCE_INTERVAL, EventDebounce
from event_ingest import ingerir_evento
from event_log import EventLog
from event_parser import parse_detection
from state_machine import ProcedureResult, ProcedureStateMachine

CONFIG = HERE.parent / "config" / "procedures.json"


class RelogioFalso:
    """Relógio controlado pelo teste: avança o tempo sem sleep()."""

    def __init__(self):
        self.agora = 0.0

    def __call__(self):
        return self.agora

    def avancar(self, segundos):
        self.agora += segundos


# --- Teste 1: primeiro evento aceito ----------------------------------------
relogio = RelogioFalso()
debounce = EventDebounce(interval=DEFAULT_DEBOUNCE_INTERVAL, clock=relogio)
assert DEFAULT_DEBOUNCE_INTERVAL > 0  # intervalo default provisório, documentado
assert debounce.autorizar("capacete_detectado", "camera_1") is True
print("[TESTE 1] primeiro CAPACETE camera_1 aceito")

# --- Teste 2: repetição imediata bloqueada ----------------------------------
relogio.avancar(0.1)
assert debounce.autorizar("capacete_detectado", "camera_1") is False
relogio.avancar(0.5)
assert debounce.autorizar("capacete_detectado", "camera_1") is False
print("[TESTE 2] repetições imediatas bloqueadas pelo debounce")

# --- Teste 3: depois do intervalo, aceito (tempo simulado, sem sleep) -------
relogio.avancar(DEFAULT_DEBOUNCE_INTERVAL)  # t = 1.6; aceite anterior em t = 0.0
assert debounce.autorizar("capacete_detectado", "camera_1") is True
print(f"[TESTE 3] aceito após {DEFAULT_DEBOUNCE_INTERVAL}s de tempo simulado")

# --- Teste 4: câmeras diferentes não são duplicata --------------------------
assert debounce.autorizar("capacete_detectado", "camera_2") is True
print("[TESTE 4] camera_2 não tratada como duplicata de camera_1")

# --- Teste 5: eventos diferentes não são o mesmo evento ---------------------
assert debounce.autorizar("luva_detectada", "camera_1") is True
print("[TESTE 5] LUVA camera_1 não tratada como CAPACETE camera_1")

# --- Intervalo configurável --------------------------------------------------
relogio_curto = RelogioFalso()
debounce_curto = EventDebounce(interval=0.5, clock=relogio_curto)
assert debounce_curto.autorizar("capacete_detectado", "camera_1") is True
relogio_curto.avancar(0.6)
assert debounce_curto.autorizar("capacete_detectado", "camera_1") is True
print("[EXTRA] intervalo customizado (0.5s) respeitado")

# --- Teste 6: metadata chega ao log -----------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    # Fixture local de procedimento (NÃO altera config/procedures.json).
    procedure = ProcedureStateMachine({
        "name": "Fixture de teste - deteccoes",
        "steps": [
            {"id": "E1", "name": "Capacete", "event": "capacete_detectado"},
            {"id": "E2", "name": "Luva", "event": "luva_detectada"},
        ],
    })
    log = EventLog(Path(tmp) / "visao.jsonl")
    relogio = RelogioFalso()
    debounce = EventDebounce(clock=relogio)

    payload = {
        "label": "CAPACETE",
        "confidence": 0.91,
        "timestamp": "2026-10-03T12:00:00Z",
        "bbox": [100, 50, 300, 400],
        "camera_id": "camera_1",
    }

    # Pipeline: parse -> debounce -> ingest -> log
    tipo, parsed = parse_detection(payload)
    assert tipo == "accepted"
    assert parsed.metadata == {
        "timestamp": "2026-10-03T12:00:00Z",
        "confidence": 0.91,
        "bbox": [100, 50, 300, 400],
        "camera_id": "camera_1",
    }
    camera_id = parsed.metadata.get("camera_id")
    assert debounce.autorizar(parsed.event, camera_id) is True
    result = ingerir_evento(parsed, procedure, log, source="visao_computacional")
    assert result.status == "advanced"

    # Repetição imediata: bloqueada -> nenhum novo registro no log
    tipo, repetido = parse_detection(dict(payload, confidence=0.93))
    assert tipo == "accepted"
    assert debounce.autorizar(repetido.event, camera_id) is False

    registros = [
        json.loads(linha)
        for linha in log.path.read_text(encoding="utf-8").splitlines()
        if linha.strip()
    ]
    assert len(registros) == 1, f"bloqueio deveria impedir 2o registro: {registros}"
    registro = registros[0]
    assert registro["source"] == "visao_computacional"
    assert registro["status"] == "advanced"
    assert registro["event"] == "capacete_detectado"
    meta = registro["metadata"]
    assert meta["timestamp"] == "2026-10-03T12:00:00Z"
    assert meta["confidence"] == 0.91
    assert meta["bbox"] == [100, 50, 300, 400]
    assert meta["camera_id"] == "camera_1"
    print("[TESTE 6] metadata preservada: parse -> ingest -> log (1 registro)")

    # Compatibilidade: registro sem metadata mantém o formato antigo
    log_sem = EventLog(Path(tmp) / "sem_meta.jsonl")
    log_sem.write(
        ProcedureResult("advanced", "base_confirmada", "ok", 0, 1),
        source="arduino_mega",
    )
    antigo = json.loads(log_sem.path.read_text(encoding="utf-8").splitlines()[0])
    assert "metadata" not in antigo
    assert antigo["source"] == "arduino_mega" and antigo["status"] == "advanced"
    print("[EXTRA] registro sem metadata mantém o formato antigo (Arduino)")

print("[OK] debounce + metadata: todos os testes passaram.")
