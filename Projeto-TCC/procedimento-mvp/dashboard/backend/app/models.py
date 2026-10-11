"""Modelos SQLAlchemy que refletem o schema existente do banco tcc_ppe.

Regras:
- nomes de tabelas e colunas são exatamente os do schema.sql;
- nenhum campo novo foi inventado;
- nenhum create_all() é executado.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Double, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    location: Mapped[str | None] = mapped_column(String(150))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class Epi(Base):
    __tablename__ = "epis"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class EventType(Base):
    __tablename__ = "event_types"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    epi_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("epis.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    compliant: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class RiskArea(Base):
    __tablename__ = "risk_areas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    camera_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("cameras.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    x1: Mapped[float] = mapped_column(Double, nullable=False)
    y1: Mapped[float] = mapped_column(Double, nullable=False)
    x2: Mapped[float] = mapped_column(Double, nullable=False)
    y2: Mapped[float] = mapped_column(Double, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class ObservationBatch(Base):
    """Espelha observation_batches (1 lote = 1 chamada on_detect_all)."""

    __tablename__ = "observation_batches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    camera_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("cameras.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    risk_area_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("risk_areas.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=True,
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    model_name: Mapped[str | None] = mapped_column(String(100))
    model_version: Mapped[str | None] = mapped_column(String(100))
    raw_detections: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class Observation(Base):
    """Espelha observations (conclusão observacional por pessoa/evento)."""

    __tablename__ = "observations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("observation_batches.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    event_type_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("event_types.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    person_ref: Mapped[int] = mapped_column(Integer, nullable=False)
    context: Mapped[str] = mapped_column(String(20), nullable=False)
    event_confidence: Mapped[float] = mapped_column(Double, nullable=False)
    conf_pessoa: Mapped[float] = mapped_column(Double, nullable=False)
    conf_epi: Mapped[float | None] = mapped_column(Double)

    person_bbox_x1: Mapped[float | None] = mapped_column(Double)
    person_bbox_y1: Mapped[float | None] = mapped_column(Double)
    person_bbox_x2: Mapped[float | None] = mapped_column(Double)
    person_bbox_y2: Mapped[float | None] = mapped_column(Double)

    epi_bbox_x1: Mapped[float | None] = mapped_column(Double)
    epi_bbox_y1: Mapped[float | None] = mapped_column(Double)
    epi_bbox_x2: Mapped[float | None] = mapped_column(Double)
    epi_bbox_y2: Mapped[float | None] = mapped_column(Double)

    # Origem lógica do registro (schema: source VARCHAR DEFAULT 'visao_computacional').
    source: Mapped[str] = mapped_column(
        String(50), nullable=False, default="visao_computacional"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

class ImageEvidence(Base):
    __tablename__ = "image_evidence"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    occurrence_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("observations.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    camera_code: Mapped[str] = mapped_column(String(50), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    image_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
