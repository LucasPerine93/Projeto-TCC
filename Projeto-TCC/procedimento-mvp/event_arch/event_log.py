import json
from datetime import datetime, timezone
from pathlib import Path


class EventLog:
    def __init__(self, path="procedure_events.jsonl"):
        self.path = Path(path)

    def write(self, result, source="system", metadata=None):
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "status": result.status,
            "event": result.event,
            "message": result.message,
            "previous_step": result.previous_step,
            "current_step": result.current_step,
        }
        if metadata:
            record["metadata"] = metadata
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record
