# jt/tmux.py
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


def _parse_pane_listing(stdout: str) -> list[dict]:
    panes = []
    for line in stdout.strip().splitlines():
        parts = line.split('\t')
        if len(parts) == 2:
            panes.append({'id': parts[0], 'command': parts[1]})
    return panes


def list_panes(session: str) -> list[dict]:
    """Panes in the session's *current* window.

    Window-scoped because the daemon uses this for command labeling in
    the status table — "first pane in current window" is a fine
    representative for a one-line summary. Border painting needs every
    pane in every window of the session, which goes through
    :func:`list_session_panes` instead.
    """
    result = subprocess.run(
        ['tmux', 'list-panes', '-t', session, '-F',
         '#{pane_id}\t#{pane_current_command}'],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return []
    return _parse_pane_listing(result.stdout)


def list_session_panes(session: str) -> list[dict]:
    """Every pane in every window of ``session``.

    The ``-s`` flag widens the listing scope from a single window to the
    whole session. Without it, multi-window agent sessions would have
    their non-current windows silently skipped during border paints.
    """
    result = subprocess.run(
        ['tmux', 'list-panes', '-s', '-t', session, '-F',
         '#{pane_id}\t#{pane_current_command}'],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return []
    return _parse_pane_listing(result.stdout)


def first_pane_id(session: str) -> Optional[str]:
    """First pane id (e.g. ``%7``) of ``session``, or None if empty.

    Pane ids are stable identifiers tmux assigns at pane creation; using
    them avoids the window/pane index landmines (``base-index 1``,
    renamed windows, multi-pane layouts).
    """
    panes = list_panes(session)
    return panes[0]['id'] if panes else None


def new_session(name: str, command: str, cwd: Optional[str] = None) -> bool:
    args = ['tmux', 'new-session', '-d', '-s', name]
    if cwd:
        args += ['-c', cwd]
    if command:
        # Pass the command as a single argument. tmux runs the
        # shell-command via /bin/sh -c, so loops, pipes, ``&&`` and other
        # shell syntax work. Splitting via shlex would shatter those tokens
        # and tmux would try to exec ``while`` directly, which fails.
        args.append(command)
    return subprocess.run(args, capture_output=True).returncode == 0


def kill_session(name: str) -> bool:
    return subprocess.run(
        ['tmux', 'kill-session', '-t', name], capture_output=True
    ).returncode == 0


def has_session(name: str) -> bool:
    return subprocess.run(
        ['tmux', 'has-session', '-t', name], capture_output=True
    ).returncode == 0


def set_pane_status_color(pane_id: str, fg: str) -> bool:
    """Tag a pane with the @jt_status_fg user option.

    The shipped jt.conf reads this option in ``pane-border-style`` and
    ``pane-active-border-style`` format strings, so the border re-renders
    in the requested color. The previous implementation called
    ``select-pane -P fg=`` which sets pane *content* foreground, not the
    border, and additionally targeted ``session:0`` which doesn't resolve
    on tmux configs with ``base-index 1``.
    """
    result = subprocess.run(
        ['tmux', 'set-option', '-p', '-t', pane_id, '@jt_status_fg', fg],
        capture_output=True,
    )
    return result.returncode == 0
