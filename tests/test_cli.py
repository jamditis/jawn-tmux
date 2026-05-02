# tests/test_cli.py
import sys
from io import StringIO
from unittest.mock import patch
import pytest
from jt.cli import main


def run_jt(*args):
    with patch('sys.argv', ['jt', *args]):
        buf = StringIO()
        with patch('sys.stdout', buf):
            try:
                main()
            except SystemExit:
                pass
    return buf.getvalue()


def test_status_renders_table():
    fake = {
        'node': 'houseofjawn', 'updated_at': 0,
        'sessions': {'main': {'name': 'main', 'status': 'active',
                               'command': 'claude', 'elapsed_secs': 60,
                               'last_activity_secs': 5, 'output_tail': []}}
    }
    with patch('jt.state.read_state', return_value=fake):
        output = run_jt('status')
    assert 'main' in output


def test_default_is_status():
    with patch('jt.state.read_state', return_value={'node': 'n', 'updated_at': 0, 'sessions': {}}):
        output = run_jt()
    assert 'No sessions.' in output


def test_spawn_calls_new_session():
    with patch('jt.tmux.new_session', return_value=True) as mock:
        run_jt('spawn', 'test-session', 'bash')
    mock.assert_called_once_with('test-session', 'bash')


def test_kill_calls_kill_session():
    with patch('jt.tmux.kill_session', return_value=True) as mock:
        run_jt('kill', 'test-session')
    mock.assert_called_once_with('test-session')


def test_nodes_shows_local_and_skips_unreachable():
    fake_local = {'node': 'houseofjawn', 'updated_at': 0, 'sessions': {}}
    with patch('jt.state.read_state', return_value=fake_local), \
         patch('jt.nodes.load_nodes', return_value=[
             {'name': 'houseofjawn', 'ip': '100.64.0.11', 'port': 6248},
             {'name': 'officejawn',  'ip': '100.64.0.12',  'port': 6248},
         ]), \
         patch('jt.nodes.fetch_remote_state', return_value=None):
        output = run_jt('nodes')
    assert 'officejawn' in output and 'unreachable' in output


def test_nodes_renders_remote_state_when_reachable():
    fake_local = {'node': 'houseofjawn', 'updated_at': 0, 'sessions': {}}
    fake_remote = {
        'node': 'officejawn', 'updated_at': 0,
        'sessions': {'morning': {'name': 'morning', 'status': 'active',
                                  'command': 'claude', 'elapsed_secs': 30,
                                  'last_activity_secs': 1, 'output_tail': []}},
    }
    with patch('jt.state.read_state', return_value=fake_local), \
         patch('jt.nodes.load_nodes', return_value=[
             {'name': 'officejawn', 'ip': '100.64.0.12', 'port': 6248},
         ]), \
         patch('jt.nodes.fetch_remote_state', return_value=fake_remote):
        output = run_jt('nodes')
    assert 'officejawn' in output
    assert 'morning' in output


def test_attach_calls_tmux():
    with patch('subprocess.run') as mock:
        run_jt('attach', 'mysession')
    mock.assert_called_once_with(['tmux', 'attach', '-t', 'mysession'])


def _sidebar_fake_run(list_panes_stdout, split_pane_id='%9'):
    """Build a subprocess.run side-effect that mimics the tmux calls
    cmd_sidebar makes. ``list_panes_stdout`` is what
    ``tmux list-panes -F '#{pane_id} #{@jt_sidebar}'`` returns."""
    def fake_run(cmd, **kwargs):
        from unittest.mock import MagicMock
        r = MagicMock(returncode=0, stdout='', stderr='')
        if cmd[:3] == ['tmux', 'list-panes', '-F']:
            r.stdout = list_panes_stdout
        elif cmd[:2] == ['tmux', 'split-window']:
            r.stdout = split_pane_id + '\n'
        return r
    return fake_run


def test_sidebar_on_tags_new_pane_via_user_option():
    """The new pane has to be tagged via ``set-option -p @jt_sidebar 1``,
    using the pane id returned from ``split-window -P -F``. Pane titles
    (the previous tag mechanism) get clobbered by shell escape sequences,
    and ``select-pane -T`` without ``-t`` targets the *current* pane —
    not the just-spawned one — when split-window was invoked with -d."""
    calls = []
    def recording(cmd, **kwargs):
        calls.append(list(cmd))
        return _sidebar_fake_run('', '%9')(cmd, **kwargs)
    with patch('subprocess.run', side_effect=recording):
        run_jt('sidebar', 'on')
    set_option_calls = [c for c in calls if c[:2] == ['tmux', 'set-option']]
    assert any(c[4] == '%9' and c[5] == '@jt_sidebar' and c[6] == '1'
               for c in set_option_calls)


def test_sidebar_off_kills_pane_tagged_jt_sidebar():
    """When the sidebar exists, ``jt sidebar off`` finds it via the user
    option and kills exactly that pane id — not "any pane whose title
    contains 'jt-sidebar'", which never matched in practice."""
    calls = []
    def recording(cmd, **kwargs):
        calls.append(list(cmd))
        return _sidebar_fake_run('%0 \n%9 1\n')(cmd, **kwargs)
    with patch('subprocess.run', side_effect=recording):
        run_jt('sidebar', 'off')
    kill_calls = [c for c in calls if c[:2] == ['tmux', 'kill-pane']]
    assert kill_calls == [['tmux', 'kill-pane', '-t', '%9']]


def test_sidebar_toggle_opens_when_absent_and_closes_when_present():
    # Absent → on
    calls_a = []
    def rec_a(cmd, **kwargs):
        calls_a.append(list(cmd))
        return _sidebar_fake_run('%0 \n', '%9')(cmd, **kwargs)
    with patch('subprocess.run', side_effect=rec_a):
        run_jt('sidebar', 'toggle')
    assert any(c[:2] == ['tmux', 'split-window'] for c in calls_a)

    # Present → off
    calls_b = []
    def rec_b(cmd, **kwargs):
        calls_b.append(list(cmd))
        return _sidebar_fake_run('%0 \n%9 1\n')(cmd, **kwargs)
    with patch('subprocess.run', side_effect=rec_b):
        run_jt('sidebar', 'toggle')
    assert any(c[:2] == ['tmux', 'kill-pane'] for c in calls_b)
