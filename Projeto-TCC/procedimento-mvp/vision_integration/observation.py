"""ObservationEvent + adaptador fino para o EventLog existente.

ObservationEvent = evento DERIVADO de conformidade (associação + contexto +
regra). NÃO é um ParsedEvent (que representa detecções), NÃO passa pela
State Machine e NÃO é ProcedureResult.

Contrato com EventLog.write(result, source, metadata):
  - ObservationResult expõe exatamente os 5 campos exigidos:
        status="observation" | event | message | previous_step=0 | current_step=0
  - previous_step/current_step são SENTINELAS 0 apenas para compatibilidade
    estrutural com o contrato do log; NÃO representam etapa de procedimento.
  - metadata (com todos os campos observacionais) vai no 3º parâmetro de
    write(), nunca embutida no resultado.
"""
from typing import Dict, Optional

SOURCE = "visao_computacional"   # source já usado pelo fluxo procedural


class ObservationEvent:
    """Evento de conformidade gerado pela camada observacional.

    event: regra derivada ("pessoa_com_capacete", "pessoa_sem_capacete",
          "pessoa_com_colete", "pessoa_sem_colete") — NUNCA o label bruto.
    metadata: label bruto e demais dados (ver event_generator).
    """

    def __init__(self, event: str, message: str, metadata: Dict):
        self.event = event
        self.message = message
        self.metadata = metadata


class ObservationResult:
    """Adaptador fino: ObservationEvent -> contrato de EventLog.write().

    NÃO é ProcedureResult e NÃO veio da State Machine (esta camada sequer
    importa state_machine/event_ingest/vision_bridge).
    """

    def __init__(self, event: str, message: str):
        self.status = "observation"
        self.event = event
        self.message = message
        self.previous_step = 0   # sentinela estrutural — não é progresso
        self.current_step = 0    # sentinela estrutural — não é progresso


def write_observation(
    obs_event: ObservationEvent,
    log,
    debounce=None,
) -> str:
    """Debounce (evento, camera_id, person_ref) -> EventLog.write().

    Retorna "written" | "debounced". NÃO chama ingest nem a máquina de estados.
    """
    camera_id = obs_event.metadata.get("camera_id")
    person_ref = obs_event.metadata.get("person_ref")

    if debounce is not None:
        if not debounce.autorizar(obs_event.event, camera_id, person_ref):
            return "debounced"

    log.write(
        ObservationResult(obs_event.event, obs_event.message),
        source=SOURCE,
        metadata=obs_event.metadata,
    )
    return "written"
