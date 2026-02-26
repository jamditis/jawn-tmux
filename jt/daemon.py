# jt/daemon.py
import glob
import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from jt import tmux, state

SILENCE_THRESHOLD = 20   # seconds, matches monitor-silence 20 in .tmux.conf
POLL_INTERVAL = 2
HTTP_PORT = 6248

STATUS_COLORS = {
    'active': '#3fb950',
    'silent': '#d29922',
    'done':   '#484f58',
    'error':  '#f85149',
}


def _find_output_file(session_created: int) -> str | None:
    files = sorted(glob.glob('/tmp/claude_scheduled_*.txt'), key=os.path.getmtime)
    for f in reversed(files):
        try:
            ts = int(Path(f).stem.replace('claude_scheduled_', ''))
            if abs(ts - session_created) < 60:
                return f
        except ValueError:
            continue
    return None


def _read_output_tail(output_file: str, n: int = 3) -> list[str]:
    try:
        lines = [ln.rstrip() for ln in Path(output_file).read_text().splitlines()
                 if ln.strip()]
        return lines[-n:] if len(lines) >= n else lines
    except OSError:
        return []


def _check_completion(output_file: str | None) -> str | None:
    if not output_file:
        return None
    try:
        for line in Path(output_file).read_text().splitlines():
            if line.startswith('CLAUDE_TASK_COMPLETE:'):
                code = int(line.split(':')[1].strip())
                return 'done' if code == 0 else 'error'
    except (OSError, ValueError):
        pass
    return None


def compute_session_status(session: dict, now: float) -> str:
    completion = _check_completion(session.get('output_file'))
    if completion:
        return completion
    if now - session['last_activity'] > SILENCE_THRESHOLD:
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
            'elapsed_secs': int(now - s['created']),
            'last_activity_secs': int(now - s['last_activity']),
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
