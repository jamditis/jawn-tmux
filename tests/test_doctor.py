# tests/test_doctor.py
import json
import time
from unittest import mock

import pytest

from jt import doctor, state


@pytest.fixture
def state_file(tmp_path, monkeypatch):
    path = tmp_path / 'jt-state.json'
    monkeypatch.setattr(state, 'STATE_FILE', path)
    return path


def _write_state(path, **overrides):
    payload = {'node': 'testbox', 'updated_at': int(time.time()), 'sessions': {}}
    payload.update(overrides)
    path.write_text(json.dumps(payload))


def test_runtime_dir_ok_when_set(monkeypatch, tmp_path):
    monkeypatch.setenv('XDG_RUNTIME_DIR', str(tmp_path))
    level, msg = doctor._check_runtime_dir()
    assert level == 'ok'
    assert str(tmp_path) in msg


def test_runtime_dir_warn_when_missing(monkeypatch):
    monkeypatch.delenv('XDG_RUNTIME_DIR', raising=False)
    level, _ = doctor._check_runtime_dir()
    assert level == 'warn'


def test_runtime_dir_fail_when_path_missing(monkeypatch, tmp_path):
    monkeypatch.setenv('XDG_RUNTIME_DIR', str(tmp_path / 'does-not-exist'))
    level, _ = doctor._check_runtime_dir()
    assert level == 'fail'


def _patch_tmux_version(version_string: str):
    """Patch shutil.which + subprocess.run so doctor._check_tmux sees a
    fixed version output without touching the real tmux."""
    def fake_run(*args, **kwargs):
        return mock.MagicMock(stdout=version_string, returncode=0)
    return mock.patch.multiple(
        'jt.doctor',
        shutil=mock.MagicMock(which=mock.MagicMock(return_value='/usr/bin/tmux')),
        subprocess=mock.MagicMock(run=fake_run),
    )


def test_tmux_ok_on_3_2():
    """Format strings in pane-border-style — the mechanism this PR uses
    for status borders — landed in tmux 3.2."""
    with _patch_tmux_version('tmux 3.2\n'):
        level, msg = doctor._check_tmux()
    assert level == 'ok'
    assert '3.2' in msg


def test_tmux_ok_on_3_5():
    with _patch_tmux_version('tmux 3.5\n'):
        level, _ = doctor._check_tmux()
    assert level == 'ok'


def test_tmux_warn_on_3_1_format_strings_unsupported():
    """tmux 3.0/3.1 work for the status table and sidebar but the
    border-painting format strings won't evaluate, so the visual cue
    silently won't appear. Warn rather than fail — partial functionality
    is still useful."""
    with _patch_tmux_version('tmux 3.1c\n'):
        level, msg = doctor._check_tmux()
    assert level == 'warn'
    assert '3.2' in msg


def test_tmux_warn_on_3_0():
    with _patch_tmux_version('tmux 3.0\n'):
        level, _ = doctor._check_tmux()
    assert level == 'warn'


def test_tmux_fail_on_pre_3_0():
    with _patch_tmux_version('tmux 2.9a\n'):
        level, _ = doctor._check_tmux()
    assert level == 'fail'


def test_state_file_fresh_ok(state_file):
    _write_state(state_file)
    level, _ = doctor._check_state_file_fresh()
    assert level == 'ok'


def test_state_file_fresh_fail_when_missing(state_file, monkeypatch):
    # Ensure no alternate path muddies the diagnostic
    monkeypatch.setattr(doctor, '_alternate_state_paths', lambda: [])
    level, msg = doctor._check_state_file_fresh()
    assert level == 'fail'
    assert 'no state file' in msg


def test_state_file_fresh_diagnoses_xdg_mismatch(state_file, tmp_path, monkeypatch):
    """When the configured path is missing but a fresh state file exists at
    /tmp (or vice versa), the doctor should call out the XDG_RUNTIME_DIR
    mismatch explicitly with the suggested systemd unit fix.
    """
    alt = tmp_path / 'alt-jt-state.json'
    alt.write_text('{"updated_at": 1}')
    monkeypatch.setattr(doctor, '_alternate_state_paths', lambda: [alt])
    level, msg = doctor._check_state_file_fresh()
    assert level == 'fail'
    assert 'XDG_RUNTIME_DIR' in msg
    assert str(alt) in msg
    # Suggested fix must use systemd's %U specifier, not shell $(id -u),
    # because systemd Environment= directives do not expand subshells.
    assert '/run/user/%U' in msg
    assert '$(id -u)' not in msg


def test_state_file_fresh_fail_when_stale(state_file):
    _write_state(state_file, updated_at=int(time.time()) - 999)
    level, msg = doctor._check_state_file_fresh()
    assert level == 'fail'
    assert 'stale' in msg


def test_state_file_fresh_fail_when_corrupt(state_file):
    state_file.write_text('not json')
    level, msg = doctor._check_state_file_fresh()
    assert level == 'fail'
    assert 'unreadable' in msg


def test_tmp_readable_ok():
    level, _ = doctor._check_tmp_readable()
    assert level == 'ok'


def test_output_file_prefixes_ok_with_defaults(monkeypatch):
    monkeypatch.delenv('JT_OUTPUT_FILE_PREFIXES', raising=False)
    level, msg = doctor._check_output_file_prefixes()
    assert level == 'ok'
    assert 'claude_scheduled' in msg
    assert 'codex_scheduled' in msg


def test_output_file_prefixes_warn_when_env_overridden_to_blank(monkeypatch):
    monkeypatch.setenv('JT_OUTPUT_FILE_PREFIXES', '  ,  ')
    level, _ = doctor._check_output_file_prefixes()
    assert level == 'warn'


def test_port_ok_with_default(monkeypatch):
    monkeypatch.delenv('JT_PORT', raising=False)
    level, msg = doctor._check_port()
    assert level == 'ok'
    assert '6248' in msg


def test_port_warn_when_env_invalid(monkeypatch):
    monkeypatch.setenv('JT_PORT', 'not-a-number')
    level, _ = doctor._check_port()
    assert level == 'warn'


def test_bind_ok_loopback(monkeypatch):
    monkeypatch.delenv('JT_BIND', raising=False)
    level, _ = doctor._check_bind()
    assert level == 'ok'


def test_bind_warn_non_loopback(monkeypatch):
    monkeypatch.setenv('JT_BIND', '100.64.0.11')
    level, msg = doctor._check_bind()
    assert level == 'warn'
    assert '100.64.0.11' in msg


def test_daemon_http_brackets_ipv6_addresses(monkeypatch):
    """Probe URL must wrap IPv6 literals in brackets per RFC 3986;
    otherwise urllib mis-parses ::1:6248 as host '::1' port '6248' joined.
    """
    monkeypatch.setenv('JT_BIND', '::1')
    captured = {}

    class FakeResp:
        status = 200
        def read(self): return b'{}'
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(url, timeout):
        captured['url'] = url
        return FakeResp()

    monkeypatch.setattr(doctor.urllib.request, 'urlopen', fake_urlopen)
    level, _ = doctor._check_daemon_http()
    assert level == 'ok'
    assert captured['url'] == 'http://[::1]:6248/status'


def test_daemon_http_does_not_bracket_ipv4(monkeypatch):
    monkeypatch.setenv('JT_BIND', '127.0.0.1')

    class FakeResp:
        status = 200
        def read(self): return b'{}'
        def __enter__(self): return self
        def __exit__(self, *a): return False

    captured = {}
    def fake_urlopen(url, timeout):
        captured['url'] = url
        return FakeResp()

    monkeypatch.setattr(doctor.urllib.request, 'urlopen', fake_urlopen)
    doctor._check_daemon_http()
    assert captured['url'] == 'http://127.0.0.1:6248/status'


def test_last_error_ok_when_absent(state_file):
    _write_state(state_file)
    level, _ = doctor._check_last_error()
    assert level == 'ok'


def test_last_error_warn_when_recent(state_file):
    _write_state(state_file, last_error={'message': 'tmux gone', 'at': int(time.time()) - 10})
    level, msg = doctor._check_last_error()
    assert level == 'warn'
    assert 'tmux gone' in msg


def test_last_error_ok_when_old(state_file):
    _write_state(state_file, last_error={'message': 'old hiccup', 'at': int(time.time()) - 9999})
    level, msg = doctor._check_last_error()
    assert level == 'ok'
    assert 'old hiccup' in msg


def test_run_checks_returns_one_entry_per_check():
    results = doctor.run_checks()
    assert len(results) == len(doctor.CHECKS)
    names = [r['name'] for r, (n, _) in zip(results, doctor.CHECKS)]
    assert all(r['level'] in {'ok', 'warn', 'fail'} for r in results)


def test_run_checks_wraps_exceptions(monkeypatch):
    """A buggy check shouldn't take down the rest of the report."""
    def boom():
        raise RuntimeError('oops')
    monkeypatch.setattr(doctor, 'CHECKS', [('boom', boom), ('runtime_dir', doctor._check_runtime_dir)])
    results = doctor.run_checks()
    assert results[0] == {'name': 'boom', 'level': 'fail', 'message': 'check raised RuntimeError: oops'}
    assert results[1]['name'] == 'runtime_dir'


def test_exit_code_is_one_when_any_fails():
    assert doctor.exit_code([{'name': 'a', 'level': 'fail', 'message': 'x'}]) == 1
    assert doctor.exit_code([{'name': 'a', 'level': 'warn', 'message': 'x'}]) == 0
    assert doctor.exit_code([{'name': 'a', 'level': 'ok', 'message': 'x'}]) == 0


def test_format_human_aligns_check_names():
    out = doctor.format_human([
        {'name': 'short', 'level': 'ok', 'message': 'fine'},
        {'name': 'much_longer_name', 'level': 'fail', 'message': 'broken'},
    ])
    assert 'OK' in out
    assert 'FAIL' in out
    # Both rows should align at the same message column
    assert out.count('  ') >= 2
