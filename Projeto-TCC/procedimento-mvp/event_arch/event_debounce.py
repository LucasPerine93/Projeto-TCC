"""Debounce de eventos: bloqueia repetições dentro do intervalo configurável.

Camada neutra entre o parser e a ingestão — FORA da ProcedureStateMachine
(a máquina de estados não conhece debounce) e sem vínculo com Arduino ou
câmera, reutilizável por qualquer fonte de eventos.

Identidade do evento: (evento, camera_id, person_ref).
  - CAPACETE na camera_1 repetido      -> bloqueado no intervalo.
  - CAPACETE na camera_1 vs camera_2   -> chaves diferentes, não bloqueia.
  - CAPACETE vs LUVA na mesma câmera   -> chaves diferentes, não bloqueia.
  - person_ref separa pessoas dentro do MESMO frame (índice efêmero, NÃO é
    identidade persistente nem tracking). Chamadas sem person_ref (fluxo
    procedural) usam None e mantêm o comportamento original.

Semântica: janela fixa — apenas eventos ACEITOS marcam o relógio da chave;
tentativas bloqueadas não estendem a janela.

O relógio é injetável (clock) para os testes simularem o tempo sem sleep().
"""
import time
from typing import Callable, Dict, Hashable, Optional, Tuple

# Intervalo PROVISÓRIO em segundos — apenas valor padrão para testes.
# Não é o valor definitivo do TCC; será definido em configuração depois.
DEFAULT_DEBOUNCE_INTERVAL = 1.0


class EventDebounce:
    """Impede que o mesmo evento se repita antes do intervalo configurado."""

    def __init__(
        self,
        interval: float = DEFAULT_DEBOUNCE_INTERVAL,
        clock: Callable[[], float] = time.monotonic,
    ):
        if interval < 0:
            raise ValueError("O intervalo do debounce não pode ser negativo.")
        self.interval = interval
        self._clock = clock
        self._ultimo: Dict[Hashable, float] = {}

    @staticmethod
    def chave_evento(
        event: str,
        camera_id: Optional[str] = None,
        person_ref: Optional[int] = None,
    ) -> Tuple[str, Optional[str], Optional[int]]:
        """Identidade do debounce: evento + câmera + slot efêmero do frame.

        person_ref (plano v3.4.2): índice de enumeração das pessoas DENTRO de
        um único frame — NÃO é identidade persistente e NÃO representa a
        mesma pessoa em frames diferentes. Sem person_ref -> None (compatível
        com o fluxo procedural existente).
        """
        return (event, camera_id, person_ref)

    def autorizar(
        self,
        event: str,
        camera_id: Optional[str] = None,
        person_ref: Optional[int] = None,
    ) -> bool:
        """True se o evento deve ser processado; False se é repetição."""
        agora = self._clock()
        chave = self.chave_evento(event, camera_id, person_ref)
        ultimo = self._ultimo.get(chave)
        if ultimo is not None and (agora - ultimo) < self.interval:
            return False
        self._ultimo[chave] = agora
        return True
