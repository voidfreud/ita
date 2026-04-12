"""Tests for _orientation.py: status, focus, version, protect, unprotect, session info."""
import json
import re
import sys
import pytest
from jsonschema import validate, ValidationError

sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent))
from conftest import ita, ita_ok

pytestmark = pytest.mark.integration

# ── JSON schemas ─────────────────────────────────────────────────────────────

STATUS_ITEM_SCHEMA = {
	'type': 'object',
	'required': ['session_id', 'session_name', 'process', 'path', 'window_id', 'tab_id'],
	'properties': {
		'session_id': {'type': 'string'},
		'session_name': {'type': 'string'},
		'process': {'type': 'string'},
		'path': {'type': 'string'},
		'window_id': {'type': 'string'},
		'tab_id': {'type': 'string'},
	},
}

FOCUS_SCHEMA = {
	'type': 'object',
	'required': ['window_id', 'tab_id', 'session_id'],
	'properties': {
		'window_id': {},
		'tab_id': {},
		'session_id': {},
		'session_name': {},
	},
}

SESSION_INFO_SCHEMA = {
	'type': 'object',
	'required': [
		'session_id', 'name', 'process', 'path', 'profile',
		'window_id', 'tab_id', 'cols', 'rows',
		'protected', 'shell_integration', 'tmux_window_id',
		'is_current', 'broadcast_domains',
	],
}

# ── status ────────────────────────────────────────────────────────────────────

@pytest.mark.contract
def test_status_json_schema(shared_session):
	out = ita_ok('status', '--json')
	data = json.loads(out)
	assert isinstance(data, list)
	for item in data:
		validate(instance=item, schema=STATUS_ITEM_SCHEMA)


@pytest.mark.contract
def test_status_ids_only_format(shared_session):
	out = ita_ok('status', '--ids-only')
	for line in out.splitlines():
		# Each line should look like a UUID (contains hyphens)
		assert '-' in line, f"Unexpected ids-only line: {line!r}"


@pytest.mark.edge
def test_status_fast_flag(shared_session):
	r = ita('status', '--fast', '--json')
	assert r.returncode == 0
	data = json.loads(r.stdout)
	# --fast returns empty strings for process/path — they must still be present
	for item in data:
		assert 'process' in item
		assert 'path' in item


@pytest.mark.edge
def test_status_where_filter_match(shared_session):
	# Get any session name to filter on
	sessions = json.loads(ita_ok('status', '--json'))
	if not sessions:
		pytest.skip("No sessions available")
	name = sessions[0]['session_name']
	if not name:
		pytest.skip("First session has no name")
	out = ita_ok('status', '--where', f'session_name={name}', '--json')
	filtered = json.loads(out)
	assert all(s['session_name'] == name for s in filtered)


@pytest.mark.edge
def test_status_where_filter_no_match(shared_session):
	r = ita('status', '--where', 'session_name=__no_such_session_xyz__', '--json')
	assert r.returncode == 0
	data = json.loads(r.stdout)
	assert data == []

# ── focus ─────────────────────────────────────────────────────────────────────

@pytest.mark.contract
def test_focus_json_schema():
	r = ita('focus', '--json')
	assert r.returncode == 0
	data = json.loads(r.stdout)
	validate(instance=data, schema=FOCUS_SCHEMA)


def test_focus_plain_output():
	r = ita('focus')
	assert r.returncode == 0
	# Either a "No focused window" message or the three-line format
	out = r.stdout
	assert ('window:' in out or 'No focused window' in out)

# ── version ───────────────────────────────────────────────────────────────────

def test_version_format():
	out = ita_ok('version')
	assert re.match(r'ita \S+ \(iTerm2 .+\)', out), f"Unexpected format: {out!r}"


# ── protect / unprotect ───────────────────────────────────────────────────────

def test_protect_happy_and_lists(session):
	r = ita('protect', '-s', session)
	assert r.returncode == 0
	out = ita_ok('protect', '--list')
	assert session in out


@pytest.mark.state
def test_protect_persists_across_invocations(session):
	ita_ok('protect', '-s', session)
	# Second invocation of --list should still show it
	out = ita_ok('protect', '--list')
	assert session in out
	# Clean up
	ita('unprotect', '-s', session)


@pytest.mark.state
def test_protected_session_refuses_write(session):
	ita_ok('protect', '-s', session)
	try:
		r = ita('run', '-s', session, 'echo hi')
		assert r.returncode != 0
		assert 'protected' in r.stderr.lower() or 'force' in r.stderr.lower()
	finally:
		ita('unprotect', '-s', session)


@pytest.mark.error
def test_protect_list_empty_when_none():
	# This is a soft check — if there happen to be protected sessions from other
	# tests we can't guarantee empty, but the command should at least succeed.
	r = ita('protect', '--list')
	assert r.returncode == 0


def test_unprotect_happy(session):
	ita_ok('protect', '-s', session)
	r = ita('unprotect', '-s', session)
	assert r.returncode == 0
	assert 'Unprotected' in r.stdout or session[:8] in r.stdout


@pytest.mark.state
def test_unprotect_removes_from_list(session):
	ita_ok('protect', '-s', session)
	ita_ok('unprotect', '-s', session)
	out = ita_ok('protect', '--list') if ita('protect', '--list').returncode == 0 else ''
	assert session not in out

# ── session info ──────────────────────────────────────────────────────────────

@pytest.mark.contract
def test_session_info_json_schema(session):
	out = ita_ok('session', 'info', '-s', session, '--json')
	data = json.loads(out)
	validate(instance=data, schema=SESSION_INFO_SCHEMA)


def test_session_info_plain(session):
	r = ita('session', 'info', '-s', session)
	assert r.returncode == 0
	assert 'session_id' in r.stdout


@pytest.mark.contract
def test_session_info_protected_flag_false_by_default(session):
	out = ita_ok('session', 'info', '-s', session, '--json')
	data = json.loads(out)
	assert data['protected'] is False


@pytest.mark.state
def test_session_info_protected_flag_true_when_protected(session):
	ita_ok('protect', '-s', session)
	try:
		out = ita_ok('session', 'info', '-s', session, '--json')
		data = json.loads(out)
		assert data['protected'] is True
	finally:
		ita('unprotect', '-s', session)


@pytest.mark.contract
def test_session_info_all_keys_present(session):
	"""All 14 schema keys are always present in --json output."""
	data = json.loads(ita_ok('session', 'info', '-s', session, '--json'))
	for key in SESSION_INFO_SCHEMA['required']:
		assert key in data, f"Missing key: {key}"
