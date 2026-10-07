from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional


@dataclass
class ProcedureResult:
    status: str
    event: str
    message: str
    previous_step: int
    current_step: int


class ProcedureStateMachine:
    """Controla a ordem das etapas de um procedimento configurável."""

    def __init__(self, procedure: Dict):
        self.procedure = procedure
        self.steps: List[Dict] = procedure.get("steps", [])
        if not self.steps:
            raise ValueError("O procedimento precisa ter pelo menos uma etapa.")
        self.reset()

    def reset(self) -> ProcedureResult:
        self.current_step = 0
        self.started_at = datetime.now(timezone.utc).isoformat()
        return ProcedureResult(
            status="reset",
            event="reset_procedimento",
            message="Procedimento reiniciado.",
            previous_step=0,
            current_step=0,
        )

    @property
    def completed(self) -> bool:
        return self.current_step >= len(self.steps)

    @property
    def current_step_data(self) -> Optional[Dict]:
        if self.completed:
            return None
        return self.steps[self.current_step]

    def expected_event(self) -> Optional[str]:
        step = self.current_step_data
        return step.get("event") if step else None

    def process_event(self, event: str) -> ProcedureResult:
        previous = self.current_step

        if self.completed:
            return ProcedureResult(
                status="completed",
                event=event,
                message="O procedimento já foi concluído. Reinicie para uma nova montagem.",
                previous_step=previous,
                current_step=self.current_step,
            )

        expected = self.current_step_data.get("event")
        expected_name = self.current_step_data.get("name", expected)

        if event == expected:
            self.current_step += 1
            if self.completed:
                message = "Procedimento concluído com sucesso."
                status = "completed"
            else:
                next_name = self.current_step_data.get("name")
                message = f"Etapa confirmada: {expected_name}. Próxima: {next_name}."
                status = "advanced"

            return ProcedureResult(status, event, message, previous, self.current_step)

        future_index = next(
            (i for i in range(self.current_step + 1, len(self.steps))
             if self.steps[i].get("event") == event),
            None,
        )

        if future_index is not None:
            message = (
                f"Erro de sequência: '{self.steps[future_index].get('name', event)}' "
                f"detectado antes de '{expected_name}'."
            )
        else:
            message = f"Evento '{event}' não é esperado nesta etapa ({expected_name})."

        return ProcedureResult(
            status="error",
            event=event,
            message=message,
            previous_step=previous,
            current_step=self.current_step,
        )

    def status(self) -> Dict:
        return {
            "procedure": self.procedure.get("name", "Procedimento"),
            "current_step": self.current_step,
            "total_steps": len(self.steps),
            "completed": self.completed,
            "expected_event": self.expected_event(),
            "expected_step": self.current_step_data.get("name") if self.current_step_data else None,
            "started_at": self.started_at,
        }
