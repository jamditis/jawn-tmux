# jt/render.py
import subprocess
import time
from jt import state as state_mod

STATUS_ICONS = {'active': '●', 'silent': '~', 'done': '✓', 'error': '✗'}

ANSI = {
    'active': '\033[32m',
    'silent': '\033[33m',
    'done':   '\033[90m',
    'error':  '\033[31m',
    'reset':  '\033[0m',
    'dim':    '\033[2m',
    'bold':   '\033[1m',
}


def format_elapsed(secs: int) -> str:
    if secs < 60:
        return f'{secs}s'
    if secs < 3600:
        return f'{secs // 60}m'
    return f'{secs // 3600}h{(secs % 3600) // 60}m'


def render_session_row(name: str, info: dict) -> str:
    status = info['status']
    icon = STATUS_ICONS.get(status, '?')
    color = ANSI.get(status, '')
    reset = ANSI['reset']
    elapsed = format_elapsed(info['elapsed_secs'])
    cmd = info.get('command', '?')
    row = f"  {color}{name:<22} {status:<8} {icon}  {elapsed:<6} {cmd}{reset}"
    tail = info.get('output_tail') or []
    tail_lines = '\n'.join(f"    {ANSI['dim']}{ln}{reset}" for ln in tail)
    return row + ('\n' + tail_lines if tail_lines else '')


_ERROR_BANNER_FRESH_SECS = 300  # 5 min: highlight recent daemon errors prominently


def _render_error_banner(data: dict) -> str | None:
    err = (data or {}).get('last_error')
    if not err:
        return None
    age = max(0, int(time.time()) - err.get('at', 0))
    msg = err.get('message', 'unknown')
    color = ANSI['error'] if age <= _ERROR_BANNER_FRESH_SECS else ANSI['dim']
    label = 'daemon error' if age <= _ERROR_BANNER_FRESH_SECS else 'last daemon error'
    return f"  {color}! {label} ({age}s ago): {msg}{ANSI['reset']}\n  {ANSI['dim']}run `jt logs` for the full traceback{ANSI['reset']}"


def render_table(data: dict) -> str:
    sessions = (data or {}).get('sessions', {})
    if not sessions:
        return 'No sessions.'
    node = data.get('node', 'unknown')
    ts = time.strftime('%H:%M:%S', time.localtime(data.get('updated_at', 0)))
    lines = [f"  {ANSI['bold']}{node}{ANSI['reset']}  {ANSI['dim']}{ts}{ANSI['reset']}", '']
    banner = _render_error_banner(data)
    if banner:
        lines.append(banner)
        lines.append('')
    for name, info in sorted(sessions.items()):
        lines.append(render_session_row(name, info))
        lines.append('')
    return '\n'.join(lines)


def watch(interval: int = 2) -> None:
    while True:
        subprocess.run(['clear'], check=False)
        print(render_table(state_mod.read_state()))
        time.sleep(interval)
