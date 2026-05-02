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
HTTP_PORT = int(os.environ.get('JT_PORT') or 6248)
HTTP_BIND = os.environ.get('JT_BIND') or '127.0.0.1'

STATUS_COLORS = {
    'active': '#3fb950',
    'silent': '#d29922',
    'done':   '#484f58',
    'error':  '#f85149',
}

log = logging.getLogger('jtd')


def _find_output_file(session_created: int) -> str | None:
    files = sorted(glob.glob('/tmp/claude_scheduled_*.txt'), key=os.path.getmtime)
    for f in reversed(files):
        try:
            ts = int(Path(f).stem.replace('claude_scheduled_', ''))
        except ValueError:
            continue
        if abs(ts - session_created) < 60:
            return f
    return None


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


def _update_borders(prev: dict, curr: dict) -> None:
    for name, info in curr.items():
        if name == 'main':
            continue
        if info['status'] != prev.get(name, {}).get('status'):
            color = STATUS_COLORS.get(info['status'], STATUS_COLORS['active'])
            tmux.set_pane_style(name, '0', color)


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


def _make_http_server(port: int = HTTP_PORT, host: str | None = None) -> ThreadingHTTPServer:
    """Bind the HTTP server.

    Defaults to ``127.0.0.1`` so the state JSON — which contains agent stdout
    tails — is not exposed to the network. Set the ``JT_BIND`` environment
    variable to a Tailscale IP (or ``0.0.0.0``, knowing the risk) to enable
    cross-node aggregation.
    """
    bind = host if host is not None else HTTP_BIND
    return ThreadingHTTPServer((bind, port), _StatusHandler)


def run():
    logging.basicConfig(
        level=os.environ.get('JT_LOG_LEVEL', 'INFO'),
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )
    node = socket.gethostname()
    try:
        server = _make_http_server()
    except OSError as e:
        log.error('failed to bind %s:%s — %s', HTTP_BIND, HTTP_PORT, e)
        raise
    log.info('jtd serving %s:%s as %s', HTTP_BIND, HTTP_PORT, node)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    prev_sessions: dict = {}
    while True:
        try:
            raw = tmux.list_sessions()
            now = time.time()
            curr = build_session_state(raw, now)
            state.write_state(node, curr)
            _update_borders(prev_sessions, curr)
            prev_sessions = curr
        except KeyboardInterrupt:
            log.info('shutting down')
            server.shutdown()
            return
        except Exception:
            # A poll failure should not crash the daemon, but we want a
            # traceback in the journal so transient errors are debuggable.
            log.exception('poll failed')
        time.sleep(POLL_INTERVAL)
