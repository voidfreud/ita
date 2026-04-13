"""Tests for `ita stabilize` (#268)."""
import json
import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ita, ita_ok

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# happy-path
# ---------------------------------------------------------------------------

def test_stabilize_default_flags_succeed(session):
	"""Default --require (shell_alive,writable) exits 0 for a live session."""
	r = ita('stabilize', '-s', session)
	assert r.returncode == 0, f"stabilize failed: {r.stderr}"


def test_stabilize_json_envelope(session):
	"""--json produces the full envelope with required keys."""
	r = ita('stabilize', '-s', session, '--json')
	assert r.returncode == 0, f"stabilize failed: {r.stderr}"
	data = json.loads(r.stdout)
	for key in ('shell_alive', 'prompt_visible', 'shell_integration_active',
	            'jobName_populated', 'writable', 'elapsed_ms'):
		assert key in data, f"missing key {key!r} in {data}"
	assert data['shell_alive'] is True
	assert data['writable'] is True
	assert isinstance(data['elapsed_ms'], int)
	assert data['elapsed_ms'] >= 0


def test_stabilize_require_shell_alive(session):
	"""Explicitly requiring only shell_alive always passes for a live session."""
	r = ita('stabilize', '-s', session, '--require', 'shell_alive', '--json')
	assert r.returncode == 0
	data = json.loads(r.stdout)
	assert data['shell_alive'] is True


def test_stabilize_json_no_error_key_on_success(session):
	"""On success, error key must NOT appear in the envelope."""
	r = ita('stabilize', '-s', session, '--json')
	assert r.returncode == 0
	data = json.loads(r.stdout)
	assert 'error' not in data


# ---------------------------------------------------------------------------
# error-path
# ---------------------------------------------------------------------------

@pytest.mark.error
def test_stabilize_locked_session_fails_writable(session):
	"""When session is write-locked, writable=false causes non-zero exit."""
	ita_ok('lock', '-s', session)
	try:
		r = ita('stabilize', '-s', session,
		        '--require', 'writable',
		        '--timeout', '200ms',
		        '--json')
		assert r.returncode != 0, "Expected non-zero when session is locked"
		data = json.loads(r.stdout)
		assert 'error' in data
		assert 'writable' in data['error']['pending']
		assert data['writable'] is False
	finally:
		ita('unlock', '-y', '-s', session)


@pytest.mark.error
def test_stabilize_unknown_require_flag_fails():
	"""Unknown --require flag name exits non-zero without connecting to iTerm2."""
	r = ita('stabilize', '-s', 'dummy-session-id', '--require', 'bogus_flag')
	assert r.returncode != 0
	assert 'bogus_flag' in r.stderr or 'Unknown' in r.stderr


@pytest.mark.error
def test_stabilize_pending_listed_in_stderr_without_json(session):
	"""Without --json, pending flags are printed to stderr."""
	ita_ok('lock', '-s', session)
	try:
		r = ita('stabilize', '-s', session,
		        '--require', 'writable',
		        '--timeout', '200ms')
		assert r.returncode != 0
		assert 'writable' in r.stderr
	finally:
		ita('unlock', '-y', '-s', session)


# ---------------------------------------------------------------------------
# contract
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_stabilize_elapsed_ms_is_non_negative(session):
	r = ita('stabilize', '-s', session, '--json')
	assert r.returncode == 0
	data = json.loads(r.stdout)
	assert data['elapsed_ms'] >= 0


@pytest.mark.contract
def test_stabilize_json_schema(session):
	"""Envelope matches expected JSON schema."""
	import jsonschema
	schema = {
		'type': 'object',
		'required': ['shell_alive', 'prompt_visible', 'shell_integration_active',
		             'jobName_populated', 'writable', 'elapsed_ms'],
		'properties': {
			'shell_alive':              {'type': 'boolean'},
			'prompt_visible':           {'type': 'boolean'},
			'shell_integration_active': {'type': 'boolean'},
			'jobName_populated':        {'type': 'boolean'},
			'writable':                 {'type': 'boolean'},
			'elapsed_ms':               {'type': 'integer', 'minimum': 0},
		},
		'additionalProperties': True,
	}
	r = ita('stabilize', '-s', session, '--json')
	assert r.returncode == 0
	jsonschema.validate(json.loads(r.stdout), schema)
