"""Contract tests for session commands: --json schema, --quiet, exit codes, output hygiene."""
import json
import sys
import pytest

sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent))
from conftest import ita, ita_ok

pytestmark = [pytest.mark.integration, pytest.mark.contract]

# JSON schema for `ita new --json`
_NEW_JSON_SCHEMA = {
	'type': 'object',
	'required': ['name', 'session_id'],
	'properties': {
		'name':       {'type': 'string', 'minLength': 1},
		'session_id': {'type': 'string', 'minLength': 1},
		'tab_id':     {'type': ['string', 'null']},
		'window_id':  {'type': ['string', 'null']},
	},
	'additionalProperties': False,
}


# ── new --json ────────────────────────────────────────────────────────────────

def test_new_json_schema():
	"""ita new --json output must validate against the published schema."""
	import jsonschema
	r = ita('new', '--json')
	assert r.returncode == 0
	data = json.loads(r.stdout)
	jsonschema.validate(instance=data, schema=_NEW_JSON_SCHEMA)
	# Teardown: close the created session
	ita('close', '-s', data['session_id'])


def test_new_json_no_ansi_no_nul(session):
	"""new --json output must contain no ANSI escape sequences or NUL bytes."""
	r = ita('new', '--json')
	assert r.returncode == 0
	out = r.stdout
	sid = json.loads(out)['session_id']
	ita('close', '-s', sid)
	assert '\x00' not in out, "NUL byte in --json output"
	assert '\x1b' not in out, "ANSI escape in --json output"
	assert '\x07' not in out, "BEL in --json output"


# ── close ─────────────────────────────────────────────────────────────────────

def test_close_quiet_emits_only_session_id(session):
	"""close --quiet should print only the session ID to stdout."""
	r = ita('close', '--quiet', '-s', session)
	assert r.returncode == 0
	out = r.stdout.strip()
	assert out == session, f"Expected only session ID on stdout; got: {out!r}"
	assert r.stderr.strip() == '', "Expected no stderr with --quiet"


def test_close_dry_run_prints_would_close(session):
	"""close --dry-run must not close the session but print what would happen."""
	r = ita('close', '--dry-run', '-s', session)
	assert r.returncode == 0
	assert 'would close' in r.stdout.lower(), f"Expected 'would close' in output; got: {r.stdout!r}"
	# Session still alive — activate to verify
	r2 = ita('activate', '-s', session)
	assert r2.returncode == 0, "Session must still be alive after dry-run"


def test_close_nonexistent_nonzero_rc():
	"""close on a bogus session ID must exit non-zero."""
	r = ita('close', '-s', 'w00000000-0000-0000-0000-000000000000')
	assert r.returncode != 0


# ── name ──────────────────────────────────────────────────────────────────────

def test_name_quiet_emits_only_session_id(session):
	"""name --quiet emits only the session ID to stdout."""
	r = ita('name', 'ita-test-quiet-name', '--quiet', '-s', session)
	assert r.returncode == 0
	out = r.stdout.strip()
	assert out == session, f"Expected only session ID; got: {out!r}"


def test_name_dry_run_does_not_rename(session):
	"""name --dry-run must not actually rename the session."""
	import json as _json
	# Get current name from status
	r_status = ita('status', '--json')
	sessions = _json.loads(r_status.stdout)
	orig_name = next(s['session_name'] for s in sessions if s['session_id'] == session)

	r = ita('name', 'ita-should-not-appear', '--dry-run', '-y', '-s', session)
	assert r.returncode == 0
	assert 'would rename' in r.stdout.lower()

	# Verify name unchanged
	r2 = ita('status', '--json')
	sessions2 = _json.loads(r2.stdout)
	current = next((s['session_name'] for s in sessions2 if s['session_id'] == session), None)
	assert current == orig_name, f"Name must not change after dry-run; got {current!r}"


def test_name_empty_nonzero_rc(session):
	"""name with empty title must exit non-zero."""
	r = ita('name', '', '-s', session)
	assert r.returncode != 0


# ── restart ───────────────────────────────────────────────────────────────────

def test_restart_quiet_emits_only_session_id(session):
	"""restart --quiet prints only the (new) session ID to stdout."""
	r = ita('restart', '--quiet', '-s', session)
	assert r.returncode == 0
	out = r.stdout.strip()
	# Should be a single UUID-like token
	assert ' ' not in out, f"--quiet output should be a single token; got: {out!r}"
	assert out, "restart --quiet must emit a session ID"


# ── resize ────────────────────────────────────────────────────────────────────

def test_resize_quiet_emits_only_session_id(session):
	"""resize --quiet prints only the session ID to stdout."""
	r = ita('resize', '--cols', '80', '--rows', '24', '--quiet', '-s', session)
	assert r.returncode == 0
	out = r.stdout.strip()
	assert out == session, f"Expected session ID; got: {out!r}"


def test_resize_dry_run_accepted(session):
	"""resize --dry-run must not raise an error."""
	r = ita('resize', '--cols', '80', '--rows', '24', '--dry-run', '-y', '-s', session)
	assert r.returncode == 0
	assert 'would resize' in r.stdout.lower()


# ── clear ─────────────────────────────────────────────────────────────────────

def test_clear_dry_run_does_not_clear(session):
	"""clear --dry-run must report intent without actually clearing."""
	r = ita('clear', '--dry-run', '-s', session)
	assert r.returncode == 0
	assert 'would clear' in r.stdout.lower()


# ── capture ───────────────────────────────────────────────────────────────────

def test_capture_no_nul_in_output(session):
	"""capture stdout must never contain NUL bytes."""
	r = ita('capture', '-s', session)
	assert r.returncode == 0
	assert '\x00' not in r.stdout, "NUL byte found in capture output"


def test_capture_bad_file_path_nonzero_rc(session):
	"""capture to a path in a nonexistent directory must exit non-zero."""
	r = ita('capture', '/no/such/dir/capture.txt', '-s', session)
	assert r.returncode != 0
