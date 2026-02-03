import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def _logs_dir() -> Path:
    base_dir = Path(__file__).resolve().parent
    logs_dir = base_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def _session_log_path(session_id: str) -> Path:
    safe_session = session_id.replace("/", "_").replace("\\", "_")
    return _logs_dir() / f"{safe_session}.json"


def load_session_records(session_id: str) -> List[Dict[str, Any]]:
    path = _session_log_path(session_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        return []
    return []


def append_session_record(session_id: str, record: Dict[str, Any]) -> None:
    path = _session_log_path(session_id)
    records = load_session_records(session_id)
    record_with_meta = {
        **record,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    records.append(record_with_meta)
    path.write_text(json.dumps(records, indent=2, ensure_ascii=True), encoding="utf-8")
