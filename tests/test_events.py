"""Integration tests for event and advanced commands: on, coprocess, annotate, rpc."""
import subprocess
import sys
import time
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ita, ita_ok

ITA = Path(__file__).parent.parent / 'src' / 'ita.py'
pytestmark = pytest.mark.integration


def _popen(*args, **kwargs):
	return subprocess.Popen(
		['uv', 'run', str(ITA)] + list(args),
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
