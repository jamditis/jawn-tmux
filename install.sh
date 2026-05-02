#!/usr/bin/env bash
# install.sh — set up jawn-tmux on this machine.
#   ./install.sh            install (default)
#   ./install.sh check      run jt doctor without installing
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

check() {
    # Resolve the jt entrypoint without requiring PATH — the common
    # first-install case is "pip put jt in ~/.local/bin but the shell
    # hasn't been reloaded yet", so PATH-only lookup defeats the
    # purpose of the action.
    if command -v jt >/dev/null 2>&1; then
        exec jt doctor
    fi
    if [ -x "$HOME/.local/bin/jt" ]; then
        exec "$HOME/.local/bin/jt" doctor
    fi
    err "'jt' not found in PATH or ~/.local/bin. Run './install.sh' first."
}

if [ "$ACTION" = "uninstall" ]; then uninstall; fi
if [ "$ACTION" = "check" ]; then check; fi
if [ "$ACTION" != "install" ]; then err "unknown action: $ACTION (try install, check, or uninstall)"; fi

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

# Check tmux version. Status-border format strings need 3.2+; older
# tmuxes can still run the status table, sidebar, and HTTP probe, so
# warn rather than abort.
tmux_version="$(tmux -V | sed -E 's/^tmux ([0-9]+\.[0-9]+).*/\1/')"
if [ -n "$tmux_version" ]; then
    tmux_major="${tmux_version%%.*}"
    tmux_minor="${tmux_version##*.}"
    if [ "$tmux_major" -lt 3 ] || { [ "$tmux_major" -eq 3 ] && [ "$tmux_minor" -lt 2 ]; }; then
        warn "tmux $tmux_version detected; status borders need 3.2+ (other features still work)"
    fi
fi

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

# Reload tmux config in any active server. ``tmux info`` requires a
# *client* context which a subshell doesn't have even when $TMUX is set,
# so it reported "no active session" inside running tmux panes;
# ``tmux ls`` only needs a server.
if tmux ls >/dev/null 2>&1; then
    tmux source-file "$TMUX_CONF" && note "reloaded tmux config"
else
    note "no tmux server running — start tmux to pick up the new keybindings"
fi

echo
echo "Done."

# PATH note before any jt commands so the user isn't told to "run jt status"
# while jt isn't reachable. ~/.local/bin is what pip --user installs into;
# distros that don't include it on the default PATH (Debian / Ubuntu without
# a login-shell init) need a manual append.
if ! command -v jt >/dev/null 2>&1; then
    warn "'jt' not on PATH (pip installed it under ~/.local/bin)"
    note "add it now:"
    note "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc && source ~/.bashrc"
    echo
fi

# Smoke check — surface any warnings or fails up front so a failed install
# isn't masked by the "Done." line. Re-runnable as ./install.sh check or jt doctor.
# Capture jt doctor's exit code so the installer's own exit reflects health:
# automated upgrade scripts and CI can then detect a green-pip / red-doctor
# install without parsing stdout.
DOCTOR_EXIT=0
if command -v jt >/dev/null 2>&1; then
    echo "Smoke check (jt doctor):"
    DOCTOR_OUT="$(jt doctor 2>&1)" || DOCTOR_EXIT=$?
    printf '%s\n' "$DOCTOR_OUT" | sed 's/^/  /'
    echo
    if [ "$DOCTOR_EXIT" -ne 0 ]; then
        warn "doctor reported failures — install completed, but health check did not pass"
        echo
    fi
fi

echo "Try:"
echo "  jt status                 — show sessions"
echo "  Ctrl+B a                  — popup"
echo "  Ctrl+B Shift+A            — sidebar toggle"
echo
echo "Re-run health checks anytime:"
echo "  jt doctor                 (or ./install.sh check from this directory)"
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

# Propagate the doctor's exit so callers (CI, upgrade scripts) see
# "install + health" as one combined status. pip + service install
# already succeeded by the time we get here; only doctor can flip this.
exit "$DOCTOR_EXIT"
