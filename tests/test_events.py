"""Integration tests for event and advanced commands: on, coprocess, annotate, rpc."""
import subprocess
import sys
import time
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ita, ita_ok

ITA = ['python', '-m', 'ita']
pytestmark = pytest.mark.integration


def _popen(*args, **kwargs):
	return subprocess.Popen(
		['uv', 'run', *ITA] + list(args),
		stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **kwargs
	)


# ── on output ─────────────────────────────────────────────────────────────────

def test_on_output_finds_pattern(session):
	proc = _popen('on', 'output', 'MARKER_ALPHA', '-s', session, '-t', '10')
	time.sleep(0.3)
	ita('send', 'echo MARKER_ALPHA', '-s', session)
	stdout, _ = proc.communicate(timeout=15)
	assert proc.returncode == 0
	assert 'MARKER_ALPHA' in stdout


def test_on_output_timeout(session):
	r = ita('on', 'output', 'WILL_NEVER_APPEAR_ZZZ', '-s', session, '-t', '2')
	assert r.returncode == 1
	assert 'timeout' in r.stderr.lower() or 'Timeout' in r.stderr


# ── on session-new ────────────────────────────────────────────────────────────

def test_on_session_new_returns_clean_uuid():
	"""#97: output must be plain session ID, no surrounding quotes."""
	proc = _popen('on', 'session-new', '-t', '10')
	time.sleep(0.3)
	r_new = ita('new')
	new_sid = r_new.stdout.strip().split('\t')[-1]
	stdout, _ = proc.communicate(timeout=15)
	assert proc.returncode == 0
	out = stdout.strip()
	assert out, "on session-new returned empty"
	assert '"' not in out, f"UUID has quotes: {out!r}"
	assert 'session_id' not in out, f"Contains field prefix: {out!r}"
	ita('close', '-s', new_sid)


# ── on session-end ────────────────────────────────────────────────────────────

def test_on_session_end_fires():
	"""Use a fresh session independent of the fixture so closing it doesn't break teardown."""
	r_new = ita('new')
	assert r_new.returncode == 0
	fresh_sid = r_new.stdout.strip().split('\t')[-1]
	proc = _popen('on', 'session-end', '-s', fresh_sid, '-t', '10')
	time.sleep(0.3)
	ita('close', '-s', fresh_sid)
	stdout, _ = proc.communicate(timeout=15)
	assert proc.returncode == 0
	assert not stdout.startswith('Error:'), f"Error prefix: {stdout!r}"


def test_on_session_end_timeout_no_error_prefix():
	"""Timeout should exit cleanly with no 'Error: ' in stdout."""
	r = ita('on', 'session-end', '-t', '2')
	assert r.returncode in (0, 1)
	assert not r.stdout.startswith('Error:'), f"Error prefix: {r.stdout!r}"


# ── on prompt / focus / layout ────────────────────────────────────────────────

def test_on_prompt_timeout(session):
	r = ita('on', 'prompt', '-s', session, '-t', '3')
	assert r.returncode in (0, 1)


def test_on_focus_timeout():
	r = ita('on', 'focus', '-t', '2')
	assert r.returncode in (0, 1)


def test_on_layout_timeout():
	r = ita('on', 'layout', '-t', '2')
	assert r.returncode in (0, 1)


# ── annotate ─────────────────────────────────────────────────────────────────

def test_annotate(session):
	ita_ok('run', 'echo annotate_target', '-s', session)
	r = ita('annotate', 'my annotation', '-s', session)
	assert r.returncode == 0


def test_annotate_invalid_range(session):
	r = ita('annotate', 'bad range', '--start', '80', '--end', '10', '-s', session)
	assert r.returncode == 1
	assert 'start' in r.stderr.lower() or 'end' in r.stderr.lower()


# ── coprocess ─────────────────────────────────────────────────────────────────

def test_coprocess_start_stop(session):
	r_start = ita('coprocess', 'start', 'cat', '-s', session)
	assert r_start.returncode == 0
	r_stop = ita('coprocess', 'stop', '-s', session)
	assert r_stop.returncode == 0


def test_coprocess_double_start_fails(session):
	ita('coprocess', 'start', 'cat', '-s', session)
	r = ita('coprocess', 'start', 'cat', '-s', session)
	assert r.returncode == 1
	assert 'already' in r.stderr.lower()
	ita('coprocess', 'stop', '-s', session)


def test_coprocess_stop_none_fails(session):
	r = ita('coprocess', 'stop', '-s', session)
	assert r.returncode == 1
	assert 'No coprocess' in r.stderr or 'no coprocess' in r.stderr.lower()


# ── coprocess list ────────────────────────────────────────────────────────────

def test_coprocess_list_empty():
	"""Happy: no coprocesses running → prints sentinel, rc=0."""
	r = ita('coprocess', 'list')
	assert r.returncode == 0
	# Output should mention 'No running coprocesses' or be empty (both acceptable)
	assert 'coprocess' in r.stdout.lower() or r.stdout.strip() == ''


def test_coprocess_list_shows_active(session):
	"""Contract: after starting a coprocess it must appear in list output."""
	ita_ok('coprocess', 'start', 'cat', '-s', session)
	try:
		r = ita('coprocess', 'list')
		assert r.returncode == 0
		assert session in r.stdout
	finally:
		ita('coprocess', 'stop', '-s', session)


# ── on prompt ─────────────────────────────────────────────────────────────────

def test_on_prompt_json_schema(session):
	"""Contract: --json emits {"line": <str>} when prompt is already visible."""
	import json
	# Run something so there's definitely a prompt on screen
	ita_ok('run', 'echo hi', '-s', session)
	r = ita('on', 'prompt', '-s', session, '-t', '5', '--json')
	assert r.returncode in (0, 1)
	if r.returncode == 0 and r.stdout.strip():
		payload = json.loads(r.stdout.strip())
		assert 'line' in payload
		assert isinstance(payload['line'], str)


def test_on_prompt_returns_string(session):
	"""Happy: on prompt returns a non-empty line when prompt appears."""
	ita_ok('run', 'echo hello', '-s', session)
	r = ita('on', 'prompt', '-s', session, '-t', '5')
	assert r.returncode in (0, 1)
	if r.returncode == 0:
		assert r.stdout.strip()


# ── on keystroke ──────────────────────────────────────────────────────────────

def test_on_keystroke_bad_regex():
	"""Error: invalid regex raises BadParameter, rc=2."""
	r = ita('on', 'keystroke', '[invalid')
	assert r.returncode == 2
	assert 'invalid' in r.stderr.lower() or 'pattern' in r.stderr.lower()


def test_on_keystroke_timeout(session):
	"""Edge: times out when no keystroke matches within window."""
	r = ita('on', 'keystroke', 'XYZZY_NEVER', '-s', session, '-t', '2')
	assert r.returncode == 1
	assert 'timeout' in r.stderr.lower() or 'Timeout' in r.stderr


def test_on_keystroke_json_shape(session):
	"""Contract: --json flag produces parseable JSON even on timeout-adjacent paths."""
	# Just confirm the flag is accepted; timeout is fine
	r = ita('on', 'keystroke', 'a', '-s', session, '-t', '1', '--json')
	assert r.returncode in (0, 1)
	if r.returncode == 0 and r.stdout.strip():
		import json
		payload = json.loads(r.stdout.strip())
		assert 'chars' in payload


# ── on session-new --json ─────────────────────────────────────────────────────

def test_on_session_new_json_schema():
	"""Contract: --json emits {session_id, name} with UUID-shaped id."""
	import json
	import re
	UUID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.I)
	proc = _popen('on', 'session-new', '-t', '10', '--json')
	time.sleep(0.3)
	r_new = ita('new')
	new_sid = r_new.stdout.strip().split('\t')[-1]
	stdout, _ = proc.communicate(timeout=15)
	assert proc.returncode == 0
	payload = json.loads(stdout.strip())
	assert 'session_id' in payload
	assert 'name' in payload
	assert UUID_RE.match(payload['session_id']), f"Bad UUID: {payload['session_id']!r}"
	ita('close', '-s', new_sid)


# ── on session-end --json ─────────────────────────────────────────────────────

def test_on_session_end_json_schema():
	"""Contract: --json emits {session_id, name}."""
	import json
	r_new = ita('new')
	assert r_new.returncode == 0
	fresh_sid = r_new.stdout.strip().split('\t')[-1]
	proc = _popen('on', 'session-end', '-s', fresh_sid, '-t', '10', '--json')
	time.sleep(0.3)
	ita('close', '-s', fresh_sid)
	stdout, _ = proc.communicate(timeout=15)
	assert proc.returncode == 0
	payload = json.loads(stdout.strip())
	assert 'session_id' in payload
	assert 'name' in payload
	assert isinstance(payload['name'], str)


# ── on focus --json ───────────────────────────────────────────────────────────

def test_on_focus_json_flag_accepted():
	"""Contract: --json flag is accepted; timeout exits cleanly."""
	r = ita('on', 'focus', '-t', '2', '--json')
	assert r.returncode in (0, 1)
	if r.returncode == 0 and r.stdout.strip():
		import json
		payload = json.loads(r.stdout.strip())
		assert 'event' in payload


# ── on layout --json ──────────────────────────────────────────────────────────

def test_on_layout_json_flag_accepted():
	"""Contract: --json flag is accepted; timeout exits cleanly."""
	r = ita('on', 'layout', '-t', '2', '--json')
	assert r.returncode in (0, 1)
	if r.returncode == 0 and r.stdout.strip():
		import json
		payload = json.loads(r.stdout.strip())
		assert 'event' in payload


# ── on output edge ────────────────────────────────────────────────────────────

@pytest.mark.edge
def test_on_output_bad_regex():
	"""Error: invalid regex pattern → rc=2 (click.BadParameter)."""
	r = ita('on', 'output', '[bad-regex')
	assert r.returncode == 2
	assert 'invalid' in r.stderr.lower() or 'pattern' in r.stderr.lower()


@pytest.mark.edge
def test_on_output_unicode_pattern(session):
	"""Edge: unicode pattern and output round-trips correctly."""
	marker = 'MARKER_\u00e9\u00e0\u00fc'
	proc = _popen('on', 'output', marker, '-s', session, '-t', '10')
	time.sleep(0.3)
	ita('send', f'echo {marker}', '-s', session)
	stdout, _ = proc.communicate(timeout=15)
	assert proc.returncode == 0
	assert marker in stdout


@pytest.mark.contract
def test_on_output_json_schema(session):
	"""Contract: --json emits {"line": <str>}."""
	import json
	proc = _popen('on', 'output', 'JSON_TEST_MARKER', '-s', session, '-t', '10', '--json')
	time.sleep(0.3)
	ita('send', 'echo JSON_TEST_MARKER', '-s', session)
	stdout, _ = proc.communicate(timeout=15)
	assert proc.returncode == 0
	payload = json.loads(stdout.strip())
	assert 'line' in payload
	assert 'JSON_TEST_MARKER' in payload['line']


# ── annotate edge / contract ──────────────────────────────────────────────────

@pytest.mark.edge
def test_annotate_unicode_text(session):
	"""Edge: unicode annotation text is accepted."""
	ita_ok('run', 'echo hi', '-s', session)
	r = ita('annotate', 'héllo wörld 🎉', '-s', session)
	assert r.returncode == 0


@pytest.mark.contract
def test_annotate_range_flag(session):
	"""Contract: --range START END is accepted and overrides legacy --start/--end."""
	ita_ok('run', 'echo hi', '-s', session)
	r = ita('annotate', 'ranged note', '--range', '0', '40', '-s', session)
	assert r.returncode == 0


# ── rpc contract ──────────────────────────────────────────────────────────────

@pytest.mark.contract
def test_rpc_invalid_invocation_fails(session):
	"""Contract: rpc with a nonexistent function name exits non-zero."""
	r = ita('rpc', 'totally_nonexistent_function()', '-s', session)
	# Must fail — function doesn't exist in iTerm2
	assert r.returncode != 0


@pytest.mark.contract
def test_rpc_missing_arg():
	"""Error: rpc with no INVOCATION argument → rc=2 (missing arg)."""
	r = ita('rpc')
	assert r.returncode == 2
