# jt/state.py
import json
import os
import time
from pathlib import Path


def _default_state_file() -> Path:
    """Pick the state file path.

    Prefer ``$JT_STATE_FILE`` (explicit override), then a per-user runtime
    directory (``$XDG_RUNTIME_DIR``), and finally fall back to ``/tmp``.

    The runtime dir is private to the user (mode 0700) on systemd systems,
    which keeps agent output tails away from other users on shared boxes.
    """
    override = os.environ.get('JT_STATE_FILE')
    if override:
        return Path(override)
    runtime = os.environ.get('XDG_RUNTIME_DIR')
    if runtime:
        return Path(runtime) / 'jt-state.json'
    return Path('/tmp/jt-state.json')


STATE_FILE = _default_state_file()


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
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix('.tmp')
    # Write with restrictive mode before rename so the file is never
    # world-readable, even briefly. output_tail can contain agent stdout
    # which may include paths or secrets.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.replace(tmp, STATE_FILE)
