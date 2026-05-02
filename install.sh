#!/usr/bin/env bash
# install.sh — set up jawn-tmux on this machine.
#   ./install.sh            install (default)
#   ./install.sh uninstall  remove the systemd unit and tmux source-file line
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
TMUX_CONF="$HOME/.tmux.conf"
SERVICE_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$SERVICE_DIR/jtd.service"
ACTION="${1:-install}"

err()  { printf 'error: %s\n' "$*" >&2; exit 1; }
warn() { printf 'warn:  %s\n' "$*" >&2; }
note() { printf '       %s\n' "$*"; }

require() {
    command -v "$1" >/dev/null 2>&1 || err "missing required command: $1"
}

uninstall() {
    if [ -f "$SERVICE_FILE" ]; then
        systemctl --user stop jtd 2>/dev/null || true
        systemctl --user disable jtd 2>/dev/null || true
        rm -f "$SERVICE_FILE"
        systemctl --user daemon-reload || true
        note "removed $SERVICE_FILE"
    fi
    if [ -f "$TMUX_CONF" ] && grep -q 'jawn-tmux' "$TMUX_CONF"; then
        # Drop the two-line block we inserted (header + source-file).
        tmp="$(mktemp)"
        awk '
            /^# jawn-tmux$/        { skip = 2; next }
            skip > 0               { skip--; next }
            { print }
        ' "$TMUX_CONF" > "$tmp" && mv "$tmp" "$TMUX_CONF"
        note "cleaned $TMUX_CONF"
    fi
    pip3 uninstall -y jawn-tmux 2>/dev/null || true
    echo "Uninstalled."
    exit 0
}

if [ "$ACTION" = "uninstall" ]; then uninstall; fi
if [ "$ACTION" != "install" ]; then err "unknown action: $ACTION"; fi

echo "Installing jawn-tmux from $REPO_DIR..."

require python3
require pip3
require tmux
command -v systemctl >/dev/null 2>&1 || warn "systemctl not found; the daemon will not auto-start"

# Check Python version.
python3 - <<'PY' || err "Python 3.11+ required"
import sys
sys.exit(0 if sys.version_info >= (3, 11) else 1)
PY

# Install Python package. Prefer --user; only fall back to
# --break-system-packages if PEP 668 is the actual reason pip refused. Keep
# --user on the fallback path so scripts land in ~/.local/bin (where the
# systemd unit looks for jtd) rather than the global /usr/local/bin.
PIP_LOG="$(mktemp)"
trap 'rm -f "$PIP_LOG"' EXIT
if pip3 install --user -e "$REPO_DIR" 2>"$PIP_LOG"; then
    cat "$PIP_LOG" >&2
elif grep -q 'externally-managed-environment' "$PIP_LOG"; then
    warn "PEP 668 lockdown detected; retrying with --user --break-system-packages"
    pip3 install --user --break-system-packages -e "$REPO_DIR"
else
    cat "$PIP_LOG" >&2
    err "pip install failed (see error above)"
fi

# Add tmux keybindings if not already present.
if ! grep -q 'jt.conf' "$TMUX_CONF" 2>/dev/null; then
    printf '\n# jawn-tmux\nsource-file "%s/tmux/jt.conf"\n' "$REPO_DIR" >> "$TMUX_CONF"
    note "added keybindings to $TMUX_CONF"
else
    note "keybindings already present in $TMUX_CONF"
fi

# Install systemd user service.
if command -v systemctl >/dev/null 2>&1; then
    mkdir -p "$SERVICE_DIR"
    cp "$REPO_DIR/systemd/jtd.service" "$SERVICE_FILE"
    systemctl --user daemon-reload
    systemctl --user enable jtd
    systemctl --user restart jtd
    note "installed and started $SERVICE_FILE"
fi

# Reload tmux config in any active session.
if tmux info >/dev/null 2>&1; then
    tmux source-file "$TMUX_CONF" && note "reloaded tmux config"
else
    note "no active tmux session — run 'tmux source ~/.tmux.conf' to load keybindings"
fi

echo
echo "Done."
echo "  jt status                 — show sessions"
echo "  Ctrl+B a                  — popup"
echo "  Ctrl+B Shift+A            — sidebar toggle"
echo
echo "Cross-node aggregation is off by default (jtd binds to 127.0.0.1)."
echo "To enable it, drop in an override and restart the daemon:"
echo "  systemctl --user edit jtd"
echo "  # add:"
echo "  [Service]"
echo "  Environment=JT_BIND=<your-tailscale-ip>"
echo "  # then:"
echo "  systemctl --user daemon-reload"
echo "  systemctl --user restart jtd"
echo
if ! command -v jt >/dev/null 2>&1; then
    echo "Note: 'jt' not on PATH. Add ~/.local/bin to PATH:"
    echo "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc && source ~/.bashrc"
fi
