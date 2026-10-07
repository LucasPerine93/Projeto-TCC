"""Ponto único de ingestão de eventos padronizados.

Toda fonte (Arduino, terminal, visão computacional, ...) deve traduzir sua
entrada para um ParsedEvent e chamar ingerir_evento(). Este módulo não sabe
de onde o evento veio: apenas processa na máquina de estados, registra no
EventLog e devolve o ProcedureResult.

Nenhum conhecimento sobre serial, câmera ou modelo vive aqui.
"""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from event_log import EventLog
from event_parser import ParsedEvent
from state_machine import ProcedureResult, ProcedureStateMachine


def ingerir_evento(
    parsed: ParsedEvent,
    procedure: ProcedureStateMachine,
    log: EventLog,
    source: str,
) -> ProcedureResult:
    """Processa um evento padronizado: máquina de estados -> log -> resultado.

    Função neutra: não sabe se o evento veio do Arduino, do teclado,
    da visão computacional ou de qualquer outra fonte.
    """
    result = procedure.process_event(parsed.event)
    log.write(result, source=source, metadata=parsed.metadata)

    print(f"[DETECCAO] {parsed.label}")
    print(f"[{result.status.upper()}] {result.message}")
    if result.status == "error":
        esperado = procedure.status()["expected_step"]
        if esperado:
            print(f"[AGUARDANDO] {esperado}")

    return result


def ingerir_reset(
    procedure: ProcedureStateMachine,
    log: EventLog,
    source: str,
) -> ProcedureResult:
    """Reinicia a máquina de estados e registra o reset no log (neutra)."""
    result = procedure.reset()
    log.write(result, source=source)
    print(f"[RESET] {result.message}")
    return result
