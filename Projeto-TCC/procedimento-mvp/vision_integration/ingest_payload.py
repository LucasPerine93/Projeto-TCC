"""Adaptador vision_integration -> payload de ingestão da API.

Converte o resultado REAL de process_frame() em IngestBatchIn SEM tocar
a pipeline: preserva o payload bruto do on_detect_all e serializa os
ObservationEvent (event + message + metadata). NÃO envia nada pela rede
e NÃO altera State Machine / event_ingest / vision_bridge.
"""
from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "dashboard" / "backend"))

from app.schemas import IngestBatchIn, IngestObservationIn, RiskAreaCoords  # noqa: E402


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def build_ingest_payload(
    raw_payload: dict,
    events: list,
    camera_id: str = "camera_1",
    model_name: str | None = None,
    model_version: str | None = None,
    received_at=None,
    risk_area: dict | None = None,
) -> IngestBatchIn:
    """Monta o payload POST /api/observations/ingest a partir do pipeline.

    risk_area (dict com x1,y1,x2,y2 ou None): área usada na avaliação de
    contexto — preservada no payload para o servidor resolver risk_area_id.
    """
    obs = []
    for e in events:
        md = e.metadata
        if not isinstance(md, dict):
            # IngestMetadata (pydantic) ou similar -> dict serializável
            md = md.model_dump() if hasattr(md, "model_dump") else dict(md)
        obs.append(
            IngestObservationIn(
                event=e.event,
                message=e.message,
                metadata=_json_safe(dict(md)),
            )
        )
    ra = None
    if isinstance(risk_area, dict) and all(k in risk_area for k in ("x1", "y1", "x2", "y2")):
        try:
            ra = RiskAreaCoords(
                x1=float(risk_area["x1"]),
                y1=float(risk_area["y1"]),
                x2=float(risk_area["x2"]),
                y2=float(risk_area["y2"]),
            )
        except (TypeError, ValueError):
            ra = None  # coords malformadas: não invalida o lote inteiro
    return IngestBatchIn(
        camera_id=camera_id,
        received_at=received_at,
        model_name=model_name,
        model_version=model_version,
        raw_detections=_json_safe(raw_payload if isinstance(raw_payload, dict) else {}),
        risk_area=ra,
        observations=obs,
    )
