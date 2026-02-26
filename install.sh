#!/bin/bash
# install.sh — set up jawn-tmux on this machine
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
TMUX_CONF="$HOME/.tmux.conf"

echo "Installing jawn-tmux..."

# Install Python package
pip3 install --break-system-packages -e "$REPO_DIR"

# Add tmux keybindings if not already present
if ! grep -q 'jt.conf' "$TMUX_CONF" 2>/dev/null; then
    printf '\n# jawn-tmux\nsource-file %s/tmux/jt.conf\n' "$REPO_DIR" >> "$TMUX_CONF"
    echo "Added keybindings to $TMUX_CONF"
else
    echo "Keybindings already present in $TMUX_CONF"
fi

# Install systemd user service
SERVICE_DIR="$HOME/.config/systemd/user"
mkdir -p "$SERVICE_DIR"
cp "$REPO_DIR/systemd/jtd.service" "$SERVICE_DIR/jtd.service"
systemctl --user daemon-reload
systemctl --user enable jtd
systemctl --user start jtd

# Reload tmux config if a session exists
tmux source-file "$TMUX_CONF" 2>/dev/null \
    && echo "Reloaded tmux config" \
    || echo "No active tmux session — run 'tmux source ~/.tmux.conf' to load keybindings"

echo ""
echo "Done."
echo "  jt status       — show sessions"
echo "  Ctrl+B a        — popup"
echo "  Ctrl+B A        — sidebar toggle"
