"""Camada temporal de ocorrências de conformidade (OPCIONAL, reutilizável).

Diferente do EventDebounce (rate-limit por janela), ESTA camada CONFIRMA
temporalmente antes de emitir — e distingue evidência de conclusão:

    detecção individual        -> evidência em UM frame (association/context)
    observação de conformidade -> evento por frame (event_generator, inalterado)
    possível não conformidade  -> sequência de evidências "ausente" ainda
                                  NÃO emite (contador de ausências)
    ocorrência confirmada      -> emitida UMA vez ao atingir confirm_frames
    persistência               -> frames seguintes NÃO geram novo registro
    recuperação                -> emitida ao atingir resolve_frames de
                                  evidências "presente" (fecha a ocorrência)
    inconclusivo (oclusão /
    baixa confiança)           -> evidência INDETERMINADO: nem confirma nem
                                  resolvida; NUNCA conta como ausência

Regras e limitações (documentadas, não estatisticamente validadas):
  - Estado por (camera_id, tipo de EPI): SEM identidade de pessoas —
    person_ref é índice efêmero do frame e NÃO é usado como chave.
  - Sem rastreamento: duas pessoas na mesma cena AGREGAM (regra
    conservadora ausente > indeterminado > presente).
  - Frames sem pessoa dentro reiniciam os contadores.
  - Parâmetros PROVISÓRIOS configuráveis por ambiente/assinatura:
    OCCURRENCE_CONFIRM_FRAMES (padrão 3), OCCURRENCE_RESOLVE_FRAMES (2).
  - Determinístico: sem tempo de relógio, apenas contagem de frames.
"""
from pathlib import Path
import sys
from typing import Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from association import (  # noqa: E402
    STATUS_ASSOCIADO,
    STATUS_AUSENTE,
    STATUS_INDETERMINADO,
    PersonAssociation,
)
from config import (  # noqa: E402
    OCCURRENCE_CONFIRM_FRAMES,
    OCCURRENCE_RESOLVE_FRAMES,
)
from context import CONTEXT_INSIDE  # noqa: E402
from observation import ObservationEvent  # noqa: E402

# Evidências por frame e severidade (maior vence na agregação).
EVID_NONE = "none"                 # nenhuma pessoa dentro da área
EVID_PRESENT = "present"           # EPI associado (conformidade)
EVID_INCONCLUSIVE = "inconclusive"  # indeterminado/oclusão — NÃO é ausência
EVID_ABSENT = "absent"             # ausência observada neste frame

_SEVERITY = {EVID_NONE: 0, EVID_PRESENT: 1, EVID_INCONCLUSIVE: 2, EVID_ABSENT: 3}

# (tipo) -> (evento_abertura/sem, evento_resolução/com, palavra)
_RULES: Dict[str, Tuple[str, str, str]] = {
    "helmet": ("pessoa_sem_capacete", "pessoa_com_capacete", "capacete"),
    "vest": ("pessoa_sem_colete", "pessoa_com_colete", "colete"),
}


def evidencias_frame(
    associations: List[PersonAssociation],
    contexts: Dict[int, str],
) -> Dict[str, Tuple[str, Optional[PersonAssociation]]]:
    """Agrega as evidências de UM frame por tipo de EPI (somente 'inside').

    Severidade por tipo: ausente > indeterminado > presente > nenhum.
    Retorna {kind: (evidencia, assoc_fonte)} — assoc_fonte é a pessoa que
    originou a pior evidência (para montar metadados no momento da emissão).
    """
    out: Dict[str, Tuple[str, Optional[PersonAssociation]]] = {
        kind: (EVID_NONE, None) for kind in _RULES
    }
    for assoc in associations:
        if contexts.get(assoc.person_ref) != CONTEXT_INSIDE:
            continue
        for kind in _RULES:
            match = getattr(assoc, kind)
            if match.status == STATUS_AUSENTE:
                ev = EVID_ABSENT
            elif match.status == STATUS_ASSOCIADO:
                ev = EVID_PRESENT
            else:  # STATUS_INDETERMINADO (oclusão/empate/baixa qualidade)
                ev = EVID_INCONCLUSIVE
            if _SEVERITY[ev] > _SEVERITY[out[kind][0]]:
                out[kind] = (ev, assoc)
    return out


class _State:
    __slots__ = ("absence_streak", "presence_streak", "active")

    def __init__(self) -> None:
        self.absence_streak = 0
        self.presence_streak = 0
        self.active = False  # ocorrência aberta (emito só na abertura)


class OccurrenceTracker:
    """Confirmação temporal por frames consecutivos, por (camera, EPI)."""

    def __init__(
        self,
        confirm_frames: Optional[int] = None,
        resolve_frames: Optional[int] = None,
    ) -> None:
        confirm = confirm_frames if confirm_frames is not None else OCCURRENCE_CONFIRM_FRAMES
        resolve = resolve_frames if resolve_frames is not None else OCCURRENCE_RESOLVE_FRAMES
        if confirm < 1 or resolve < 1:
            raise ValueError("confirm_frames/resolve_frames devem ser >= 1.")
        self.confirm_frames = int(confirm)
        self.resolve_frames = int(resolve)
        self._states: Dict[Tuple[str, str], _State] = {}
        # Contadores observáveis para testes/monitoração.
        self.opened = 0
        self.resolved = 0
        self.suppressed = 0      # frames ativos sem nova emissão
        self.inconclusive = 0    # frames com evidência inconclusiva

    def state_of(self, camera_id: str, kind: str) -> Optional[str]:
        """Estado atual ('clear'/'active'/None sem histórico) — só leitura."""
        st = self._states.get((camera_id, kind))
        if st is None:
            return None
        return "active" if st.active else "clear"

    def update(
        self,
        camera_id: str,
        associations: List[PersonAssociation],
        contexts: Dict[int, str],
    ) -> List[ObservationEvent]:
        """Avalia UM frame e retorna APENAS as transições a emitir."""
        evidences = evidencias_frame(associations, contexts)
        events: List[ObservationEvent] = []
        for kind, (evidence, source) in evidences.items():
            key = (camera_id, kind)
            st = self._states.setdefault(key, _State())
            ev_sem, ev_com, word = _RULES[kind]

            if evidence == EVID_INCONCLUSIVE:
                # Oclusão/baixa confiança: pausa (não confirma, não resolve).
                self.inconclusive += 1
                continue

            if evidence == EVID_NONE:
                # Sem pessoa dentro: nenhuma evidência — zera contadores.
                st.absence_streak = 0
                st.presence_streak = 0
                continue

            if evidence == EVID_ABSENT:
                st.presence_streak = 0
                if st.active:
                    self.suppressed += 1
                    continue
                st.absence_streak += 1
                if st.absence_streak >= self.confirm_frames:
                    st.absence_streak = 0
                    st.active = True
                    self.opened += 1
                    events.append(self._event(ev_sem, word, source))
                continue

            # evidence == EVID_PRESENT
            st.absence_streak = 0
            if not st.active:
                st.presence_streak = 0
                continue
            st.presence_streak += 1
            if st.presence_streak >= self.resolve_frames:
                st.presence_streak = 0
                st.absence_streak = 0
                st.active = False
                self.resolved += 1
                events.append(self._event(ev_com, word, source))
        return events

    @staticmethod
    def _event(
        event_code: str,
        word: str,
        source: Optional[PersonAssociation],
    ) -> ObservationEvent:
        """Monta ObservationEvent com o MESMO contrato do event_generator."""
        assoc = source
        person_ref = assoc.person_ref if assoc else 0
        bbox = list(assoc.bbox) if assoc else [0.0, 0.0, 0.0, 0.0]
        conf_pessoa = assoc.confidence if assoc else 0.0
        camera_id = assoc.camera_id if assoc else None
        if event_code.startswith("pessoa_com_"):
            kind_attr = "helmet" if word == "capacete" else "vest"
            match = getattr(assoc, kind_attr) if assoc else None
            conf_epi = match.confidence if match else None
            bbox_epi = list(match.bbox) if match and match.bbox else None
            label = word  # detecção bruta subjacente ("helmet"/"vest")
            confidence = min(conf_pessoa, conf_epi) if conf_epi is not None else conf_pessoa
            message = (
                f"Pessoa {person_ref}: {word} associado dentro da área de risco "
                f"(recuperação confirmada)."
            )
        else:
            conf_epi = None
            bbox_epi = None
            label = "person"
            confidence = conf_pessoa
            message = (
                f"Pessoa {person_ref}: {word} não associado dentro da área de risco "
                f"(ocorrência confirmada)."
            )
        return ObservationEvent(
            event=event_code,
            message=message,
            metadata={
                "label": label,
                "confidence": confidence,
                "bbox": bbox,
                "camera_id": camera_id,
                "person_ref": person_ref,  # efêmero do frame que EMITIU
                "context": CONTEXT_INSIDE,
                "conf_pessoa": conf_pessoa,
                "conf_epi": conf_epi,
                "bbox_epi": bbox_epi,
            },
        )
