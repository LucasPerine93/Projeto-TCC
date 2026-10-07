"""Ponte entre pipelines de visão computacional e a arquitetura de procedimentos.

Composição EXCLUSIVA das camadas existentes:

    payload de detecção
        -> parse_detection()         (event_parser)
        -> EventDebounce.autorizar() (event_debounce)
        -> ingerir_evento()          (event_ingest)
        -> ProcedureStateMachine     (state_machine)
        -> EventLog                  (event_log)

Este módulo NÃO contém: lógica de máquina de estados, regras de procedimento,
código YOLO/processamento de imagem, tracking, dashboard, Telegram etc.
Apenas conecta os componentes — e a ProcedureStateMachine não sabe que o
debounce existe.

Uso futuro (NÃO implementado nesta etapa): o pipeline de visão chama
process_detection(payload, procedure, log, debounce) a cada detecção.
"""
from pathlib import Path
import sys
from typing import Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from event_debounce import EventDebounce
from event_ingest import ingerir_evento
from event_log import EventLog
from event_parser import parse_detection
from state_machine import ProcedureResult, ProcedureStateMachine


def process_detection(
    payload,
    procedure: ProcedureStateMachine,
    log: EventLog,
    debounce: EventDebounce,
) -> Tuple[str, Optional[ProcedureResult]]:
    """Processa uma detecção da visão: parse -> debounce -> ingestão.

    Retorna (resultado, ProcedureResult) onde resultado é:
      "accepted"       -> processado; 2º elemento é o resultado real de
                          ingerir_evento() (advanced/completed/error)
      "debounced"      -> repetição bloqueada; máquina e log NÃO são chamados
      "low_confidence" -> confiança abaixo do threshold; não chega à máquina
      "unknown_class"  -> classe não mapeada; não chega à máquina
      "invalid"        -> payload inválido; não chega à máquina

    O camera_id vem da metadata do parse (ausente -> None, chave neutra
    aceita pelo EventDebounce — nenhuma câmera é inventada).
    """
    tipo, parsed = parse_detection(payload)
    if tipo != "accepted":
        return tipo, None

    # "accepted" garante metadata (ao menos confidence); camera_id é opcional.
    camera_id = (parsed.metadata or {}).get("camera_id")

    if not debounce.autorizar(parsed.event, camera_id):
        print(f"[DEBOUNCE] {parsed.label} ignorado (repetição de {debounce.interval}s).")
        return "debounced", None

    result = ingerir_evento(parsed, procedure, log, source="visao_computacional")
    return "accepted", result
