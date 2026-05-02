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
