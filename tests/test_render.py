# tests/test_render.py
from jt import render


def test_format_elapsed_seconds():
    assert render.format_elapsed(45) == '45s'


def test_format_elapsed_minutes():
    assert render.format_elapsed(90) == '1m'


def test_format_elapsed_hours():
    assert render.format_elapsed(3720) == '1h2m'


def test_render_table_no_sessions():
    assert render.render_table({}) == 'No sessions.'
    assert render.render_table({'sessions': {}}) == 'No sessions.'


def test_render_table_contains_session_name():
    data = {
        'node': 'houseofjawn', 'updated_at': 1740000000,
        'sessions': {
            'main': {
                'name': 'main', 'status': 'active', 'command': 'claude',
                'elapsed_secs': 120, 'last_activity_secs': 5, 'output_tail': [],
            }
        }
    }
    output = render.render_table(data)
    assert 'main' in output
    assert 'active' in output
    assert 'houseofjawn' in output


def test_render_table_includes_output_tail():
    data = {
        'node': 'houseofjawn', 'updated_at': 1740000000,
        'sessions': {
            'morning-wake': {
                'name': 'morning-wake', 'status': 'silent', 'command': 'claude',
                'elapsed_secs': 300, 'last_activity_secs': 45,
                'output_tail': ['Checking email...', 'Found 1 transcript.'],
            }
        }
    }
    output = render.render_table(data)
    assert 'Checking email...' in output
    assert 'Found 1 transcript.' in output


def test_render_table_all_statuses_no_crash():
    for status in ('active', 'silent', 'done', 'error'):
        data = {
            'node': 'test', 'updated_at': 0,
            'sessions': {
                'test-wake': {
                    'name': 'test-wake', 'status': status, 'command': 'bash',
                    'elapsed_secs': 10, 'last_activity_secs': 5, 'output_tail': [],
                }
            }
        }
        render.render_table(data)  # should not raise
