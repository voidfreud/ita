"""Tests for _overview.py: overview command."""
import json
import sys
import pytest
from jsonschema import validate

sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent))
from conftest import ita, ita_ok

pytestmark = pytest.mark.integration

# ── JSON schema ───────────────────────────────────────────────────────────────

SESSION_ENTRY_SCHEMA = {
	'type': 'object',
	'required': ['session_id', 'session_name', 'process', 'path', 'window_id', 'tab_id', 'is_current', 'lines'],
}

TAB_ENTRY_SCHEMA = {
	'type': 'object',
	'required': ['tab_id', 'sessions'],
}

WINDOW_ENTRY_SCHEMA = {
	'type': 'object',
	'required': ['window_id', 'tabs'],
}

OVERVIEW_SCHEMA = {
	'type': 'object',
	'required': ['windows', 'tmux'],
	'properties': {
		'windows': {'type': 'array'},
		'tmux': {'type': 'array'},
	},
}

# ── happy path ────────────────────────────────────────────────────────────────

def test_overview_exits_zero(shared_session):
	r = ita('overview')
	assert r.returncode == 0


@pytest.mark.contract
def test_overview_json_schema(shared_session):
	out = ita_ok('overview', '--json')
	data = json.loads(out)
	validate(instance=data, schema=OVERVIEW_SCHEMA)
	assert isinstance(data['windows'], list)
	assert isinstance(data['tmux'], list)


@pytest.mark.contract
def test_overview_json_nested_structure(shared_session):
	data = json.loads(ita_ok('overview', '--json'))
	for w in data['windows']:
		validate(instance=w, schema=WINDOW_ENTRY_SCHEMA)
		for t in w['tabs']:
			validate(instance=t, schema=TAB_ENTRY_SCHEMA)
			for s in t['sessions']:
				validate(instance=s, schema=SESSION_ENTRY_SCHEMA)


def test_overview_contains_known_session(shared_session):
	data = json.loads(ita_ok('overview', '--json'))
	all_sids = [
		s['session_id']
		for w in data['windows']
		for t in w['tabs']
		for s in t['sessions']
	]
	assert shared_session in all_sids

# ── edge ──────────────────────────────────────────────────────────────────────

@pytest.mark.edge
def test_overview_lines_zero(shared_session):
	out = ita_ok('overview', '--lines', '0', '--json')
	data = json.loads(out)
	# lines key must be present but empty when --lines 0
	for w in data['windows']:
		for t in w['tabs']:
			for s in t['sessions']:
				assert s.get('lines') == []


@pytest.mark.edge
def test_overview_no_preview_flag(shared_session):
	out = ita_ok('overview', '--no-preview', '--json')
	data = json.loads(out)
	for w in data['windows']:
		for t in w['tabs']:
			for s in t['sessions']:
				assert s.get('lines') == []


@pytest.mark.edge
def test_overview_where_filter_no_match(shared_session):
	out = ita_ok('overview', '--where', 'session_name=__no_match_xyz__', '--json')
	data = json.loads(out)
	# Windows/tabs with no matching sessions are dropped
	all_sids = [
		s['session_id']
		for w in data['windows']
		for t in w['tabs']
		for s in t['sessions']
	]
	assert all_sids == []


@pytest.mark.edge
def test_overview_lines_multiple(shared_session):
	r = ita('overview', '--lines', '5', '--json')
	assert r.returncode == 0
	data = json.loads(r.stdout)
	# lines key is a list — may or may not have content but must be a list
	for w in data['windows']:
		for t in w['tabs']:
			for s in t['sessions']:
				assert isinstance(s.get('lines'), list)


# ── contract ──────────────────────────────────────────────────────────────────

@pytest.mark.contract
def test_overview_plain_text_contains_window(shared_session):
	out = ita_ok('overview')
	assert 'Window' in out


@pytest.mark.contract
def test_overview_json_no_ansi(shared_session):
	out = ita_ok('overview', '--json')
	assert '\x1b[' not in out, "ANSI escape leaked into --json output"
	assert '\x00' not in out, "Null byte leaked into --json output"
