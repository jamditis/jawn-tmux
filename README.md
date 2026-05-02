# jawn-tmux

[![version](https://img.shields.io/github/v/tag/jamditis/jawn-tmux?style=flat-square&color=3fb950&labelColor=0d120d&label=version)](https://github.com/jamditis/jawn-tmux/releases)
[![python](https://img.shields.io/badge/python-3.11%2B-3fb950?style=flat-square&labelColor=0d120d)](https://python.org)
[![license](https://img.shields.io/badge/license-MIT-484f58?style=flat-square&labelColor=0d120d)](LICENSE)
[![platform](https://img.shields.io/badge/platform-linux%20arm64%20%7C%20x86%20%7C%20wsl2-484f58?style=flat-square&labelColor=0d120d)](#install)
[![tests](https://img.shields.io/badge/tests-56%20passing-3fb950?style=flat-square&labelColor=0d120d)](tests/)
[![stdlib only](https://img.shields.io/badge/deps-stdlib%20only-3fb950?style=flat-square&labelColor=0d120d)](#)

tmux session manager for AI agent workflows. Visual pane border attention, live sidebar, cross-node status.

**[Documentation & demo →](https://jamditis.github.io/jawn-tmux)**

![jt status — two sessions, one active (green) and one silent (amber)](docs/screenshot.png)

---

## What it does

When you run multiple AI agents in parallel tmux sessions, it's hard to tell what's happening without switching between each one. jawn-tmux adds:

- **Colored pane borders** — green (active), amber (silent), gray (done), red (error)
- **Live sidebar** — 36-col right pane showing all sessions + output tails, refreshing every 2s
- **Interactive popup** — `Ctrl+B a` opens a status overlay; `k` kills, `q` closes
- **Cross-node status** — `jt nodes` aggregates sessions from all configured machines via HTTP

## How it works

Two processes:

**`jtd` (daemon)** polls tmux every 2 seconds, writes the state file, updates pane border colors, and serves the state JSON on port 6248 for cross-node polling.

**`jt` (CLI)** reads the state file directly for instant local status and hits remote nodes' HTTP endpoints concurrently for `jt nodes`.

```
jtd (systemd user service)
  ├── polls tmux list-sessions every 2s
  ├── writes $XDG_RUNTIME_DIR/jt-state.json (atomic, mode 0600)
  ├── updates tmux pane borders via select-pane -P
  └── serves :6248/status (bound to 127.0.0.1 by default)

jt (CLI)
  ├── reads the state file directly
  └── fetches <node-ip>:6248/status concurrently for remote nodes
```

The state file lives under `$XDG_RUNTIME_DIR` (typically `/run/user/$UID`) so it is private to the invoking user. If `XDG_RUNTIME_DIR` is not set the daemon falls back to `/tmp/jt-state.json`. Set `JT_STATE_FILE` to override.

## Install

Requires Python 3.11+, tmux 3.0+, systemd. Works on Linux ARM64, x86_64, and WSL2.

```bash
git clone https://github.com/jamditis/jawn-tmux.git ~/projects/jawn-tmux
cd ~/projects/jawn-tmux
chmod +x install.sh
./install.sh
```

The installer:
1. Installs `jt` and `jtd` to `~/.local/bin` via pip editable install
2. Appends `source-file .../tmux/jt.conf` to `~/.tmux.conf` (idempotent)
3. Copies the systemd unit to `~/.config/systemd/user/` and starts the service

Verify it's running:
```bash
systemctl --user status jtd
jt status
```

## Commands

| Command | Description |
|---------|-------------|
| `jt` / `jt status` | Table of all local sessions |
| `jt watch` | Live re-render loop (2s interval) |
| `jt popup` | Interactive status popup (`q` close, `k` kill) |
| `jt sidebar [on\|off\|toggle]` | Toggle 36-col persistent right pane |
| `jt spawn <name> <cmd>` | Create a named tmux session |
| `jt kill <name>` | Kill a session |
| `jt attach <name>` | Attach to a session |
| `jt nodes` | Aggregate status from all configured nodes |

## Tmux keybindings

Added via `source-file ~/projects/jawn-tmux/tmux/jt.conf`:

| Binding | Action |
|---------|--------|
| `Ctrl+B a` | Status popup |
| `Ctrl+B A` | Sidebar toggle |

## Session states

| Status | Trigger | Pane border |
|--------|---------|-------------|
| `active` | Output in last 20s | `#3fb950` green |
| `silent` | No output for 20s+ | `#d29922` amber |
| `done` | `CLAUDE_TASK_COMPLETE:0` in output | `#484f58` dim gray |
| `error` | Non-zero exit in marker | `#f85149` red |

The `done`/`error` states read the `CLAUDE_TASK_COMPLETE:$EXIT_CODE` marker written by [claude-scheduler](https://github.com/jamditis/houseofjawn-bot). The `main` session's border is never modified.

## Multi-node setup

By default, `jtd` only binds the HTTP listener to `127.0.0.1`. The state JSON
contains agent stdout tails, so the listener stays local until you opt in.

To enable cross-node aggregation, point `JT_BIND` at the host's Tailscale IP
(or another private interface) via a systemd drop-in:

```bash
systemctl --user edit jtd
```

```ini
[Service]
Environment=JT_BIND=100.122.208.15
```

Editing the unit doesn't restart it — apply the change explicitly:

```bash
systemctl --user daemon-reload
systemctl --user restart jtd
```

Then list your machines in `~/.config/jt/nodes.json`:

```json
[
  {"name": "houseofjawn", "ip": "100.122.208.15", "port": 6248},
  {"name": "officejawn",  "ip": "100.84.214.24",  "port": 6248}
]
```

`jt nodes` fetches each node's `/status` endpoint concurrently and renders a
combined view. Unreachable nodes are shown as such without blocking.

### Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `JT_BIND` | `127.0.0.1` | HTTP bind interface for `jtd`. Set to a Tailscale IP to enable `jt nodes`. |
| `JT_PORT` | `6248` | HTTP port. |
| `JT_STATE_FILE` | `$XDG_RUNTIME_DIR/jt-state.json`, then `/tmp/jt-state.json` | Override the state file path. |
| `JT_LOG_LEVEL` | `INFO` | Log level for the daemon (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |

## Development

```bash
git clone https://github.com/jamditis/jawn-tmux.git
cd jawn-tmux
pip3 install --break-system-packages -e .
python3 -m pytest -v
```

56 tests, stdlib only, no third-party runtime deps.

## File layout

```
jawn-tmux/
├── jt/
│   ├── cli.py        # argparse entry point
│   ├── daemon.py     # jtd — poller + HTTP server (port 6248)
│   ├── state.py      # read/write /tmp/jt-state.json
│   ├── render.py     # table, watch loop, popup layout
│   ├── tmux.py       # subprocess wrappers
│   └── nodes.py      # cross-node HTTP client
├── tests/            # 56 pytest tests
├── config/
│   └── nodes.json    # default node definitions
├── systemd/
│   └── jtd.service   # systemd user service unit
├── tmux/
│   └── jt.conf       # Ctrl+B a / Ctrl+B A keybindings
├── docs/             # GitHub Pages
└── install.sh        # installer
```

## Acknowledgments

jawn-tmux was inspired by [cmux](https://github.com/manaflow-ai/cmux) — a native macOS terminal built on Ghostty that pioneered the idea of visual session state for parallel AI agent workflows (blue ring indicators, per-workspace sidebars with branch/port/notification data). jawn-tmux adapts the same concept for Linux and tmux users who can't run macOS-native apps.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Issues and PRs welcome.

## License

MIT
