"""Schemas Pydantic para as respostas da API e ingestão observacional."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class HealthOut(BaseModel):
    status: str


class HealthDbOut(BaseModel):
    status: str
    database: str


class CameraOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    location: str | None = None
    active: bool


class EpiOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: str | None = None
    active: bool


class EventTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    description: str
    compliant: bool
    epi_code: str
    epi_name: str


class RiskAreaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    camera_id: int
    camera_code: str
    name: str
    x1: float
    y1: float
    x2: float
    y2: float
    active: bool


# ============================================================
# Ingestão observacional: POST /api/observations/ingest
# 1 lote on_detect_all -> 1 batch + 0..N observations (1 transação).
# camera_id aqui é o CÓDIGO lógico ("camera_1"), não o PK interno.
# ============================================================

ContextValue = Literal["inside", "outside", "no_area", "indeterminate"]


class IngestMetadata(BaseModel):
    """Metadata do ObservationEvent (origem preservada por categoria)."""

    model_config = ConfigDict(populate_by_name=True)

    label: str = Field(min_length=1, max_length=50)
    confidence: float = Field(ge=0, le=1)
    bbox: list[float] = Field(min_length=4, max_length=4)
    camera_id: str | None = Field(default=None, min_length=1, max_length=50)
    person_ref: int = Field(ge=0)
    context: ContextValue
    conf_pessoa: float = Field(ge=0, le=1)
    conf_epi: float | None = Field(default=None, ge=0, le=1)
    bbox_epi: list[float] | None = Field(default=None, min_length=4, max_length=4)

    @field_validator("bbox")
    @classmethod
    def _check_bbox(cls, v: list[float]) -> list[float]:
        x1, y1, x2, y2 = (float(x) for x in v)
        if not (x2 > x1 and y2 > y1):
            raise ValueError("bbox inválida: exige x2>x1 e y2>y1.")
        return [x1, y1, x2, y2]

    @field_validator("bbox_epi")
    @classmethod
    def _check_bbox_epi(cls, v: list[float] | None) -> list[float] | None:
        if v is None:
            return None
        x1, y1, x2, y2 = (float(x) for x in v)
        if not (x2 > x1 and y2 > y1):
            raise ValueError("bbox_epi inválida: exige x2>x1 e y2>y1.")
        return [x1, y1, x2, y2]


class IngestObservationIn(BaseModel):
    """Um ObservationEvent serializado (event + message + metadata)."""

    event: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=500)
    metadata: IngestMetadata


class RiskAreaCoords(BaseModel):
    """Retângulo da área de risco em coordenadas do FRAME (vem da pipeline).

    A pipeline só conhece coordenadas (não existem IDs no lado da visão);
    o servidor resolve estas coordenadas para risk_areas.id quando casam
    com uma área cadastrada e ativa da mesma câmera. Sem correspondência:
    risk_area_id permanece NULL (nenhum ID é inventado).
    """

    x1: float
    y1: float
    x2: float
    y2: float


class IngestBatchIn(BaseModel):
    """Payload de UM lote observacional (1 chamada on_detect_all)."""

    model_config = ConfigDict(populate_by_name=True)

    camera_id: str = Field(min_length=1, max_length=50)
    received_at: datetime | None = None
    model_name: str | None = Field(default=None, max_length=100)
    model_version: str | None = Field(default=None, max_length=100)
    raw_detections: dict[str, Any]
    # Área de risco opcional (coords do frame) — preservada até o banco.
    risk_area: RiskAreaCoords | None = None
    observations: list[IngestObservationIn] = Field(default_factory=list)

    @field_validator("raw_detections")
    @classmethod
    def _check_raw(cls, v: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(v, dict):
            raise ValueError("raw_detections deve ser um objeto JSON.")
        return v


class IngestBatchOut(BaseModel):
    batch_id: int
    observations_created: int
    # true quando o servidor reconheceu o REENVIO do mesmo
    # (camera_id, received_at) e devolveu o batch já existente.
    duplicate: bool = False
    # IDs reais (observations.id) criados neste lote, na ordem de inserção.
    # Permite ao chamador vincular evidências de imagem à ocorrência EXATA
    # persistida (nunca um id provisório). Vazio quando duplicate=True.
    observation_ids: list[int] = Field(default_factory=list)


# ============================================================
# Leitura de observações: GET /api/observations e
# GET /api/observations/summary (somente leitura do MVP).
# conformidade é derivada de event_types.compliant.
# ============================================================


class ObservationOut(BaseModel):
    """Uma observação persistida, já resolvida com câmera e evento."""

    id: int
    created_at: datetime
    batch_id: int
    camera_code: str
    camera_name: str
    event_code: str
    event_description: str
    compliant: bool
    epi_code: str
    epi_name: str
    context: str
    person_ref: int
    event_confidence: float
    conf_pessoa: float
    conf_epi: float | None = None
    # Área de risco do batch quando resolvida (NULL = sem correspondência).
    risk_area_id: int | None = None


class ObservationListOut(BaseModel):
    total: int
    items: list[ObservationOut]


class SummaryByDayOut(BaseModel):
    date: str  # YYYY-MM-DD (fuso da sessão do banco)
    total: int
    compliant: int
    non_compliant: int


class SummaryByCameraOut(BaseModel):
    camera_code: str
    camera_name: str
    total: int
    compliant: int
    non_compliant: int


class SummaryByEventTypeOut(BaseModel):
    event_code: str
    event_description: str
    compliant: bool
    total: int


class ObservationSummaryOut(BaseModel):
    """Resumo das observações disponíveis (sem noções de pessoas únicas)."""

    total_observations: int
    compliant_observations: int
    non_compliant_observations: int
    # Taxa de conformidade das observações: conformes / total.
    # None quando não há observações registradas.
    compliance_rate: float | None = None
    by_day: list[SummaryByDayOut]
    by_camera: list[SummaryByCameraOut]
    by_event_type: list[SummaryByEventTypeOut]


class ImageEvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    occurrence_id: int
    camera_code: str
    mime_type: str
    file_name: str
    sha256: str
    # Caminho absoluto NÃO é exposto pela API (ver file_record_to_dict);
    # mantido opcional para compatibilidade com registros internos.
    image_path: str | None = None
    created_at: datetime


class ImageEvidenceListOut(BaseModel):
    total: int
    items: list[ImageEvidenceOut]
