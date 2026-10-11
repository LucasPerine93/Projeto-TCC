"""Hook Lucas -> MVP (Etapa 2): integracao separada do detector real.

Importado pelo detector do Lucas com chamada minima em
`operario_detectado()`. Nao reimplementa geometria, associacao, faixas
corporais ou area de risco: encaminha a lista de Operario JA calculada
por `organizar_dado()` para:

    lucas_adapter.adapt_lucas_operarios()  (veredicto -> ObservationEvent)
      -> write_observation()               (debounce + EventLog JSONL)
      -> DetectorIngestBridge.submit()     (fila limitada + worker, HTTP)

Protecoes do callback (Etapa 2, secao 3):
  - NENHUMA requisicao HTTP sincrona aqui (so submit nao-bloqueante).
  - NENHUM acesso a banco aqui.
  - Toda excecao capturada, contada e registrada em `erros`; NUNCA
    sobe para o detector (a camera continua processando).
  - Fila cheia -> ciclo descartado com contador `descartados`.
  - Sem workers/filas duplicados: bridge criado 1x via `configurar()`.

Maquina de estados de MONTAGEM: nunca acionada aqui. Este modulo nao
importa state_machine, event_ingest nem vision_bridge (guarda testada).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

AQUI = Path(__file__).resolve().parent
for _pasta in (AQUI, AQUI.parent / "event_arch"):
    _s = str(_pasta)
    if _s not in sys.path:
        sys.path.insert(0, _s)

from config import DEFAULT_CAMERA_ID  # noqa: E402
from detector_bridge import DetectorIngestBridge  # noqa: E402
from event_debounce import EventDebounce  # noqa: E402
from lucas_adapter import adapt_lucas_operarios  # noqa: E402
from observation import write_observation  # noqa: E402
from risk_area_mapper import map_box_canvas_to_frame  # noqa: E402

_log = None
_debounce = None
_ocorrencia = None
_ponte: Optional[DetectorIngestBridge] = None
_camera_id: str = DEFAULT_CAMERA_ID
_area_frame: Optional[Dict[str, float]] = None
erros: List[str] = []
descartados: int = 0
ciclos: int = 0


def _normalizar_area(area) -> Optional[Dict[str, float]]:
    """Normaliza box para dict {x1,y1,x2,y2} em floats do frame.

    Aceita dict, lista/tupla [x1,y1,x2,y2] (formato servidor.box_risco
    do Lucas) ou None. Invalido -> None (no_area explicito, sem inventar).
    """
    if area is None:
        return None
    if isinstance(area, dict):
        try:
            vals = [float(area[k]) for k in ("x1", "y1", "x2", "y2")]
        except (KeyError, TypeError, ValueError):
            return None
    elif isinstance(area, (list, tuple)) and len(area) == 4:
        try:
            vals = [float(v) for v in area]
        except (TypeError, ValueError):
            return None
    else:
        return None
    x1, y1, x2, y2 = vals
    return {"x1": x1, "y1": y1, "x2": x2, "y2": y2}


def configurar(
    *,
    log=None,
    debounce=None,
    ponte: Optional[DetectorIngestBridge] = None,
    camera_id: Optional[str] = None,
    risk_area: Optional[Dict[str, float]] = None,
    risk_area_canvas=None,
    occurrence=None,
) -> Dict[str, Any]:
    """Configura o hook 1x na inicializacao (testes usam resetar)."""
    global _log, _debounce, _ponte, _camera_id, _area_frame, _ocorrencia
    _log = log
    _debounce = debounce if debounce is not None else EventDebounce()
    _ponte = ponte
    if camera_id:
        _camera_id = camera_id
    if risk_area is not None:
        _area_frame = _normalizar_area(risk_area)
    elif risk_area_canvas is not None:
        try:
            _area_frame = map_box_canvas_to_frame(risk_area_canvas)
        except ValueError as exc:
            erros.append(f"risk_area_canvas invalida: {exc!r}")
            _area_frame = None
    _ocorrencia = occurrence
    return estado()


def definir_area_canvas(box_canvas) -> Optional[Dict[str, float]]:
    """Atualiza a area a partir do canvas do Lucas (mesma da avaliacao)."""
    global _area_frame
    try:
        _area_frame = map_box_canvas_to_frame(box_canvas)
    except ValueError as exc:
        erros.append(f"definir_area_canvas invalida: {exc!r}")
        _area_frame = None
    return _area_frame


def resetar() -> None:
    """Limpa o estado global (uso em testes). Nao remove arquivos."""
    global _log, _debounce, _ocorrencia, _ponte, _camera_id, _area_frame
    global erros, descartados, ciclos
    if _ponte is not None:
        try:
            _ponte.close(timeout=2.0)
        except Exception:  # noqa: BLE001 - reset nunca pode falhar
            pass
    _log, _debounce, _ocorrencia, _ponte = None, None, None, None
    _camera_id = DEFAULT_CAMERA_ID
    _area_frame = None
    erros, descartados, ciclos = [], 0, 0


def estado() -> Dict[str, Any]:
    return {
        "camera_id": _camera_id,
        "risk_area": dict(_area_frame) if _area_frame else None,
        "ponte_stats": _ponte.stats if _ponte is not None else None,
        "erros": len(erros),
        "descartados": descartados,
        "ciclos": ciclos,
    }


def processar_operarios(
    operarios,
    *,
    specs_frame: Optional[Dict] = None,
    box_risco=None,
    area_ativa: Optional[bool] = None,
    received_at=None,
) -> Dict[str, Any]:
    """Encaminha Operario do Lucas ao MVP. NUNCA levanta excecao.

    Retorna {"eventos": n_escritos, "descartado_bridge": bool, "ok": bool}.
    """
    global descartados, ciclos
    ciclos += 1
    resumo: Dict[str, Any] = {"eventos": 0, "descartado_bridge": False, "ok": True}
    try:
        area = _normalizar_area(box_risco) if box_risco is not None else _area_frame
        if area_ativa is False:
            area = None
        events, _diag = adapt_lucas_operarios(
            operarios or [], camera_id=_camera_id, risk_area=area)
        if _ocorrencia is not None:
            events = _aplicar_ocorrencia(events)
        escritos = []
        if _log is not None:
            for ev in events:
                if write_observation(ev, _log, _debounce) == "written":
                    escritos.append(ev)
        else:
            escritos = list(events)
        resumo["eventos"] = len(escritos)
        if _ponte is not None and escritos:
            bruto = dict(specs_frame) if isinstance(specs_frame, dict) else {}
            aceito = _ponte.submit(
                bruto, escritos, risk_area=area,
                received_at=received_at or datetime.now(timezone.utc),
            )
            if not aceito:
                descartados += 1
                resumo["descartado_bridge"] = True
                erros.append("fila da ponte cheia: ciclo descartado (contabilizado)")
        return resumo
    except Exception as exc:  # noqa: BLE001 - callback nunca pode cair
        erros.append(f"processar_operarios: {exc!r}")
        resumo["ok"] = False
        return resumo


def _aplicar_ocorrencia(events):
    """Filtro temporal sobre o veredicto do adapter (sem geometria)."""
    if _ocorrencia is None:
        return events
    try:
        from association import (  # noqa: PLC0415
            STATUS_ASSOCIADO,
            STATUS_AUSENTE,
            STATUS_INDETERMINADO,
            EpiMatch,
            PersonAssociation,
        )
        from context import CONTEXT_INSIDE  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        erros.append(f"ocorrencia indisponivel: {exc!r}")
        return events
    por_pessoa: Dict[int, Dict[str, Any]] = {}
    for ev in events:
        md = ev.metadata or {}
        ref = md.get("person_ref", 0)
        slot = por_pessoa.setdefault(ref, {"bbox": md.get("bbox"),
                                           "conf": md.get("conf_pessoa"),
                                           "cam": md.get("camera_id"),
                                           "helmet": None, "vest": None})
        if ev.event in ("pessoa_com_capacete", "pessoa_sem_capacete"):
            slot["helmet"] = (STATUS_ASSOCIADO if ev.event == "pessoa_com_capacete"
                              else STATUS_AUSENTE, md.get("conf_epi"),
                              md.get("bbox_epi"))
        elif ev.event in ("pessoa_com_colete", "pessoa_sem_colete"):
            slot["vest"] = (STATUS_ASSOCIADO if ev.event == "pessoa_com_colete"
                            else STATUS_AUSENTE, md.get("conf_epi"),
                            md.get("bbox_epi"))
    assocs = []
    for ref, slot in por_pessoa.items():
        try:
            bbox = tuple(float(v) for v in slot["bbox"])
        except (TypeError, ValueError):
            continue

        def _match(dado):
            if dado is None:
                return None
            st, cf, bb = dado
            try:
                bbt = tuple(float(v) for v in bb) if bb else None
            except (TypeError, ValueError):
                bbt = None
            return EpiMatch(st, cf, bbt)

        mh, mv = _match(slot["helmet"]), _match(slot["vest"])
        if mh is None and mv is None:
            continue
        assocs.append(PersonAssociation(
            person_ref=ref, bbox=bbox, confidence=slot["conf"] or 0.0,
            camera_id=slot["cam"],
            helmet=mh or EpiMatch(STATUS_INDETERMINADO),
            vest=mv or EpiMatch(STATUS_INDETERMINADO)))
    if not assocs:
        _ocorrencia.update(_camera_id, [], {})
        return []
    contextos = {a.person_ref: CONTEXT_INSIDE for a in assocs}
    return _ocorrencia.update(_camera_id, assocs, contextos)

    return {
        "camera_id": _camera_id,
        "risk_area": dict(_area_frame) if _area_frame else None,
        "ponte_stats": _ponte.stats if _ponte is not None else None,
        "erros": len(erros),
        "descartados": descartados,
        "ciclos": ciclos,
    }
