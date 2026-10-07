"""Teste do pipeline observacional completo (somente payloads falsos).

payload on_detect_all -> adapter -> gate(parser) -> association -> context
    -> event_generator -> ObservationEvent -> debounce -> EventLog

Verificações obrigatórias:
  - registros no JSONL com status="observation"
  - NENHUMA chamada a State Machine.process_event / event_ingest / vision_bridge
  - debounce (event, camera_id, person_ref): 2 pessoas -> 2 registros
  - threshold único no parser (0.5)
  - camera_id vem da configuração
"""
from pathlib import Path
import json
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "event_arch"))
sys.path.insert(0, str(HERE.parent / "vision_integration"))

from event_debounce import EventDebounce
from event_log import EventLog
from pipeline import process_frame

# --- Guarda 1: se o pipeline chamar a máquina/ingest, o teste falha ----------
import state_machine
import event_ingest

_original_sm = state_machine.ProcedureStateMachine.process_event
_original_ingest = event_ingest.ingerir_evento
_chamadas = {"sm": 0, "ingest": 0}

def _sm_espia(self, event):
    _chamadas["sm"] += 1
    return _original_sm(self, event)

def _ingest_espia(*a, **k):
    _chamadas["ingest"] += 1
    return _original_ingest(*a, **k)

state_machine.ProcedureStateMachine.process_event = _sm_espia
event_ingest.ingerir_evento = _ingest_espia

# --- Guarda 2: pacote observacional não pode importar módulos proibidos ------
import pathlib
vi_dir = pathlib.Path(__file__).resolve().parent.parent / "vision_integration"
for f in vi_dir.glob("*.py"):
    for line in f.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if (s.startswith("import ") or s.startswith("from ")) and any(
            p in s for p in ("state_machine", "event_ingest", "vision_bridge")
        ):
            raise AssertionError(f"{f.name} importa módulo proibido: {s}")
print("[GUARDA] vision_integration sem imports de SM/ingest/bridge")

# --- Fixtures: 2 pessoas + EPIs, área cobrindo ambas --------------------------
P0 = (100.0, 100.0, 300.0, 400.0)     # centro (200,250)
P1 = (500.0, 100.0, 700.0, 400.0)     # centro (600,250)
HELMET_P0 = (150.0, 50.0, 250.0, 120.0)   # centro (200,85)  -> região helmet P0
VEST_P1 = (550.0, 250.0, 650.0, 350.0)    # centro (600,300) -> região vest P1
AREA = {"x1": 0.0, "y1": 0.0, "x2": 800.0, "y2": 600.0}

PAYLOAD = {
    "person": [
        {"confidence": 0.93, "bounding_box_xyxy": P0},
        {"confidence": 0.91, "bounding_box_xyxy": P1},
    ],
    "helmet": [{"confidence": 0.90, "bounding_box_xyxy": HELMET_P0}],
    "vest": [{"confidence": 0.88, "bounding_box_xyxy": VEST_P1}],
}


class RelogioFalso:
    def __init__(self):
        self.agora = 0.0
    def __call__(self):
        return self.agora
    def avancar(self, s):
        self.agora += s


def ler_log(log):
    if not log.path.exists():
        return []
    return [
        json.loads(l)
        for l in log.path.read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]


with tempfile.TemporaryDirectory() as tmp:
    # ===== 1) Fluxo completo: 4 conformidades, 2 pessoas =====================
    log = EventLog(Path(tmp) / "obs.jsonl")
    relogio = RelogioFalso()
    debounce = EventDebounce(clock=relogio)
    n, eventos = process_frame(PAYLOAD, log, debounce, risk_area=AREA)

    registros = ler_log(log)
    assert n == 4 and len(registros) == 4, (n, len(registros))
    nomes = [r["event"] for r in registros]
    assert nomes == [
        "pessoa_com_capacete", "pessoa_sem_colete",   # P0 (ref 0)
        "pessoa_sem_capacete", "pessoa_com_colete",   # P1 (ref 1)
    ], nomes
    print("[TESTE 1] 2 pessoas -> 4 conformidades independentes")

    for r in registros:
        assert r["status"] == "observation"
        assert r["source"] == "visao_computacional"
        assert r["previous_step"] == 0 and r["current_step"] == 0
        assert r["metadata"]["context"] == "inside"
    assert [r["metadata"]["person_ref"] for r in registros] == [0, 0, 1, 1]
    assert all(r["metadata"]["camera_id"] == "camera_1" for r in registros)
    print("[TESTE 2] JSONL: status/source/sentinhas/metadata corretos")

    # confidence congelada: com_* = min(pessoa, epi); sem_* = conf_pessoa
    por_evento = {r["event"]: r["metadata"] for r in registros}
    assert por_evento["pessoa_com_capacete"]["confidence"] == min(0.93, 0.90)
    assert por_evento["pessoa_com_colete"]["confidence"] == min(0.91, 0.88)
    assert por_evento["pessoa_sem_capacete"]["confidence"] == 0.91
    assert por_evento["pessoa_sem_colete"]["confidence"] == 0.93
    print("[TESTE 3] confidence: min() em com_*; conf_pessoa em sem_*")

    # ===== 4-5) Debounce por (evento, camera_id, person_ref) =================
    n2, _ = process_frame(PAYLOAD, log, debounce, risk_area=AREA)
    assert n2 == 0, "repetição imediata deve ser debounced"
    assert len(ler_log(log)) == 4, "debounce não pode gerar registros extras"
    print("[TESTE 4] mesmo frame na janela: tudo debounced")

    relogio.avancar(1.1)
    n3, _ = process_frame(PAYLOAD, log, debounce, risk_area=AREA)
    assert n3 == 4, "após a janela deve ser aceito novamente"
    print("[TESTE 5] após a janela: aceito novamente")

    # ===== 6) pessoas diferentes no mesmo frame não se bloqueiam =============
    debounce_livre = EventDebounce(clock=RelogioFalso())
    n4, ev4 = process_frame(PAYLOAD, log, debounce_livre, risk_area=AREA)
    refs = [e.metadata["person_ref"] for e in ev4]
    assert n4 == 4 and refs == [0, 0, 1, 1]
    print("[TESTE 6] pessoas diferentes no frame: sem supressão cruzada")

    # ===== 7-8) Threshold ÚNICO no parser (0.5) ==============================
    log_baixa = EventLog(Path(tmp) / "baixa.jsonl")
    nb, _ = process_frame(
        {"person": [{"confidence": 0.40, "bounding_box_xyxy": P0}]},
        log_baixa, None, risk_area=AREA,
    )
    assert nb == 0 and ler_log(log_baixa) == []
    print("[TESTE 7] confidence 0.40 < 0.5: rejeitada pelo gate do parser")

    log_limite = EventLog(Path(tmp) / "limite.jsonl")
    nl, _ = process_frame(
        {"person": [{"confidence": 0.5, "bounding_box_xyxy": P0}]},
        log_limite, None, risk_area=AREA,
    )
    assert nl == 2, nl  # limiar exato aceito (>=) -> sem_capacete + sem_colete
    print("[TESTE 8] confidence 0.5 (limiar exato): aceita pelo parser")

    # ===== 9-10) no_area / outside -> nenhuma conformidade ===================
    log_semarea = EventLog(Path(tmp) / "semarea.jsonl")
    ns, _ = process_frame(PAYLOAD, log_semarea, None, risk_area=None)
    assert ns == 0 and ler_log(log_semarea) == []
    print("[TESTE 9] no_area: nenhum evento de conformidade")

    log_fora = EventLog(Path(tmp) / "fora.jsonl")
    nf, _ = process_frame(PAYLOAD, log_fora, None,
                          risk_area={"x1": 5000.0, "y1": 5000.0,
                                     "x2": 6000.0, "y2": 6000.0})
    assert nf == 0 and ler_log(log_fora) == []
    print("[TESTE 10] outside: nenhum evento de conformidade")

    # ===== 11) Payload vazio / malformado ====================================
    log_vazio = EventLog(Path(tmp) / "vazio.jsonl")
    assert process_frame({}, log_vazio, None, risk_area=AREA)[0] == 0
    assert process_frame("não é dict", log_vazio, None, risk_area=AREA)[0] == 0
    assert process_frame(
        {"person": [{"confidence": "x", "bounding_box_xyxy": P0}]},
        log_vazio, None, risk_area=AREA,
    )[0] == 0
    assert ler_log(log_vazio) == []
    print("[TESTE 11] payload vazio/malformado: sem eventos, sem erro")

    # ===== 12) NENHUMA chamada à State Machine ou ingest =====================
    assert _chamadas["sm"] == 0, f"process_event chamado {_chamadas['sm']}x"
    assert _chamadas["ingest"] == 0, f"ingerir_evento chamado {_chamadas['ingest']}x"
    print("[TESTE 12] SM e ingest NÃO foram chamadas em nenhum teste")

state_machine.ProcedureStateMachine.process_event = _original_sm
event_ingest.ingerir_evento = _original_ingest

print("[OK] pipeline: fluxo observacional completo sem State Machine.")
