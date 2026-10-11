"""Backend TCC-PPE — FastAPI + PostgreSQL.

Etapa atual: base da API (health checks + endpoints de consulta do MVP)
+ ingestão observacional (POST /api/observations/ingest).
Sem autenticação, sem frontend.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import check_database_connection, get_db
from app.image_store import (
    decode_image_path,
    file_record_to_dict,
    get_image_dir,
    save_image_evidence,
)
from app.ingest import ingest_batch
from app.models import ImageEvidence, Observation
from app.schemas import (
    CameraOut,
    EpiOut,
    EventTypeOut,
    HealthDbOut,
    HealthOut,
    IngestBatchIn,
    IngestBatchOut,
    ObservationListOut,
    ObservationOut,
    ObservationSummaryOut,
    RiskAreaOut,
    SummaryByCameraOut,
    SummaryByDayOut,
    SummaryByEventTypeOut,
    ImageEvidenceOut,
    ImageEvidenceListOut,
)

app = FastAPI(
    title="TCC-PPE API",
    description=(
        "API do dashboard de monitoramento inteligente de EPI. "
        "Etapa atual: consulta do MVP (somente leitura)."
    ),
    version="0.1.0",
)

# CORS: apenas as origens do frontend (configuráveis via CORS_ORIGINS).
# Necessário para o React em http://localhost:5173 consultar a API e enviar
# a evidência de imagem (POST multipart /api/images). Cabeçalhos `*` cobrem
# Content-Type (multipart/form-data); sem credenciais (cookies desabilitados).
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ============================================================
# Health checks
# ============================================================

@app.get("/health", response_model=HealthOut, tags=["health"])
def health() -> HealthOut:
    """Health check da aplicação (não toca o banco)."""
    return HealthOut(status="ok")


@app.get("/health/db", response_model=HealthDbOut, tags=["health"])
def health_db() -> HealthDbOut:
    """Health check real: executa uma consulta no PostgreSQL."""
    try:
        database = check_database_connection()
    except Exception:
        # Não expor string de conexão, senha ou stacktrace.
        raise HTTPException(
            status_code=503,
            detail="Banco de dados indisponível.",
        )
    return HealthDbOut(status="ok", database=database)


# ============================================================
# Endpoints de consulta do MVP (somente leitura)
# ============================================================

@app.get("/api/cameras", response_model=list[CameraOut], tags=["mvp"])
def list_cameras(db: Session = Depends(get_db)) -> list[CameraOut]:
    """Lista as câmeras cadastradas."""
    rows = db.execute(
        text("SELECT id, code, name, location, active FROM cameras ORDER BY id")
    ).all()
    return [
        CameraOut(
            id=r[0], code=r[1], name=r[2], location=r[3], active=r[4]
        )
        for r in rows
    ]


@app.get("/api/epis", response_model=list[EpiOut], tags=["mvp"])
def list_epis(db: Session = Depends(get_db)) -> list[EpiOut]:
    """Lista os EPIs monitorados."""
    rows = db.execute(
        text(
            "SELECT id, code, name, description, active FROM epis ORDER BY id"
        )
    ).all()
    return [
        EpiOut(
            id=r[0], code=r[1], name=r[2], description=r[3], active=r[4]
        )
        for r in rows
    ]


@app.get("/api/event-types", response_model=list[EventTypeOut], tags=["mvp"])
def list_event_types(db: Session = Depends(get_db)) -> list[EventTypeOut]:
    """Lista os tipos de evento observacional e o EPI associado."""
    rows = db.execute(
        text(
            """
            SELECT et.id, et.code, et.description, et.compliant,
                   e.code AS epi_code, e.name AS epi_name
            FROM event_types et
            JOIN epis e ON e.id = et.epi_id
            ORDER BY et.id
            """
        )
    ).all()
    return [
        EventTypeOut(
            id=r[0],
            code=r[1],
            description=r[2],
            compliant=r[3],
            epi_code=r[4],
            epi_name=r[5],
        )
        for r in rows
    ]


@app.get("/api/risk-areas", response_model=list[RiskAreaOut], tags=["mvp"])
def list_risk_areas(db: Session = Depends(get_db)) -> list[RiskAreaOut]:
    """Lista as áreas de risco configuradas (com a câmera associada)."""
    rows = db.execute(
        text(
            """
            SELECT ra.id, ra.camera_id, c.code AS camera_code, ra.name,
                   ra.x1, ra.y1, ra.x2, ra.y2, ra.active
            FROM risk_areas ra
            JOIN cameras c ON c.id = ra.camera_id
            ORDER BY ra.id
            """
        )
    ).all()
    return [
        RiskAreaOut(
            id=r[0],
            camera_id=r[1],
            camera_code=r[2],
            name=r[3],
            x1=r[4],
            y1=r[5],
            x2=r[6],
            y2=r[7],
            active=r[8],
        )
        for r in rows
    ]


# ============================================================
# Leitura de observações (dados reais do dashboard)
# ============================================================

_OBS_FROM = """
    FROM observations o
    JOIN observation_batches b ON b.id = o.batch_id
    JOIN cameras c ON c.id = b.camera_id
    JOIN event_types et ON et.id = o.event_type_id
    JOIN epis e ON e.id = et.epi_id
"""


def _observation_filters(
    camera_code: str | None,
    event_type_code: str | None,
    compliant: bool | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> tuple[str, dict]:
    """Monta WHERE + parâmetros compartilhados por lista e resumo."""
    if date_from is not None and date_to is not None and date_from >= date_to:
        raise HTTPException(
            status_code=422,
            detail="Período inválido: date_from deve ser anterior a date_to.",
        )
    clauses: list[str] = []
    params: dict = {}
    if camera_code:
        clauses.append("c.code = :camera_code")
        params["camera_code"] = camera_code
    if event_type_code:
        clauses.append("et.code = :event_type_code")
        params["event_type_code"] = event_type_code
    if compliant is not None:
        clauses.append("et.compliant = :compliant")
        params["compliant"] = compliant
    if date_from is not None:
        clauses.append("o.created_at >= :date_from")
        params["date_from"] = date_from
    if date_to is not None:
        # date_to é exclusivo (menor que).
        clauses.append("o.created_at < :date_to")
        params["date_to"] = date_to
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


@app.get(
    "/api/observations",
    response_model=ObservationListOut,
    tags=["mvp"],
)
def list_observations(
    camera_code: str | None = Query(default=None, max_length=50),
    event_type_code: str | None = Query(default=None, max_length=80),
    compliant: bool | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> ObservationListOut:
    """Lista observações persistidas (mais recentes primeiro).

    Filtros opcionais: câmera (code), tipo de evento (code), conformidade
    (event_types.compliant) e período (date_from inclusivo, date_to exclusivo).
    Observações são registros de visão computacional — person_ref é efêmero.
    """
    where, params = _observation_filters(
        camera_code, event_type_code, compliant, date_from, date_to
    )
    total = int(
        db.execute(
            text("SELECT COUNT(*) " + _OBS_FROM + where), params
        ).scalar_one()
    )
    rows = db.execute(
        text(
            """
            SELECT o.id, o.created_at, o.batch_id,
                   c.code, c.name,
                   et.code, et.description, et.compliant,
                   e.code, e.name,
                   o.context, o.person_ref,
                   o.event_confidence, o.conf_pessoa, o.conf_epi,
                   b.risk_area_id
            """
            + _OBS_FROM
            + where
            + " ORDER BY o.created_at DESC, o.id DESC"
            + " LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": limit, "offset": offset},
    ).all()
    return ObservationListOut(
        total=total,
        items=[
            ObservationOut(
                id=r[0],
                created_at=r[1],
                batch_id=r[2],
                camera_code=r[3],
                camera_name=r[4],
                event_code=r[5],
                event_description=r[6],
                compliant=r[7],
                epi_code=r[8],
                epi_name=r[9],
                context=r[10],
                person_ref=r[11],
                event_confidence=r[12],
                conf_pessoa=r[13],
                conf_epi=r[14],
                risk_area_id=r[15],
            )
            for r in rows
        ],
    )


@app.get(
    "/api/observations/summary",
    response_model=ObservationSummaryOut,
    tags=["mvp"],
)
def observations_summary(
    camera_code: str | None = Query(default=None, max_length=50),
    event_type_code: str | None = Query(default=None, max_length=80),
    compliant: bool | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    db: Session = Depends(get_db),
) -> ObservationSummaryOut:
    """Resumo das observações para os cartões e gráficos do dashboard.

    Taxa de conformidade = observações com event_types.compliant = true
    dividido pelo total de observações disponíveis (não é contagem de
    pessoas únicas).
    """
    where, params = _observation_filters(
        camera_code, event_type_code, compliant, date_from, date_to
    )

    counts = db.execute(
        text(
            """
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE et.compliant) AS compliant,
                   COUNT(*) FILTER (WHERE NOT et.compliant) AS non_compliant
            """
            + _OBS_FROM
            + where
        ),
        params,
    ).one()
    total, n_compliant, n_non_compliant = int(counts[0]), int(counts[1]), int(counts[2])

    by_day_rows = db.execute(
        text(
            """
            SELECT to_char(date_trunc('day', o.created_at), 'YYYY-MM-DD') AS day,
                   COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE et.compliant) AS compliant,
                   COUNT(*) FILTER (WHERE NOT et.compliant) AS non_compliant
            """
            + _OBS_FROM
            + where
            + " GROUP BY 1 ORDER BY 1"
        ),
        params,
    ).all()

    by_camera_rows = db.execute(
        text(
            """
            SELECT c.code, c.name,
                   COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE et.compliant) AS compliant,
                   COUNT(*) FILTER (WHERE NOT et.compliant) AS non_compliant
            """
            + _OBS_FROM
            + where
            + " GROUP BY c.code, c.name ORDER BY c.code"
        ),
        params,
    ).all()

    by_event_rows = db.execute(
        text(
            """
            SELECT et.code, et.description, et.compliant,
                   COUNT(*) AS total
            """
            + _OBS_FROM
            + where
            + " GROUP BY et.code, et.description, et.compliant ORDER BY et.code"
        ),
        params,
    ).all()

    return ObservationSummaryOut(
        total_observations=total,
        compliant_observations=n_compliant,
        non_compliant_observations=n_non_compliant,
        compliance_rate=(round(n_compliant / total, 4) if total > 0 else None),
        by_day=[
            SummaryByDayOut(
                date=r[0], total=int(r[1]), compliant=int(r[2]), non_compliant=int(r[3])
            )
            for r in by_day_rows
        ],
        by_camera=[
            SummaryByCameraOut(
                camera_code=r[0],
                camera_name=r[1],
                total=int(r[2]),
                compliant=int(r[3]),
                non_compliant=int(r[4]),
            )
            for r in by_camera_rows
        ],
        by_event_type=[
            SummaryByEventTypeOut(
                event_code=r[0],
                event_description=r[1],
                compliant=bool(r[2]),
                total=int(r[3]),
            )
            for r in by_event_rows
        ],
    )


# ============================================================
# Ingestão observacional (única escrita do MVP)
# ============================================================


@app.post(
    "/api/observations/ingest",
    response_model=IngestBatchOut,
    status_code=201,
    tags=["ingest"],
)
def ingest_observations(
    payload: IngestBatchIn, db: Session = Depends(get_db)
) -> IngestBatchOut:
    """Ingere 1 lote observacional (1 on_detect_all -> 1 batch + 0..N obs).

    Transação única: qualquer falha (câmera/evento/validação) faz rollback
    total — nunca deixa batch parcial. Eventos observacionais NÃO passam
    pela State Machine.
    """
    batch_id, created, duplicate, obs_ids = ingest_batch(db, payload)
    return IngestBatchOut(
        batch_id=batch_id,
        observations_created=created,
        duplicate=duplicate,
        observation_ids=obs_ids,
    )


# ============================================================
# Image evidence (persistência em disco + registro no banco)
# ============================================================

@app.post(
    "/api/images",
    response_model=ImageEvidenceOut,
    response_model_exclude={"image_path"},
    status_code=201,
    tags=["image_evidence"],
)
async def store_image_evidence(
    image: UploadFile = File(...),
    occurrence_id: int = Form(...),
    camera_code: str = Form(...),
    db: Session = Depends(get_db),
) -> ImageEvidenceOut:
    """
    Recebe uma imagem (multipart) e registra a evidência.

    O conteúdo é validado e salvo em data/images (pasta raiz do projeto).
    O caminho e metadados são persistidos em `image_evidence`, vinculados
    a `observations.id` através de `occurrence_id`.

    Parâmetros (multipart/form-data):
      - image: arquivo de imagem (obrigatório)
      - occurrence_id: id da observação (obrigatório)
      - camera_code: código lógico da câmera (obrigatório)
    """
    if occurrence_id is None:
        raise HTTPException(
            status_code=422,
            detail="occurrence_id é obrigatório para associar a evidência.",
        )
    if not camera_code or not camera_code.strip():
        raise HTTPException(
            status_code=422,
            detail="camera_code é obrigatório para identificar a câmera.",
        )

    try:
        file_bytes = await image.read()
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail="Não foi possível ler o arquivo enviado.",
        ) from exc

    try:
        record = save_image_evidence(
            file_bytes,
            camera_code=camera_code,
            occurrence_id=occurrence_id,
            original_filename=image.filename,
            mime_type=image.content_type,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    db_image = ImageEvidence(
        occurrence_id=occurrence_id,
        camera_code=camera_code,
        mime_type=record["mime_type"],
        file_name=record["file_name"],
        sha256=record["sha256"],
        image_path=record["image_path"],
        created_at=datetime.now(timezone.utc),
    )
    db.add(db_image)
    db.commit()
    db.refresh(db_image)

    return file_record_to_dict(db_image)


@app.get(
    "/api/images/by-occurrence/{occurrence_id}",
    response_model=ImageEvidenceListOut,
    response_model_exclude={"items": {"__all__": {"image_path"}}},
    tags=["image_evidence"],
)
def list_images_by_occurrence(
    occurrence_id: int, db: Session = Depends(get_db)
) -> ImageEvidenceListOut:
    """Lista as evidências vinculadas a uma ocorrência persistida.

    `occurrence_id` é `observations.id` (FK de `image_evidence.occurrence_id`).
    Ocorrência válida sem imagens -> lista vazia. Ocorrência inexistente -> 404
    (distinto de "sem evidências").
    """
    if db.get(Observation, occurrence_id) is None:
        raise HTTPException(status_code=404, detail="Ocorrência não encontrada.")
    rows = (
        db.execute(
            select(ImageEvidence)
            .where(ImageEvidence.occurrence_id == occurrence_id)
            .order_by(ImageEvidence.id.asc())
        )
        .scalars()
        .all()
    )
    items = [file_record_to_dict(r) for r in rows]
    return ImageEvidenceListOut(total=len(items), items=items)


@app.get(
    "/api/images/{image_id}",
    response_model=ImageEvidenceOut,
    response_model_exclude={"image_path"},
    tags=["image_evidence"],
)
def get_image_evidence(image_id: int, db: Session = Depends(get_db)) -> ImageEvidenceOut:
    """Retorna as metadados de uma evidência de imagem."""
    row = db.get(ImageEvidence, image_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Evidência de imagem não encontrada.")
    return file_record_to_dict(row)


@app.get(
    "/api/images/{image_id}/content",
    tags=["image_evidence"],
)
def get_image_evidence_content(
    image_id: int, db: Session = Depends(get_db)
) -> StreamingResponse:
    """Recupera os bytes da imagem de uma evidência (streaming).

    O caminho vem SEMPRE do registro do banco (nunca de input do cliente) e é
    confinado ao diretório autorizado `data/images`. Arquivo ausente/ilegível
    -> 404/500 sem revelar caminhos internos.
    """
    row = db.get(ImageEvidence, image_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Evidência de imagem não encontrada.")

    allowed_dir = get_image_dir().resolve()
    resolved = decode_image_path(row.image_path)
    try:
        resolved.relative_to(allowed_dir)
    except ValueError as exc:
        raise HTTPException(
            status_code=404, detail="Arquivo da evidência fora do diretório autorizado."
        ) from exc
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="Arquivo da evidência não encontrado.")

    mime = (row.mime_type or "").strip().lower().split(";")[0].strip()
    if mime not in {
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/gif",
        "image/bmp",
        "image/x-tiff",
        "image/tiff",
    }:
        mime = "application/octet-stream"

    def _chunks(chunk_size: int = 65536):
        try:
            with resolved.open("rb") as fh:
                while True:
                    data = fh.read(chunk_size)
                    if not data:
                        break
                    yield data
        except OSError as exc:
            raise HTTPException(
                status_code=500, detail="Falha ao ler o arquivo da evidência."
            ) from exc

    return StreamingResponse(
        _chunks(),
        media_type=mime,
        headers={"Content-Length": str(resolved.stat().st_size)},
    )
