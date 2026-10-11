"""
Persistência de evidências de imagem independente de alto nível.

Este módulo não depende de FastAPI. Ele aceita bytes embutidos e
armazena em um diretório portátil (`data/images`), calcula sha256 e
retorna o caminho seguro para posterior cadastro no banco.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.config import get_settings

# Mapeamento MIME -> extensão de arquivo
_MIME_TO_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/x-tiff": ".tif",
    "image/tiff": ".tif",
}

# Extensões aceitáveis para evitar salvamento de arquivos não-IMAGE.
_ACCEPTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}

# Caracteres proibidos em nomes de arquivo, preservando UUID e timestamp.
_SAFE_NAME_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789_.-"


def _project_root() -> Path:
    """Raiz do 'Projeto-TCC' e fallback para TCC_MVP_ROOT."""
    env_root = os.getenv("TCC_MVP_ROOT")
    if env_root:
        return Path(env_root).resolve()
    return Path(__file__).resolve().parents[3]


def get_image_dir() -> Path:
    """Retorna e garante a existência do diretório de imagens persistidas."""
    root = _project_root()
    image_dir = root / "data" / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    return image_dir


def compute_sha256(bytes_data: bytes) -> str:
    """Retorna o sha256 de um bloco de bytes."""
    return hashlib.sha256(bytes_data).hexdigest()


def _normalize_mime(mime_type: Optional[str], default_mime: Optional[str] = None) -> str:
    """
    Normaliza um MIME para 'image/*' ou levanta ValueError.
    Se mime_type for None, usa o default.
    """
    if mime_type:
        mime_type = mime_type.strip().lower().split(";")[0].strip()
    if not mime_type:
        mime_type = default_mime or "image/jpeg"

    if not mime_type.startswith("image/"):
        raise ValueError(f"MIME '{mime_type}' não é uma imagem.")
    return mime_type



def _detect_signature(data: bytes) -> Optional[str]:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "gif"
    if data.startswith(b"BM"):
        return "bmp"
    if data.startswith(b"II*\x00") or data.startswith(b"MM\x00*"):
        return "tif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _detect_extension(
    data: bytes,
    *,
    filename: Optional[str] = None,
    mime_type: Optional[str] = None,
) -> Optional[str]:
    """
    Tentativa de detecção conservadora de extensão.
    Retorna a extensão com ponto, ou None quando não puder confirmar.
    """
    # 1) extensão explícita no filename
    if filename:
        suffix = Path(filename).suffix.lower()
        if suffix in _ACCEPTED_EXTENSIONS:
            return suffix

    # 2) MIME explícito
    if mime_type:
        mime_lower = mime_type.strip().lower().split(";")[0].strip()
        if mime_lower in _MIME_TO_EXT:
            return _MIME_TO_EXT[mime_lower]

    # 3) verificação de assinatura de cabeçalho
    if data:
        detected = _detect_signature(data)
        if detected:
            return "." + detected

    # 4) fallback: só aceita extensão padrão fortemente mapeado
    if mime_type:
        mime_lower = mime_type.strip().lower().split(";")[0].strip()
        return _MIME_TO_EXT.get(mime_lower)

    return None


def save_image_evidence(
    bytes_data: bytes,
    *,
    camera_code: str,
    occurrence_id: Optional[int] = None,
    original_filename: Optional[str] = None,
    mime_type: Optional[str] = None,
) -> dict:
    """
    Valida, salva e prepara metadados de uma evidência de imagem.

    Retorna um dicionário de read-only para cadastro no banco:
      {
        "camera_code": str,
        "occurrence_id": Optional[int],
        "file_name": str,
        "sha256": str,
        "mime_type": str,
        "image_path": str,
      }
    """
    if not bytes_data:
        raise ValueError("Não foi enviado nenhum dado de imagem.")

    if not camera_code:
        raise ValueError("camera_code é obrigatório.")

    # Detecção de extensão segura
    ext = _detect_extension(
        bytes_data,
        filename=original_filename,
        mime_type=mime_type,
    )
    if ext is None:
        raise ValueError("Arquivo não identificado como imagem válida.")

    # MIME final
    mime = _normalize_mime(mime_type, default_mime=ext and _MIME_TO_EXT.get(ext))

    # Nome seguro, independente do nome original do cliente
    created = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    random_hex = secrets.token_hex(8)
    sha_preview = compute_sha256(bytes_data)[:12]
    file_name = f"IMG_{created}_{random_hex}_{sha_preview}{ext}"

    image_dir = get_image_dir()
    file_path = image_dir / file_name
    file_path.write_bytes(bytes_data)

    return {
        "camera_code": camera_code,
        "occurrence_id": occurrence_id,
        "file_name": file_name,
        "sha256": compute_sha256(bytes_data),
        "mime_type": mime,
        "image_path": str(file_path),
    }


def file_record_to_dict(record) -> dict:
    """Converte um modelo ImageEvidence em dict de resposta.

    NÃO expõe `image_path` (caminho absoluto do backend): o cliente deve usar
    GET /api/images/{id}/content para recuperar os bytes.
    """
    return {
        "id": record.id,
        "occurrence_id": record.occurrence_id,
        "camera_code": record.camera_code,
        "mime_type": record.mime_type,
        "file_name": record.file_name,
        "sha256": record.sha256,
        "created_at": record.created_at,
    }


def decode_image_path(image_path: str) -> Path:
    """Resolver caminho relativo/ambos do storage."""
    return Path(image_path).expanduser().resolve()
