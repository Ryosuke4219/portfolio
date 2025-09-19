import json, time, os
from typing import Any, Dict

def _ensure_dir(path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)

def log_event(event_type: str, path: str, **fields: Dict[str, Any]) -> None:
    _ensure_dir(path)
    rec = {"ts": int(time.time() * 1000), "event": event_type}
    rec.update(fields)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
