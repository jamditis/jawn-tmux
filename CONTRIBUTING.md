# Contributing to jawn-tmux

Thanks for your interest. Contributions are welcome — bug reports, feature requests, and pull requests.

## Quick start

```bash
git clone https://github.com/jamditis/jawn-tmux.git
cd jawn-tmux

# Editable install. On PEP 668 systems (recent Debian/Ubuntu) pip will
# refuse with "error: externally-managed-environment" — in that case add
# --break-system-packages to the same command. install.sh does this
# fallback automatically, but only on that specific error string.
pip3 install --user -e .

python3 -m pytest -v
```

All tests should pass — no third-party runtime deps. Test count grows over time; `python3 -m pytest -v | tail -1` shows the current total.

## Ground rules

- **stdlib only** — no third-party runtime dependencies. The whole point is that it just works.
- **TDD** — write a failing test before implementing anything. The existing tests show the pattern.
- **No breaking changes to the state schema** — `/tmp/jt-state.json` is read by both `jt` and remote nodes. Adding new keys is fine; removing or renaming existing ones is not.
- **`main` session is untouched** — the daemon never modifies the `main` session's pane border. Keep it that way.

## Submitting a PR

1. Fork and create a branch from `master`
2. Write tests for your change
3. Run `python3 -m pytest -v` — all tests must pass
4. Keep commits focused and messages clear
5. Open a PR with a description of what and why

## Reporting a bug

Use the [bug report template](.github/ISSUE_TEMPLATE/bug_report.md). Include:
- OS and architecture (arm64 / x86_64 / WSL2)
- tmux version (`tmux -V`)
- Python version (`python3 --version`)
- The output of `systemctl --user status jtd`
- Contents of `/tmp/jt-state.json` if the daemon is running

## Requesting a feature

Use the [feature request template](.github/ISSUE_TEMPLATE/feature_request.md). Describe the use case, not just the implementation.

## Code style

- Follow existing patterns in each module
- Short, factual log messages — no decoration
- Sentence case in all user-facing text
- No emojis in source code or log output
