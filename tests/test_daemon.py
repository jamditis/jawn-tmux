# tests/test_daemon.py
import time
from pathlib import Path
import pytest
from jt import daemon


@pytest.fixture
def output_file(tmp_path):
    return tmp_path / 'claude_scheduled_1740000000.txt'


def test_compute_status_active_when_recent_output():
    session = {'last_activity': time.time() - 5, 'output_file': None}
    assert daemon.compute_session_status(session, time.time()) == 'active'


def test_compute_status_silent_after_threshold():
    session = {'last_activity': time.time() - 25, 'output_file': None}
    assert daemon.compute_session_status(session, time.time()) == 'silent'


def test_compute_status_done_from_marker(output_file):
    output_file.write_text('some output\nCLAUDE_TASK_COMPLETE:0\n')
    session = {'last_activity': time.time() - 30, 'output_file': str(output_file)}
    assert daemon.compute_session_status(session, time.time()) == 'done'


def test_compute_status_error_from_nonzero_marker(output_file):
    output_file.write_text('some output\nCLAUDE_TASK_COMPLETE:1\n')
    session = {'last_activity': time.time() - 30, 'output_file': str(output_file)}
    assert daemon.compute_session_status(session, time.time()) == 'error'


def test_read_output_tail_returns_last_lines(output_file):
    output_file.write_text('line1\nline2\nline3\nline4\nline5\n')
    result = daemon._read_output_tail(str(output_file))
    assert result == ['line3', 'line4', 'line5']


def test_read_output_tail_skips_blank_lines(output_file):
    output_file.write_text('line1\n\nline2\n\nline3\n')
    result = daemon._read_output_tail(str(output_file))
    assert result == ['line1', 'line2', 'line3']


def test_read_output_tail_missing_file():
    assert daemon._read_output_tail('/nonexistent/file.txt') == []


def test_update_borders_calls_set_pane_on_status_change(monkeypatch):
    calls = []
    monkeypatch.setattr('jt.tmux.set_pane_style', lambda s, p, c: calls.append((s, c)))
    prev = {'morning-wake': {'status': 'active'}}
    curr = {'morning-wake': {'status': 'silent', 'command': 'claude'}}
    daemon._update_borders(prev, curr)
    assert len(calls) == 1
    assert calls[0] == ('morning-wake', '#d29922')


def test_update_borders_skips_main(monkeypatch):
    calls = []
    monkeypatch.setattr('jt.tmux.set_pane_style', lambda s, p, c: calls.append(s))
    daemon._update_borders({}, {'main': {'status': 'active', 'command': 'claude'}})
    assert calls == []


def test_update_borders_skips_unchanged(monkeypatch):
    calls = []
    monkeypatch.setattr('jt.tmux.set_pane_style', lambda s, p, c: calls.append(s))
    prev = {'morning-wake': {'status': 'silent'}}
    curr = {'morning-wake': {'status': 'silent', 'command': 'claude'}}
    daemon._update_borders(prev, curr)
    assert calls == []
