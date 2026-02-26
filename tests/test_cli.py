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
             {'name': 'houseofjawn', 'ip': '100.122.208.15', 'port': 6248},
             {'name': 'officejawn',  'ip': '100.84.214.24',  'port': 6248},
         ]), \
         patch('jt.nodes.fetch_remote_state', return_value=None):
        output = run_jt('nodes')
    assert 'officejawn' in output or 'unreachable' in output


def test_attach_calls_tmux():
    with patch('subprocess.run') as mock:
        run_jt('attach', 'mysession')
    mock.assert_called_once_with(['tmux', 'attach', '-t', 'mysession'])
