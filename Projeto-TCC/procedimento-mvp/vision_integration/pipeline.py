"""Pipeline observacional: ponto de entrada único da camada de visão.

Fluxo (CONGELADO no v3.4.2 — NÃO passa por vision_bridge, event_ingest nem
State Machine):

    payload on_detect_all
        -> adapt()        (adapter: formato + camera_id; sem threshold)
        -> gate()         (event_parser: ÚNICO gate de confidence, 0.5)
        -> associate()    (association: geometria intra-frame)
        -> evaluate()     (context: inside/outside/no_area por pessoa)
        -> generate()     (event_generator: conformidades -> ObservationEvent)
        -> write_observation() (debounce + EventLog, status="observation")

Uso (a chamada real on_detect_all vem do projeto de visão — ETAPA FUTURA):
    from vision_integration.pipeline import process_frame
    process_frame(detections, log, debounce)
"""
from pathlib import Path
import sys
from typing import Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "event_arch"))

from adapter import adapt, gate
from association import associate
from config import DEFAULT_CAMERA_ID, DEFAULT_RISK_AREA
from context import evaluate
from event_generator import generate
from observation import ObservationEvent, write_observation


def process_frame(
    payload: Dict,
    log,
    debounce=None,
    camera_id: Optional[str] = None,
    risk_area: Optional[Dict[str, float]] = None,
    occurrence=None,
) -> Tuple[int, List[ObservationEvent]]:
    """Processa UM frame do on_detect_all no fluxo observacional.

    Retorna (n_registros, eventos_escritos). Eventos debounced não são
    escritos mas continuam contabilizados separadamente pelo chamador via
    retorno (n_registros = escritos no EventLog).

    occurrence (opcional): OccurrenceTracker da camada temporal
    (occurrence.py). Quando fornecido, SUBSTITUI a geração por frame pelo
    retorno das transições confirmadas (abertura/encerramento de ocorrência);
    debounce e EventLog continuam iguais. Padrão None = comportamento
    congelado v3.4.2 (geração por frame).
    """
    camera = camera_id if camera_id is not None else DEFAULT_CAMERA_ID
    area = risk_area if risk_area is not None else DEFAULT_RISK_AREA

    # 1) Normalização estrutural (sem filtro de confiança aqui).
    detections = adapt(payload, camera_id=camera)

    # 2) Gate ÚNICO de confidence -> event_parser.parse_detection (0.5).
    accepted = [d for d in detections if gate(d)]

    # 3) Associação geométrica intra-frame (heurística experimental).
    associations = associate(accepted)

    # 4) Contexto por pessoa (stateless).
    contexts: Dict[int, str] = {
        a.person_ref: evaluate(a.bbox, area) for a in associations
    }

    # 5) Conformidades -> ObservationEvent (com camada temporal opcional).
    if occurrence is not None:
        events = occurrence.update(camera, associations, contexts)
    else:
        events = generate(associations, contexts)

    # 6) Debounce (evento, camera_id, person_ref) -> EventLog (status observation).
    written = [e for e in events if write_observation(e, log, debounce) == "written"]
    return len(written), written
