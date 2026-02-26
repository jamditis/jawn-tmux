# jt/cli.py
import argparse
import subprocess
import sys
import termios
import time
import tty

from jt import tmux, state, render
from jt.nodes import load_nodes, fetch_remote_state


def _getch() -> str:
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def cmd_status(args):
    print(render.render_table(state.read_state()))


def cmd_watch(args):
    render.watch()


def cmd_popup(args):
    local = state.read_state()
    node_name = local.get('node', '')
    remotes = [
        fetch_remote_state(n)
        for n in load_nodes()
        if n['name'] != node_name
    ]
    while True:
        subprocess.run(['clear'], check=False)
        print(render.render_table(local))
        for r in remotes:
            if r:
                print(render.render_table(r))
        print('\n  [q] close   [k] kill session')
        ch = _getch()
        if ch == 'q':
            break
        elif ch == 'k':
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
            name = input('\n  session name: ').strip()
            if name:
                ok = tmux.kill_session(name)
                print('killed' if ok else 'not found')
                time.sleep(1)
        local = state.read_state()


def cmd_sidebar(args):
    action = getattr(args, 'action', 'toggle')
    result = subprocess.run(
        ['tmux', 'list-panes', '-F', '#{pane_title}'],
        capture_output=True, text=True,
    )
    has_sidebar = 'jt-sidebar' in result.stdout

    if action == 'toggle':
        action = 'off' if has_sidebar else 'on'

    if action == 'on' and not has_sidebar:
        subprocess.run(['tmux', 'split-window', '-h', '-l', '36', '-d', 'jt watch'],
                       capture_output=True)
        subprocess.run(['tmux', 'select-pane', '-T', 'jt-sidebar'], capture_output=True)
    elif action == 'off' and has_sidebar:
        result = subprocess.run(
            ['tmux', 'list-panes', '-F', '#{pane_id} #{pane_title}'],
            capture_output=True, text=True,
        )
        for line in result.stdout.splitlines():
            if 'jt-sidebar' in line:
                pane_id = line.split()[0]
                subprocess.run(['tmux', 'kill-pane', '-t', pane_id], capture_output=True)
                break


def cmd_spawn(args):
    ok = tmux.new_session(args.name, args.cmd)
    print('ok' if ok else 'failed')


def cmd_kill(args):
    ok = tmux.kill_session(args.name)
    print('ok' if ok else 'not found')


def cmd_attach(args):
    subprocess.run(['tmux', 'attach', '-t', args.name])


def cmd_nodes(args):
    local = state.read_state()
    print(render.render_table(local))
    node_name = local.get('node', '')
    for n in load_nodes():
        if n['name'] != node_name:
            remote = fetch_remote_state(n)
            if remote:
                print(render.render_table(remote))
            else:
                print(f"  {n['name']}  (unreachable)\n")


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

    args = parser.parse_args()
    if not hasattr(args, 'func'):
        cmd_status(args)
    else:
        args.func(args)
