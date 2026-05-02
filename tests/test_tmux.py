# tests/test_tmux.py
from unittest.mock import patch, MagicMock
from jt import tmux


def make_result(stdout='', returncode=0):
    r = MagicMock()
    r.stdout = stdout
    r.returncode = returncode
    return r


def test_list_sessions_parses_output():
    output = "main\t1740000000\t1740000100\nmorning-wake\t1740001000\t1740001200\n"
    with patch('subprocess.run', return_value=make_result(output)):
        sessions = tmux.list_sessions()
    assert len(sessions) == 2
    assert sessions[0]['name'] == 'main'
    assert sessions[0]['created'] == 1740000000
    assert sessions[1]['name'] == 'morning-wake'


def test_list_sessions_empty_on_error():
    with patch('subprocess.run', return_value=make_result(returncode=1)):
        assert tmux.list_sessions() == []


def test_list_panes_parses_output():
    output = "%0\tclaude\n"
    with patch('subprocess.run', return_value=make_result(output)):
        panes = tmux.list_panes('morning-wake')
    assert panes[0] == {'id': '%0', 'command': 'claude'}


def test_list_panes_does_not_use_dash_s():
    """list_panes is window-scoped — used for command labeling in the
    status table where 'first pane in current window' is the right
    representative. Border painting needs all session panes, which goes
    through list_session_panes instead."""
    with patch('subprocess.run', return_value=make_result('')) as mock_run:
        tmux.list_panes('morning-wake')
    args = mock_run.call_args[0][0]
    assert '-s' not in args


def test_list_session_panes_uses_dash_s():
    """tmux list-panes without -s only returns panes in the current
    window of the target session. Sessions with multiple windows would
    have their other-window panes silently skipped during border paints,
    so the painter uses -s to enumerate the full session."""
    output = "%0\tclaude\n%5\tbash\n"
    with patch('subprocess.run', return_value=make_result(output)) as mock_run:
        panes = tmux.list_session_panes('morning-wake')
    args = mock_run.call_args[0][0]
    assert args[:3] == ['tmux', 'list-panes', '-s']
    assert '-t' in args and 'morning-wake' in args
    assert [p['id'] for p in panes] == ['%0', '%5']


def test_list_session_panes_returns_empty_on_failure():
    with patch('subprocess.run', return_value=make_result(returncode=1)):
        assert tmux.list_session_panes('gone') == []


def test_first_pane_id_returns_first_pane():
    with patch('subprocess.run', return_value=make_result('%7\tbash\n')):
        assert tmux.first_pane_id('morning-wake') == '%7'


def test_first_pane_id_returns_none_when_empty():
    with patch('subprocess.run', return_value=make_result('')):
        assert tmux.first_pane_id('gone') is None


def test_new_session_returns_true_on_success():
    with patch('subprocess.run', return_value=make_result(returncode=0)):
        assert tmux.new_session('test', 'bash') is True


def test_new_session_passes_command_as_single_arg():
    """Shell syntax (loops, pipes, ``&&``) must reach tmux intact so it
    can run the command through /bin/sh -c. Splitting via shlex would
    shatter ``while``/``do``/``done`` into separate argv entries that
    tmux tries to exec literally and fails."""
    with patch('subprocess.run', return_value=make_result(returncode=0)) as mock_run:
        tmux.new_session('s', 'while true; do echo x; sleep 1; done')
    args = mock_run.call_args[0][0]
    assert args[-1] == 'while true; do echo x; sleep 1; done'


def test_kill_session_returns_false_on_failure():
    with patch('subprocess.run', return_value=make_result(returncode=1)):
        assert tmux.kill_session('nonexistent') is False


def test_has_session():
    with patch('subprocess.run', return_value=make_result(returncode=0)):
        assert tmux.has_session('main') is True
    with patch('subprocess.run', return_value=make_result(returncode=1)):
        assert tmux.has_session('gone') is False


def test_set_pane_status_color_uses_per_pane_user_option():
    """The daemon paints status by writing @jt_status_fg on the pane;
    jt.conf reads that option in pane-border-style so the border updates.
    The previous ``select-pane -P fg=`` approach set pane content fg, not
    the border, and silently failed when the target window index was
    rejected (e.g. ``base-index 1`` configs)."""
    with patch('subprocess.run', return_value=make_result(returncode=0)) as mock_run:
        result = tmux.set_pane_status_color('%5', '#3fb950')
    args = mock_run.call_args[0][0]
    assert args[:4] == ['tmux', 'set-option', '-p', '-t']
    assert args[4] == '%5'
    assert args[5] == '@jt_status_fg'
    assert args[6] == '#3fb950'
    assert result is True


def test_set_pane_status_color_returns_false_on_failure():
    with patch('subprocess.run', return_value=make_result(returncode=1)):
        assert tmux.set_pane_status_color('%5', '#3fb950') is False
