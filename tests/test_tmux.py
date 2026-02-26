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


def test_new_session_returns_true_on_success():
    with patch('subprocess.run', return_value=make_result(returncode=0)):
        assert tmux.new_session('test', 'bash') is True


def test_kill_session_returns_false_on_failure():
    with patch('subprocess.run', return_value=make_result(returncode=1)):
        assert tmux.kill_session('nonexistent') is False


def test_has_session():
    with patch('subprocess.run', return_value=make_result(returncode=0)):
        assert tmux.has_session('main') is True
    with patch('subprocess.run', return_value=make_result(returncode=1)):
        assert tmux.has_session('gone') is False


def test_set_pane_style_calls_tmux():
    with patch('subprocess.run') as mock_run:
        tmux.set_pane_style('morning-wake', '0', '#3fb950')
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert 'select-pane' in args
    assert 'fg=#3fb950' in args
