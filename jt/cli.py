# jt/cli.py
import argparse
import json
import os
import select
import shutil
import subprocess
import sys
import termios
import time
import tty

from jt import doctor as doctor_mod
from jt import nodes as nodes_mod
from jt import render
from jt import state
from jt import tmux

_CLEAR = '\033[2J\033[H'   # clear + home, faster than running clear(1)
_POPUP_TICK = 2.0          # seconds; matches the daemon's poll interval


def _wait_key(timeout: float | None = None) -> str | None:
    """Wait up to ``timeout`` seconds for a single keypress.

    Returns the character on input, ``None`` if the timeout elapsed without
    a keypress (the caller can use this to refresh on a tick), or ``''`` if
    the read was interrupted. Restores the terminal attributes even on
    interrupt so the user is never left in an unusable cbreak mode.
    """
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        if not ready:
            return None
        return sys.stdin.read(1)
    except (OSError, KeyboardInterrupt):
        return ''
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def cmd_status(args):
    print(render.render_table(state.read_state()))


def cmd_watch(args):
    render.watch()


def cmd_popup(args):
    while True:
        local = state.read_state()
        node_name = local.get('node', '')
        remotes = [
            r for n, r in nodes_mod.fetch_remotes(
                [n for n in nodes_mod.load_nodes() if n.get('name') != node_name]
            )
            if r
        ]
        sys.stdout.write(_CLEAR)
        print(render.render_table(local))
        for r in remotes:
            print(render.render_table(r))
        print('\n  [q] close   [k] kill session')
        sys.stdout.flush()
        ch = _wait_key(_POPUP_TICK)
        if ch is None:
            # Timeout: re-render with fresh state so the popup doesn't go
            # stale while the user idles.
            continue
        if ch in ('q', '\x03', ''):  # q, Ctrl-C, or read failure
            break
        if ch == 'k':
            sys.stdout.write('\n  session name: ')
            sys.stdout.flush()
            name = sys.stdin.readline().strip()
            if name:
                ok = tmux.kill_session(name)
                print('killed' if ok else 'not found')
                time.sleep(0.6)


def _find_sidebar_pane() -> str | None:
    """Return the pane id of the sidebar, or None.

    The sidebar is identified by the per-pane ``@jt_sidebar`` user option,
    not by pane title. Pane titles get clobbered by shell escape sequences
    (``\033]2;...\007``) and other tools, so they're unreliable.
    """
    result = subprocess.run(
        ['tmux', 'list-panes', '-F', '#{pane_id} #{@jt_sidebar}'],
        capture_output=True, text=True,
    )
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == '1':
            return parts[0]
    return None


def cmd_sidebar(args):
    action = getattr(args, 'action', 'toggle')
    sidebar_pane = _find_sidebar_pane()

    if action == 'toggle':
        action = 'off' if sidebar_pane else 'on'

    if action == 'on' and not sidebar_pane:
        # ``-P -F '#{pane_id}'`` makes split-window print the new pane id
        # on stdout. Using the printed id instead of an implicit "active
        # pane" assumption is necessary because we passed ``-d``, which
        # leaves the original pane focused — so a follow-up
        # ``select-pane -T`` (no -t) would tag the wrong pane.
        r = subprocess.run(
            ['tmux', 'split-window', '-h', '-l', '36', '-d',
             '-P', '-F', '#{pane_id}', 'jt watch'],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            new_pane = r.stdout.strip()
            if new_pane:
                subprocess.run(
                    ['tmux', 'set-option', '-p', '-t', new_pane,
                     '@jt_sidebar', '1'],
                    capture_output=True,
                )
        else:
            print('failed to open sidebar:', r.stderr.strip(), file=sys.stderr)
    elif action == 'off' and sidebar_pane:
        subprocess.run(['tmux', 'kill-pane', '-t', sidebar_pane], capture_output=True)


def cmd_spawn(args):
    ok = tmux.new_session(args.name, args.cmd)
    print('ok' if ok else 'failed')
    if not ok:
        sys.exit(1)


def cmd_kill(args):
    ok = tmux.kill_session(args.name)
    print('ok' if ok else 'not found')
    if not ok:
        sys.exit(1)


def cmd_attach(args):
    subprocess.run(['tmux', 'attach', '-t', args.name])


def cmd_doctor(args):
    results = doctor_mod.run_checks()
    if getattr(args, 'json', False):
        print(json.dumps({'checks': results}, indent=2))
    else:
        print(doctor_mod.format_human(results))
    sys.exit(doctor_mod.exit_code(results))


def cmd_logs(args):
    """Wrap journalctl --user -u jtd so users don't have to remember the incantation."""
    if not shutil.which('journalctl'):
        print('journalctl not found; jtd may be running outside systemd.', file=sys.stderr)
        print('Start the daemon manually with `jtd` to see output on stderr.', file=sys.stderr)
        sys.exit(1)
    cmd = ['journalctl', '--user', '-u', 'jtd', '--no-pager']
    if args.lines:
        cmd += ['-n', str(args.lines)]
    if args.since:
        cmd += ['--since', args.since]
    if args.follow:
        cmd += ['-f']
    try:
        subprocess.run(cmd, check=False)
    except KeyboardInterrupt:
        # journalctl -f exits cleanly on SIGINT; surface a clean prompt instead of a stack trace.
        sys.exit(0)


def cmd_nodes(args):
    local = state.read_state()
    print(render.render_table(local))
    node_name = local.get('node', '')
    others = [n for n in nodes_mod.load_nodes() if n.get('name') != node_name]
    for node, remote in nodes_mod.fetch_remotes(others):
        if remote:
            print(render.render_table(remote))
        else:
            print(f"  {node.get('name', '?')}  (unreachable)\n")


def main():
    parser = argparse.ArgumentParser(prog='jt', description='jawn-tmux agent session manager')
    sub = parser.add_subparsers(dest='command')

    sub.add_parser('status').set_defaults(func=cmd_status)
    sub.add_parser('watch').set_defaults(func=cmd_watch)
    sub.add_parser('popup').set_defaults(func=cmd_popup)

    p = sub.add_parser('sidebar')
    p.add_argument('action', choices=['on', 'off', 'toggle'], nargs='?', default='toggle')
    p.set_defaults(func=cmd_sidebar)

    p = sub.add_parser('spawn')
    p.add_argument('name')
    p.add_argument('cmd')
    p.set_defaults(func=cmd_spawn)

    p = sub.add_parser('kill')
    p.add_argument('name')
    p.set_defaults(func=cmd_kill)

    p = sub.add_parser('attach')
    p.add_argument('name')
    p.set_defaults(func=cmd_attach)

    sub.add_parser('nodes').set_defaults(func=cmd_nodes)

    p = sub.add_parser('doctor', help='run health checks against the daemon and environment')
    p.add_argument('--json', action='store_true', help='emit machine-readable JSON')
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser('logs', help='tail jtd systemd journal logs')
    p.add_argument('-f', '--follow', action='store_true', help='follow new entries')
    p.add_argument('-n', '--lines', type=int, default=50, help='show the last N lines (default 50)')
    p.add_argument('--since', help='passed through to journalctl --since (e.g. "10m" or "yesterday")')
    p.set_defaults(func=cmd_logs)

    args = parser.parse_args()
    if not hasattr(args, 'func'):
        cmd_status(args)
    else:
        args.func(args)
