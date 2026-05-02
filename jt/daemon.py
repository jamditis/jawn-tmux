# jt/daemon.py
import glob
import json
import logging
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from jt import tmux, state

SILENCE_THRESHOLD = 20   # seconds, matches monitor-silence 20 in .tmux.conf
POLL_INTERVAL = 2
LAST_ERROR_VISIBILITY_SECS = 300  # 5 min: how long a recovered error stays in state.json
DEFAULT_HTTP_PORT = 6248
DEFAULT_HTTP_BIND = '127.0.0.1'
DEFAULT_OUTPUT_FILE_PREFIXES = ('claude_scheduled', 'codex_scheduled')

STATUS_COLORS = {
    'active': '#3fb950',
    'silent': '#d29922',
    'done':   '#484f58',
    'error':  '#f85149',
}

log = logging.getLogger('jtd')


def _resolve_port(default: int = DEFAULT_HTTP_PORT) -> int:
    """Read JT_PORT lazily so a typo doesn't crash module import.

    A bad value logs a warning and falls back to the default; the daemon
    still starts on a known port instead of dying with an import-time
    traceback that systemd will keep restarting.
    """
    raw = os.environ.get('JT_PORT')
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        log.warning('JT_PORT=%r is not an integer; falling back to %d', raw, default)
        return default


def _resolve_bind(default: str = DEFAULT_HTTP_BIND) -> str:
    return os.environ.get('JT_BIND') or default


def _resolve_output_file_prefixes() -> tuple[str, ...]:
    """Comma-separated env override; falls back to the default tuple.

    Defaults cover the two scheduler wrappers we ship awareness of
    (claude-scheduler, codex-scheduler). Set JT_OUTPUT_FILE_PREFIXES to
    extend or replace, e.g. "claude_scheduled,codex_scheduled,my_runner".
    """
    raw = os.environ.get('JT_OUTPUT_FILE_PREFIXES')
    if not raw:
        return DEFAULT_OUTPUT_FILE_PREFIXES
    prefixes = tuple(p.strip() for p in raw.split(',') if p.strip())
    return prefixes or DEFAULT_OUTPUT_FILE_PREFIXES


def _find_output_file(session_created: int) -> str | None:
    candidates: list[tuple[float, str]] = []
    for prefix in _resolve_output_file_prefixes():
        for f in glob.glob(f'/tmp/{prefix}_*.txt'):
            try:
                ts = int(Path(f).stem.removeprefix(f'{prefix}_'))
            except ValueError:
                continue
            if abs(ts - session_created) < 60:
                candidates.append((os.path.getmtime(f), f))
    if not candidates:
        return None
    candidates.sort()
    return candidates[-1][1]


def _read_output_tail(output_file: str, n: int = 3) -> list[str]:
    try:
        # Read only the tail. We cap at 64 KiB so a runaway log file doesn't
        # cause a multi-GB read every poll.
        path = Path(output_file)
        with path.open('rb') as f:
            try:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 65536))
            except OSError:
                pass
            data = f.read().decode('utf-8', errors='replace')
        lines = [ln.rstrip() for ln in data.splitlines() if ln.strip()]
        return lines[-n:]
    except OSError:
        return []


def _check_completion(output_file: str | None) -> str | None:
    if not output_file:
        return None
    try:
        # Same cap as _read_output_tail; the marker is always written near the
        # end of the file so a tail read is sufficient.
        path = Path(output_file)
        with path.open('rb') as f:
            try:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 65536))
            except OSError:
                pass
            data = f.read().decode('utf-8', errors='replace')
        for line in data.splitlines():
            if line.startswith('CLAUDE_TASK_COMPLETE:'):
                code = int(line.split(':', 1)[1].strip())
                return 'done' if code == 0 else 'error'
    except (OSError, ValueError):
        pass
    return None


def compute_session_status(session: dict, now: float) -> str:
    completion = _check_completion(session.get('output_file'))
    if completion:
        return completion
    last_activity = session.get('last_activity')
    if last_activity is None:
        return 'active'
    if now - last_activity > SILENCE_THRESHOLD:
        return 'silent'
    return 'active'


def build_session_state(raw_sessions: list[dict], now: float) -> dict:
    result = {}
    for s in raw_sessions:
        name = s['name']
        panes = tmux.list_panes(name)
        command = panes[0]['command'] if panes else 'unknown'
        output_file = _find_output_file(s['created']) if name != 'main' else None
        output_tail = _read_output_tail(output_file) if output_file else []
        status = compute_session_status({**s, 'output_file': output_file}, now)
        result[name] = {
            'name': name,
            'status': status,
            'command': command,
            'elapsed_secs': max(0, int(now - s['created'])),
            'last_activity_secs': max(0, int(now - s['last_activity'])),
            'output_tail': output_tail,
            'output_file': output_file,
        }
    return result


def _should_clear_last_error(last_error: dict | None, now: float) -> bool:
    """True when a recovered error has stayed visible long enough to clear.

    Errors stay in state.json for ``LAST_ERROR_VISIBILITY_SECS`` after they
    happen so users running `jt status` or `jt doctor` see them at least
    once. After that, a single transient hiccup shouldn't look permanent.
    """
    if not last_error:
        return False
    return (now - last_error.get('at', 0)) > LAST_ERROR_VISIBILITY_SECS


def _update_borders(prev: dict, curr: dict) -> None:
    for name, info in curr.items():
        if name == 'main':
            continue
        if info['status'] == prev.get(name, {}).get('status'):
            continue
        color = STATUS_COLORS.get(info['status'], STATUS_COLORS['active'])
        # Paint every pane in every window of the session. Multi-window
        # agent sessions need consistent border color across all panes;
        # painting only the first window's first pane left the rest stale.
        for pane in tmux.list_session_panes(name):
            pane_id = pane['id']
            if not tmux.set_pane_status_color(pane_id, color):
                # Don't raise — paint failures shouldn't kill the poll
                # loop. Surface to journald so regressions are debuggable.
                log.warning('failed to paint %s pane %s color=%s', name, pane_id, color)


class _StatusHandler(BaseHTTPRequestHandler):
    server_version = 'jtd/0.1'

    def do_GET(self):
        if self.path == '/status':
            body = json.dumps(state.read_state()).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.send_header('Content-Length', '0')
            self.end_headers()

    def log_message(self, format, *args):  # noqa: A002
        # Route HTTP access logs through the configured logger so they end up
        # in the systemd journal at DEBUG, not interleaved with poll output.
        log.debug('http %s - %s', self.address_string(), format % args)


def _make_http_server(port: int | None = None, host: str | None = None) -> ThreadingHTTPServer:
    """Bind the HTTP server.

    Defaults to ``127.0.0.1`` so the state JSON — which contains agent stdout
    tails — is not exposed to the network. Set the ``JT_BIND`` environment
    variable to a Tailscale IP (or ``0.0.0.0``, knowing the risk) to enable
    cross-node aggregation.
    """
    bind = host if host is not None else _resolve_bind()
    p = port if port is not None else _resolve_port()
    return ThreadingHTTPServer((bind, p), _StatusHandler)


def run():
    logging.basicConfig(
        level=os.environ.get('JT_LOG_LEVEL', 'INFO'),
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )
    node = socket.gethostname()
    bind = _resolve_bind()
    port = _resolve_port()
    try:
        server = _make_http_server(port=port, host=bind)
    except OSError as e:
        log.error('failed to bind %s:%s — %s', bind, port, e)
        raise
    log.info('jtd serving %s:%s as %s', bind, port, node)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    prev_sessions: dict = {}
    last_sessions: dict = {}
    last_error: dict | None = None
    while True:
        try:
            raw = tmux.list_sessions()
            now = time.time()
            curr = build_session_state(raw, now)
            last_sessions = curr
            # Recovered errors stay in state.json for the visibility window so
            # `jt status` / `jt doctor` can warn the user; after that they're
            # cleared so a single transient hiccup doesn't look permanent.
            # journalctl preserves the full history regardless.
            if _should_clear_last_error(last_error, now):
                log.info('clearing last_error from state (recovered %ds ago)',
                         int(now - last_error['at']))
                last_error = None
            state.write_state(node, curr, last_error)
            _update_borders(prev_sessions, curr)
            prev_sessions = curr
        except KeyboardInterrupt:
            log.info('shutting down')
            server.shutdown()
            return
        except Exception as e:
            # A poll failure should not crash the daemon, but we want a
            # traceback in the journal so transient errors are debuggable
            # and a structured record in the state file so `jt doctor`
            # can surface it without users running journalctl themselves.
            log.exception('poll failed')
            last_error = {
                'message': str(e),
                'type': type(e).__name__,
                'at': int(time.time()),
            }
            try:
                state.write_state(node, last_sessions, last_error)
            except Exception:
                log.exception('failed to write error to state file')
        time.sleep(POLL_INTERVAL)
