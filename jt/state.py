# jt/state.py
import json
import time
from pathlib import Path

STATE_FILE = Path('/tmp/jt-state.json')


def read_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_state(node: str, sessions: dict) -> None:
    data = {
        'node': node,
        'updated_at': int(time.time()),
        'sessions': sessions,
    }
    tmp = STATE_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2))
    tmp.rename(STATE_FILE)
