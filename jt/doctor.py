# jt/doctor.py
"""Health checks for jawn-tmux. Surfaced as `jt doctor`.

Each check returns ``(level, message)`` where ``level`` is ``ok``, ``warn``,
or ``fail``. The orchestrator runs them in order and reports a roll-up exit
code: 0 if no failures, 1 otherwise.
"""
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from jt import daemon, state

CheckResult = tuple[str, str]  # (level, message)
CheckFn = Callable[[], CheckResult]

LEVEL_GLYPHS = {'ok': 'OK', 'warn': 'WARN', 'fail': 'FAIL'}
STATE_STALE_AFTER = 30  # seconds; daemon polls every 2s, so 30s is comfortably stale


def _check_runtime_dir() -> CheckResult:
    runtime = os.environ.get('XDG_RUNTIME_DIR')
    if not runtime:
        return ('warn', '$XDG_RUNTIME_DIR not set; state file will fall back to /tmp')
    if not os.path.isdir(runtime):
        return ('fail', f'$XDG_RUNTIME_DIR={runtime} does not exist')
    return ('ok', f'using {runtime}')


def _alternate_state_paths() -> list[Path]:
    """Candidate state file paths besides the one currently configured.

    Helps diagnose the common systemd-user-service case where the daemon
    booted without ``XDG_RUNTIME_DIR`` and silently fell back to /tmp,
    while an interactive CLI session resolves it to ``$XDG_RUNTIME_DIR``.
    """
    configured = state.STATE_FILE
    alternates = [Path('/tmp/jt-state.json')]
    runtime = os.environ.get('XDG_RUNTIME_DIR')
    if runtime:
        alternates.append(Path(runtime) / 'jt-state.json')
    return [p for p in alternates if p != configured and p.exists()]


def _check_state_file_fresh() -> CheckResult:
    path = state.STATE_FILE
    if not path.exists():
        others = _alternate_state_paths()
        if others:
            other = others[0]
            return ('fail',
                    f'no state file at {path}, but a fresh one exists at {other} — '
                    f'the daemon and CLI disagree on $XDG_RUNTIME_DIR. '
                    f'Add `Environment=XDG_RUNTIME_DIR=/run/user/%U` to jtd.service '
                    f'and restart, or set JT_STATE_FILE in both environments.')
        return ('fail', f'no state file at {path}; daemon may not be running')
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        return ('fail', f'state file at {path} is unreadable: {e}')
    updated_at = data.get('updated_at')
    if not isinstance(updated_at, int):
        return ('fail', f'state file at {path} missing updated_at')
    age = int(time.time()) - updated_at
    if age > STATE_STALE_AFTER:
        return ('fail', f'state file is {age}s stale (threshold {STATE_STALE_AFTER}s); daemon stopped polling')
    return ('ok', f'state file fresh ({age}s old) at {path}')


def _check_tmux() -> CheckResult:
    binary = shutil.which('tmux')
    if not binary:
        return ('fail', 'tmux not on PATH; jawn-tmux cannot manage sessions')
    try:
        out = subprocess.run([binary, '-V'], capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.TimeoutExpired) as e:
        return ('fail', f'tmux -V failed: {e}')
    match = re.search(r'tmux\s+(\d+)\.(\d+)', out.stdout)
    if not match:
        return ('warn', f'unrecognized tmux version string: {out.stdout.strip()!r}')
    major, minor = int(match.group(1)), int(match.group(2))
    if (major, minor) < (3, 0):
        return ('fail', f'tmux {major}.{minor} is too old; need 3.0+')
    if (major, minor) < (3, 2):
        # Format strings in pane-border-style landed in 3.2; the status
        # borders this tool's central feature relies on won't render
        # below that. The status table, sidebar, and HTTP status all
        # still work, so warn rather than fail.
        return ('warn', f'tmux {major}.{minor} ({binary}); status borders need 3.2+')
    return ('ok', f'tmux {major}.{minor} ({binary})')


def _check_tmp_readable() -> CheckResult:
    if not os.path.isdir('/tmp'):
        return ('fail', '/tmp does not exist; marker discovery is impossible')
    if not os.access('/tmp', os.R_OK):
        return ('fail', '/tmp is not readable; marker discovery will silently fail')
    return ('ok', '/tmp is readable')


def _check_output_file_prefixes() -> CheckResult:
    raw = os.environ.get('JT_OUTPUT_FILE_PREFIXES')
    prefixes = daemon._resolve_output_file_prefixes()
    if not prefixes:
        return ('fail', 'no marker prefixes configured; done/error states will never trigger')
    if raw and tuple(p.strip() for p in raw.split(',') if p.strip()) != prefixes:
        # Resolver fell back to defaults despite the env var being set
        return ('warn', f'JT_OUTPUT_FILE_PREFIXES={raw!r} produced no usable prefixes; using defaults {prefixes}')
    return ('ok', f'scanning prefixes {prefixes}')


def _check_port() -> CheckResult:
    raw = os.environ.get('JT_PORT')
    port = daemon._resolve_port()
    if not (1 <= port <= 65535):
        return ('fail', f'resolved port {port} is out of range')
    if raw and str(port) != raw.strip():
        return ('warn', f'JT_PORT={raw!r} ignored; using default {port}')
    return ('ok', f'port {port}')


def _check_bind() -> CheckResult:
    bind = daemon._resolve_bind()
    if not bind:
        return ('fail', 'bind address resolved to empty string')
    if bind != '127.0.0.1':
        return ('warn', f'bound to {bind} (state JSON contains agent stdout — confirm this interface is private)')
    return ('ok', f'bound to {bind} (loopback)')


def _check_daemon_http() -> CheckResult:
    bind = daemon._resolve_bind()
    port = daemon._resolve_port()
    # 0.0.0.0 / :: mean "all interfaces" — connect to loopback for the probe.
    host = '127.0.0.1' if bind in ('0.0.0.0', '::') else bind
    # IPv6 literals must be bracket-wrapped in URLs (RFC 3986 §3.2.2),
    # otherwise urllib parses the trailing :port as part of the address.
    host_in_url = f'[{host}]' if ':' in host else host
    url = f'http://{host_in_url}:{port}/status'
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            if resp.status != 200:
                return ('fail', f'GET {url} returned HTTP {resp.status}')
            json.loads(resp.read().decode('utf-8'))
    except urllib.error.URLError as e:
        return ('fail', f'GET {url} failed: {e.reason}')
    except (OSError, json.JSONDecodeError) as e:
        return ('fail', f'GET {url} failed: {e}')
    return ('ok', f'daemon responded at {url}')


LAST_ERROR_FRESH_SECS = 300


def _check_last_error() -> CheckResult:
    """Surface the daemon's last poll error, if any.

    Recent errors warn; older ones report as ``ok`` with a descriptive note
    so users can still see that *something* happened earlier without being
    nagged forever about a single transient hiccup.
    """
    data = state.read_state()
    err = data.get('last_error')
    if not err:
        return ('ok', 'no daemon errors recorded')
    age = max(0, int(time.time()) - err.get('at', 0))
    msg = err.get('message', 'unknown')
    if age <= LAST_ERROR_FRESH_SECS:
        return ('warn', f'recent daemon error ({age}s ago): {msg}')
    return ('ok', f'last daemon error was {age}s ago (recovered): {msg}')


CHECKS: list[tuple[str, CheckFn]] = [
    ('runtime_dir', _check_runtime_dir),
    ('state_file_fresh', _check_state_file_fresh),
    ('tmux_present', _check_tmux),
    ('tmp_readable', _check_tmp_readable),
    ('output_file_prefixes', _check_output_file_prefixes),
    ('port', _check_port),
    ('bind', _check_bind),
    ('daemon_http', _check_daemon_http),
    ('last_error', _check_last_error),
]


def run_checks() -> list[dict]:
    """Execute every check and return a list of dicts.

    Returned shape: ``[{'name': str, 'level': str, 'message': str}, ...]``.
    Wrap each check so a single buggy check can't take down the whole report.
    """
    results = []
    for name, fn in CHECKS:
        try:
            level, message = fn()
        except Exception as e:  # noqa: BLE001
            level, message = 'fail', f'check raised {type(e).__name__}: {e}'
        results.append({'name': name, 'level': level, 'message': message})
    return results


def format_human(results: list[dict]) -> str:
    width = max(len(r['name']) for r in results)
    lines = []
    for r in results:
        glyph = LEVEL_GLYPHS.get(r['level'], r['level'].upper())
        lines.append(f'  {glyph:<4}  {r["name"]:<{width}}  {r["message"]}')
    return '\n'.join(lines)


def exit_code(results: list[dict]) -> int:
    return 1 if any(r['level'] == 'fail' for r in results) else 0
