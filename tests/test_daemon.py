# tests/test_daemon.py
import os
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
    monkeypatch.setattr('jt.tmux.list_session_panes',
                        lambda name: [{'id': '%5', 'command': 'sleep'}])
    monkeypatch.setattr('jt.tmux.set_pane_status_color',
                        lambda pid, c: calls.append((pid, c)) or True)
    prev = {'morning-wake': {'status': 'active'}}
    curr = {'morning-wake': {'status': 'silent', 'command': 'claude'}}
    daemon._update_borders(prev, curr)
    assert calls == [('%5', '#d29922')]


def test_update_borders_paints_all_panes_in_multi_window_session(monkeypatch):
    """Sessions can have multiple windows (and panes within them). The
    painter must enumerate the whole session via list_session_panes so
    a multi-window agent run shows consistent border color across all
    windows, not just the current one."""
    calls = []
    monkeypatch.setattr('jt.tmux.list_session_panes',
                        lambda name: [
                            {'id': '%5', 'command': 'claude'},
                            {'id': '%6', 'command': 'tail'},
                            {'id': '%7', 'command': 'bash'},
                        ])
    monkeypatch.setattr('jt.tmux.set_pane_status_color',
                        lambda pid, c: calls.append((pid, c)) or True)
    prev = {'morning-wake': {'status': 'active'}}
    curr = {'morning-wake': {'status': 'done', 'command': 'claude'}}
    daemon._update_borders(prev, curr)
    assert calls == [('%5', '#484f58'), ('%6', '#484f58'), ('%7', '#484f58')]


def test_update_borders_skips_main(monkeypatch):
    calls = []
    monkeypatch.setattr('jt.tmux.list_session_panes',
                        lambda name: [{'id': '%5', 'command': 'claude'}])
    monkeypatch.setattr('jt.tmux.set_pane_status_color',
                        lambda pid, c: calls.append(pid) or True)
    daemon._update_borders({}, {'main': {'status': 'active', 'command': 'claude'}})
    assert calls == []


def test_update_borders_skips_when_session_has_no_panes(monkeypatch):
    """If a session vanishes between status read and border paint, skip
    quietly — better than tmux returning an error we then log loudly."""
    calls = []
    monkeypatch.setattr('jt.tmux.list_session_panes', lambda name: [])
    monkeypatch.setattr('jt.tmux.set_pane_status_color',
                        lambda pid, c: calls.append(pid) or True)
    prev = {'morning-wake': {'status': 'active'}}
    curr = {'morning-wake': {'status': 'silent', 'command': 'claude'}}
    daemon._update_borders(prev, curr)
    assert calls == []


def test_update_borders_skips_unchanged(monkeypatch):
    calls = []
    monkeypatch.setattr('jt.tmux.list_session_panes',
                        lambda name: [{'id': '%5', 'command': 'claude'}])
    monkeypatch.setattr('jt.tmux.set_pane_status_color',
                        lambda pid, c: calls.append(pid) or True)
    prev = {'morning-wake': {'status': 'silent'}}
    curr = {'morning-wake': {'status': 'silent', 'command': 'claude'}}
    daemon._update_borders(prev, curr)
    assert calls == []


def test_update_borders_logs_on_paint_failure(monkeypatch, caplog):
    """Paint failures (rare — usually a race where the pane vanished mid-poll)
    must surface in the journal. Previously the daemon ignored
    set_pane_style's return value, so a config bug that broke painting
    on every call was invisible."""
    monkeypatch.setattr('jt.tmux.list_session_panes',
                        lambda name: [{'id': '%5', 'command': 'claude'}])
    monkeypatch.setattr('jt.tmux.set_pane_status_color', lambda pid, c: False)
    prev = {'morning-wake': {'status': 'active'}}
    curr = {'morning-wake': {'status': 'silent', 'command': 'claude'}}
    with caplog.at_level('WARNING', logger='jtd'):
        daemon._update_borders(prev, curr)
    assert any('failed to paint' in r.message for r in caplog.records)


def _patch_glob_to_tmp(monkeypatch, tmp_path):
    """Redirect daemon's glob.glob('/tmp/<prefix>_*.txt') calls into tmp_path."""
    real_glob = daemon.glob.glob

    def fake_glob(pattern):
        if pattern.startswith('/tmp/'):
            return real_glob(str(tmp_path / pattern[len('/tmp/'):]))
        return real_glob(pattern)

    monkeypatch.setattr(daemon.glob, 'glob', fake_glob)


def test_find_output_file_matches_claude_scheduled_default(monkeypatch, tmp_path):
    _patch_glob_to_tmp(monkeypatch, tmp_path)
    created = 1740000000
    log = tmp_path / f'claude_scheduled_{created}.txt'
    log.write_text('hello\n')
    assert daemon._find_output_file(created) == str(log)


def test_find_output_file_matches_codex_scheduled_default(monkeypatch, tmp_path):
    _patch_glob_to_tmp(monkeypatch, tmp_path)
    created = 1740000000
    log = tmp_path / f'codex_scheduled_{created}.txt'
    log.write_text('hello\n')
    assert daemon._find_output_file(created) == str(log)


def test_find_output_file_rejects_outside_60s_window(monkeypatch, tmp_path):
    _patch_glob_to_tmp(monkeypatch, tmp_path)
    log = tmp_path / 'claude_scheduled_1740000000.txt'
    log.write_text('hello\n')
    assert daemon._find_output_file(1740000061) is None
    assert daemon._find_output_file(1740000059) == str(log)


def test_find_output_file_picks_most_recent_when_multiple_prefixes_match(monkeypatch, tmp_path):
    _patch_glob_to_tmp(monkeypatch, tmp_path)
    created = 1740000000
    older = tmp_path / f'claude_scheduled_{created}.txt'
    newer = tmp_path / f'codex_scheduled_{created}.txt'
    older.write_text('older\n')
    newer.write_text('newer\n')
    os_utime_older = (older.stat().st_atime, older.stat().st_mtime - 100)
    os.utime(older, os_utime_older)
    assert daemon._find_output_file(created) == str(newer)


def test_find_output_file_respects_env_override(monkeypatch, tmp_path):
    _patch_glob_to_tmp(monkeypatch, tmp_path)
    monkeypatch.setenv('JT_OUTPUT_FILE_PREFIXES', 'my_runner')
    created = 1740000000
    claude_log = tmp_path / f'claude_scheduled_{created}.txt'
    claude_log.write_text('default prefix\n')
    custom_log = tmp_path / f'my_runner_{created}.txt'
    custom_log.write_text('custom prefix\n')
    assert daemon._find_output_file(created) == str(custom_log)


def test_resolve_output_file_prefixes_ignores_blank_entries(monkeypatch):
    monkeypatch.setenv('JT_OUTPUT_FILE_PREFIXES', '  , ,  ')
    assert daemon._resolve_output_file_prefixes() == daemon.DEFAULT_OUTPUT_FILE_PREFIXES


def test_should_clear_last_error_false_when_none():
    assert daemon._should_clear_last_error(None, time.time()) is False


def test_should_clear_last_error_false_when_inside_visibility_window():
    now = time.time()
    err = {'message': 'x', 'at': int(now - 30)}
    assert daemon._should_clear_last_error(err, now) is False


def test_should_clear_last_error_true_after_visibility_window():
    now = time.time()
    err = {'message': 'x', 'at': int(now - daemon.LAST_ERROR_VISIBILITY_SECS - 10)}
    assert daemon._should_clear_last_error(err, now) is True


def test_should_clear_last_error_handles_missing_at_key():
    """Defensive: malformed last_error without 'at' should still clear,
    not raise. A missing 'at' is treated as epoch 0 so age is huge."""
    assert daemon._should_clear_last_error({'message': 'orphaned'}, time.time()) is True
