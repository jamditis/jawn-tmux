# jt/tmux.py
import shlex
import subprocess
from typing import Optional


def list_sessions() -> list[dict]:
    result = subprocess.run(
        ['tmux', 'list-sessions', '-F',
         '#{session_name}\t#{session_created}\t#{session_activity}'],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return []
    sessions = []
    for line in result.stdout.strip().splitlines():
        parts = line.split('\t')
        if len(parts) == 3:
            try:
                sessions.append({
                    'name': parts[0],
                    'created': int(parts[1]),
                    'last_activity': int(parts[2]),
                })
            except ValueError:
                continue
    return sessions


def list_panes(session: str) -> list[dict]:
    result = subprocess.run(
        ['tmux', 'list-panes', '-t', session, '-F',
         '#{pane_id}\t#{pane_current_command}'],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return []
    panes = []
    for line in result.stdout.strip().splitlines():
        parts = line.split('\t')
        if len(parts) == 2:
            panes.append({'id': parts[0], 'command': parts[1]})
    return panes


def new_session(name: str, command: str, cwd: Optional[str] = None) -> bool:
    args = ['tmux', 'new-session', '-d', '-s', name]
    if cwd:
        args += ['-c', cwd]
    if command:
        args += shlex.split(command)
    return subprocess.run(args, capture_output=True).returncode == 0


def kill_session(name: str) -> bool:
    return subprocess.run(
        ['tmux', 'kill-session', '-t', name], capture_output=True
    ).returncode == 0


def has_session(name: str) -> bool:
    return subprocess.run(
        ['tmux', 'has-session', '-t', name], capture_output=True
    ).returncode == 0


def set_pane_style(session: str, pane: str, fg: str) -> bool:
    result = subprocess.run(
        ['tmux', 'select-pane', '-t', f'{session}:{pane}', '-P', f'fg={fg}'],
        capture_output=True,
    )
    return result.returncode == 0
