"""Persistência da ingestão observacional (1 transação por lote).

1 batch + 0..N observations em UMA transação SQLAlchemy 2.x.
Não toca State Machine, event_ingest nem vision_bridge.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Camera, EventType, Observation, ObservationBatch, RiskArea
from app.schemas import IngestBatchIn

# Tolerância (em pixels do frame) para casar as coordenadas recebidas com as
# áreas cadastradas — absorve arredondamento de calibração; PROVISÓRIO.
RISK_AREA_EPS = 1.0


def _json_safe(value: Any) -> Any:
    """Converte tuples/estruturas do pipeline em JSON serializável."""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _received_at_or_now(received_at: datetime | None) -> datetime:
    if received_at is None:
        return datetime.now(timezone.utc)
    if received_at.tzinfo is None:
        return received_at.replace(tzinfo=timezone.utc)
    return received_at


def _resolve_risk_area_id(db: Session, camera_pk: int, area) -> int | None:
    """Coordenadas recebidas -> risk_areas.id da mesma câmera (ativa).

    Só retorna um ID quando existe correspondência (com RISK_AREA_EPS de
    tolerância, coordenadas normalizadas min/max) em área ATIVA desta câmera.
    Sem área no payload ou sem correspondência -> None (nada é inventado).
    """
    if area is None:
        return None
    rx1, rx2 = sorted((float(area.x1), float(area.x2)))
    ry1, ry2 = sorted((float(area.y1), float(area.y2)))
    rows = db.execute(
        select(RiskArea.id, RiskArea.x1, RiskArea.y1, RiskArea.x2, RiskArea.y2).where(
            RiskArea.camera_id == camera_pk,
            RiskArea.active.is_(True),
        )
    ).all()
    for ra_id, ax1, ay1, ax2, ay2 in rows:
        ax_lo, ax_hi = sorted((float(ax1), float(ax2)))
        ay_lo, ay_hi = sorted((float(ay1), float(ay2)))
        if (
            abs(rx1 - ax_lo) <= RISK_AREA_EPS
            and abs(rx2 - ax_hi) <= RISK_AREA_EPS
            and abs(ry1 - ay_lo) <= RISK_AREA_EPS
            and abs(ry2 - ay_hi) <= RISK_AREA_EPS
        ):
            return int(ra_id)
    return None


def ingest_batch(db: Session, payload: IngestBatchIn) -> tuple[int, int, bool, list[int]]:
    """Persiste 1 batch + N observations atomicamente.

    Retorna (batch_id, observations_created, duplicate, observation_ids).
    observation_ids são os IDs reais (observations.id) na ordem de inserção —
    permitem vincular evidências de imagem à ocorrência persistida. Vazio
    quando duplicate=True (nada novo foi criado). Levanta HTTPException
    (404 câmera, 422 evento) — nesse caso nada é persistido (rollback).

    Idempotência: quando o payload traz received_at, um reenvio do MESMO
    (camera_id, received_at) devolve o batch já existente sem criar registros
    (protege contra retries ambíguos — ex.: timeout após o commit). Sem
    received_at, cada chamada cria um batch novo (comportamento anterior).
    """
    try:
        camera = db.execute(
            select(Camera).where(Camera.code == payload.camera_id)
        ).scalar_one_or_none()
        if camera is None:
            raise HTTPException(
                status_code=404,
                detail=f"Câmera '{payload.camera_id}' não encontrada.",
            )

        if payload.received_at is not None:
            received = _received_at_or_now(payload.received_at)
            existing_id = db.execute(
                select(ObservationBatch.id).where(
                    ObservationBatch.camera_id == camera.id,
                    ObservationBatch.received_at == received,
                )
            ).scalar_one_or_none()
            if existing_id is not None:
                return int(existing_id), 0, True, []

        model_name = payload.model_name
        if not model_name:
            model_name = get_settings().model_name

        batch = ObservationBatch(
            camera_id=camera.id,
            risk_area_id=_resolve_risk_area_id(db, camera.id, payload.risk_area),
            received_at=_received_at_or_now(payload.received_at),
            model_name=model_name,
            model_version=payload.model_version,
            raw_detections=_json_safe(payload.raw_detections),
            created_at=datetime.now(timezone.utc),
        )
        db.add(batch)
        db.flush()  # obtém batch.id sem commitar

        # Lookup antecipado de todos os event_types (falha antes de persistir).
        codes = [o.event for o in payload.observations]
        type_by_code: dict[str, EventType] = {}
        for code in set(codes):
            et = db.execute(
                select(EventType).where(EventType.code == code)
            ).scalar_one_or_none()
            if et is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"event_type '{code}' desconhecido.",
                )
            type_by_code[code] = et

        obs_ids: list[int] = []
        for obs in payload.observations:
            md = obs.metadata
            epi = list(md.bbox_epi) if md.bbox_epi is not None else [None] * 4
            now = datetime.now(timezone.utc)
            new_obs = Observation(
                batch_id=batch.id,
                event_type_id=type_by_code[obs.event].id,
                person_ref=md.person_ref,
                context=md.context,
                event_confidence=float(md.confidence),
                conf_pessoa=float(md.conf_pessoa),
                conf_epi=float(md.conf_epi) if md.conf_epi is not None else None,
                person_bbox_x1=float(md.bbox[0]),
                person_bbox_y1=float(md.bbox[1]),
                person_bbox_x2=float(md.bbox[2]),
                person_bbox_y2=float(md.bbox[3]),
                epi_bbox_x1=float(epi[0]) if epi[0] is not None else None,
                epi_bbox_y1=float(epi[1]) if epi[1] is not None else None,
                epi_bbox_x2=float(epi[2]) if epi[2] is not None else None,
                epi_bbox_y2=float(epi[3]) if epi[3] is not None else None,
                source="visao_computacional",
                created_at=now,
            )
            db.add(new_obs)
            db.flush()  # obtém new_obs.id (real) para vincular evidências depois
            obs_ids.append(int(new_obs.id))

        db.commit()
        db.refresh(batch)
        return int(batch.id), len(payload.observations), False, obs_ids
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
