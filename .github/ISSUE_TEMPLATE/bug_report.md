---
name: Bug report
about: Something isn't working correctly
labels: bug
---

**Describe the bug**
A clear description of what went wrong.

**To reproduce**
Steps to reproduce the behavior.

**Expected behavior**
What you expected to happen.

**Environment**
- OS and architecture: <!-- e.g. Raspberry Pi OS Bookworm, arm64 -->
- tmux version: <!-- tmux -V -->
- Python version: <!-- python3 --version -->
- jawn-tmux version: <!-- git describe --tags -->

**Daemon status**
```
paste output of: systemctl --user status jtd
```

**State file**
```json
paste contents of: cat /tmp/jt-state.json
```

**Additional context**
Any other relevant information.
