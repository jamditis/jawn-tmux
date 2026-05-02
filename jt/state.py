# jt/state.py
import json
import os
import tempfile
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


def write_state(node: str, sessions: dict, last_error: dict | None = None) -> None:
    data = {
        'node': node,
        'updated_at': int(time.time()),
        'sessions': sessions,
    }
    if last_error is not None:
        data['last_error'] = last_error
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Use mkstemp to get a unique name with O_EXCL semantics: this defeats
    # the symlink-attack vector that exists when the state file lives in a
    # shared directory (the /tmp fallback, or any user-supplied
    # JT_STATE_FILE location).  mkstemp opens with mode 0600 by default.
    fd, tmp_path = tempfile.mkstemp(
        prefix='.jt-state-', suffix='.tmp',
        dir=str(STATE_FILE.parent),
    )
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2)
        # Belt-and-braces: enforce mode in case the platform's mkstemp
        # default isn't 0600 (it is on CPython, but be explicit).
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, STATE_FILE)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
