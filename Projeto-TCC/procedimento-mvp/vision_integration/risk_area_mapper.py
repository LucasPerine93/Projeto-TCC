"""Mapeamento explícito canvas (WebUI do Lucas) -> frame (modelo/pipeline).

Contexto (Etapa 1, somente análise + adaptação):
  - O Lucas desenha a área de risco num <canvas> de 720x460
    (Projeto-TCC-main(4).../assets/app.js + index.html).
  - O detector avalia em pixels do FRAME (Camera 720x480 em
    python/detector.py).
  - O MVP assumia "coordenadas já em pixels do frame"
    (vision_integration/config.py).

Este módulo NÃO altera a referência geométrica do Lucas: apenas aplica
escala linear separada por eixo (sx = frame_w / canvas_w,
sy = frame_h / canvas_h). Sem arredondamento implícito além de float().
"""

from typing import Dict, Mapping, Optional, Sequence, Tuple

DEFAULT_CANVAS_SIZE: Tuple[float, float] = (720.0, 460.0)
DEFAULT_FRAME_SIZE: Tuple[float, float] = (720.0, 480.0)


def _num(value) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):  # NaN/Inf
        return None
    return out


def _size(size: Sequence, nome: str) -> Tuple[float, float]:
    if not isinstance(size, (list, tuple)) or len(size) != 2:
        raise ValueError(f"{nome} deve ser (largura, altura).")
    larg = _num(size[0])
    alt = _num(size[1])
    if larg is None or alt is None or larg <= 0 or alt <= 0:
        raise ValueError(f"{nome} inválido: {size!r}.")
    return (larg, alt)


def map_point_canvas_to_frame(
    x,
    y,
    canvas_size: Sequence = DEFAULT_CANVAS_SIZE,
    frame_size: Sequence = DEFAULT_FRAME_SIZE,
) -> Tuple[float, float]:
    """Converte UM ponto do canvas para o frame (escala linear por eixo)."""
    fx = _num(x)
    fy = _num(y)
    if fx is None or fy is None:
        raise ValueError(f"ponto inválido: {(x, y)!r}.")
    larg_c, alt_c = _size(canvas_size, "canvas_size")
    larg_f, alt_f = _size(frame_size, "frame_size")
    return (fx * larg_f / larg_c, fy * alt_f / alt_c)


def map_box_canvas_to_frame(
    box,
    canvas_size: Sequence = DEFAULT_CANVAS_SIZE,
    frame_size: Sequence = DEFAULT_FRAME_SIZE,
) -> Dict[str, float]:
    """Converte box {x1,y1,x2,y2} (ou [x1,y1,x2,y2]) do canvas -> frame.

    Normaliza com min/max (aceita cantos invertidos, como o JS que usa
    Math.min/Math.max). Retorna dict {x1,y1,x2,y2} em floats do frame.
    Levanta ValueError em entrada inválida (nunca inventa coordenadas).
    """
    if isinstance(box, Mapping):
        try:
            raw = (box["x1"], box["y1"], box["x2"], box["y2"])
        except KeyError as exc:
            raise ValueError(f"box sem chave {exc} : {box!r}.") from exc
    elif isinstance(box, (list, tuple)) and len(box) == 4:
        raw = tuple(box)
    else:
        raise ValueError(f"box inválida (dict ou lista-4 esperados): {box!r}.")

    vals = [_num(v) for v in raw]
    if any(v is None for v in vals):
        raise ValueError(f"box com coordenada não numérica: {box!r}.")
    larg_c, alt_c = _size(canvas_size, "canvas_size")
    larg_f, alt_f = _size(frame_size, "frame_size")
    sx = larg_f / larg_c
    sy = alt_f / alt_c
    x1, y1, x2, y2 = vals
    fx1, fx2 = sorted((x1 * sx, x2 * sx))
    fy1, fy2 = sorted((y1 * sy, y2 * sy))
    return {"x1": fx1, "y1": fy1, "x2": fx2, "y2": fy2}
