"""Contract tests for send commands: --json schema, --quiet, exit codes, output hygiene."""
import json
import sys
import time
import pytest

sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent))
from conftest import ita

pytestmark = [pytest.mark.integration, pytest.mark.contract]


@pytest.fixture
def settled_session(session):
	time.sleep(1)
	return session


# JSON schema for `ita run --json`
_RUN_JSON_SCHEMA = {
	'type': 'object',
	'required': ['output', 'elapsed_ms', 'exit_code', 'timed_out', 'escalated', 'shell_integration'],
	'properties': {
		'output':           {'type': 'string'},
		'elapsed_ms':       {'type': 'integer', 'minimum': 0},
		'exit_code':        {'type': ['integer', 'null']},
		'timed_out':        {'type': 'boolean'},
		'escalated':        {'type': 'boolean'},
		'shell_integration':{'type': 'boolean'},
	},
	'additionalProperties': False,
}


# ── run --json ────────────────────────────────────────────────────────────────

def test_run_json_schema(settled_session):
	"""ita run --json output must validate against the published schema."""
	import jsonschema
	r = ita('run', 'echo contract', '--json', '-s', settled_session)
	assert r.returncode == 0
	data = json.loads(r.stdout)
	jsonschema.validate(instance=data, schema=_RUN_JSON_SCHEMA)


def test_run_json_no_ansi_no_nul(settled_session):
	"""run --json output must not contain NUL bytes, ANSI escapes, or BEL."""
	r = ita('run', 'echo hygiene', '--json', '-s', settled_session)
	assert r.returncode == 0
	out = r.stdout
	assert '\x00' not in out, "NUL byte in run --json output"
	assert '\x1b' not in out, "ANSI escape in run --json output"
	assert '\x07' not in out, "BEL in run --json output"


def test_run_json_exit_code_passthrough(settled_session):
	"""run --json exit_code must match the command's real exit code."""
	r = ita('run', 'exit 7', '--json', '-s', settled_session)
	assert r.returncode == 7
	data = json.loads(r.stdout)
	assert data['exit_code'] == 7


def test_run_json_elapsed_ms_positive(settled_session):
	"""run --json elapsed_ms must be a positive integer."""
	r = ita('run', 'true', '--json', '-s', settled_session)
	assert r.returncode == 0
	data = json.loads(r.stdout)
	assert data['elapsed_ms'] > 0


def test_run_json_timed_out_false_on_fast_cmd(settled_session):
	"""run --json timed_out must be false for fast commands."""
	r = ita('run', 'true', '--json', '-s', settled_session)
	assert r.returncode == 0
	data = json.loads(r.stdout)
	assert data['timed_out'] is False


# ── send ──────────────────────────────────────────────────────────────────────

def test_send_missing_session_nonzero():
	"""send without -s must exit non-zero with an intelligible error."""
	r = ita('send', 'hello')
	assert r.returncode != 0
	combined = r.stderr + r.stdout
	assert combined.strip(), "Expected error output"


def test_send_empty_text_accepted(session):
	"""send with empty string must be accepted (no-op or newline send)."""
	r = ita('send', '', '-s', session)
	# Empty text: rc=0 is expected (sending empty text is valid)
	assert r.returncode == 0


# ── inject ────────────────────────────────────────────────────────────────────

def test_inject_missing_session_nonzero():
	"""inject without -s must exit non-zero."""
	r = ita('inject', 'hi')
	assert r.returncode != 0


def test_inject_state_does_not_kill_session(session):
	"""inject should not close the session."""
	r = ita('inject', '--hex', '41', '-s', session)  # 'A'
	assert r.returncode == 0
	# Session still alive
	r2 = ita('activate', '-s', session)
	assert r2.returncode == 0


# ── key ───────────────────────────────────────────────────────────────────────

def test_key_missing_session_nonzero():
	"""key without -s must exit non-zero."""
	r = ita('key', 'enter')
	assert r.returncode != 0


def test_key_unknown_error_message():
	"""key with unknown token must emit a message containing 'unknown'."""
	r = ita('key', 'notarealkey_xyz')
	assert r.returncode != 0
	assert 'unknown' in (r.stderr + r.stdout).lower()


def test_key_no_nul_in_output(session):
	"""key output must not contain NUL bytes."""
	r = ita('key', 'enter', '-s', session)
	assert r.returncode == 0
	assert '\x00' not in r.stdout
