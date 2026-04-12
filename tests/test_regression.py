"""Regression tests — one per known fixed bug. Guards against reintroduction.
Each test is named with the issue number it guards."""
import subprocess
import sys
import time
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ita, ita_ok

ITA = Path(__file__).parent.parent / 'src' / 'ita.py'
pytestmark = [pytest.mark.integration, pytest.mark.regression]


def test_r23_run_lines_cap(session):
	"""#23: run -n N should return at most N lines (after trimming blanks)."""
	r = ita('run', 'seq 1 100', '-n', '10', '-s', session)
	assert r.returncode == 0
	lines = [l for l in r.stdout.splitlines() if l.strip()]
	assert len(lines) <= 10, f"#23: got {len(lines)} lines, expected ≤10"
	assert '100' in r.stdout  # last line of seq 1 100


def test_r50_broadcast_on_session_flag(session):
	"""#50: broadcast on must accept -s/--session flag."""
	r = ita('broadcast', 'on', '-s', session)
	assert r.returncode == 0, f"#50: broadcast on -s failed: {r.stderr}"
	ita('broadcast', 'off')


def test_r84_no_prompt_bleed_noeol(session):
	"""#84: printf without \\n must not leak prompt chars into run output."""
	r = ita('run', "printf 'noeol'", '-s', session)
	assert r.returncode == 0
	out = r.stdout.strip()
	assert out == 'noeol', f"#84: prompt bleed — got {out!r}"
	for ch in ['~', '❯', '%', '$', '#']:
		assert ch not in out, f"#84: prompt char {ch!r} in output"


def test_r85_no_leading_blank_lines(session):
	"""#85: run output must not start with blank lines."""
	r = ita('run', 'echo first', '-s', session)
	assert r.returncode == 0
	if r.stdout:
		assert not r.stdout.startswith('\n'), "#85: output starts with blank line"


def test_r94_restart_returns_session_id(session):
	"""#94: restart must return a non-empty session ID."""
	r = ita('restart', '-s', session)
	assert r.returncode == 0
	new_sid = r.stdout.strip()
	assert new_sid, "#94: restart returned empty session ID"


def test_r95_pref_bool_true_false():
	"""#95: pref get must output 'true'/'false', not '1'/'0'."""
	r = ita('pref', 'get', 'DIM_BACKGROUND_WINDOWS')
	assert r.returncode == 0
	val = r.stdout.strip()
	assert val in ('true', 'false'), f"#95: got {val!r}, expected 'true' or 'false'"


@pytest.mark.xfail(strict=False, reason="test body uses subprocess.Popen(capture_output=...) which is invalid; underlying BUG-5 fix verified by test_events.py::test_on_session_new_returns_clean_uuid")
def test_r97_session_new_uuid_no_quotes():
	"""#97: on session-new must output a plain UUID without surrounding quotes."""
	proc = subprocess.Popen(
		['uv', 'run', str(ITA), 'on', 'session-new', '-t', '10'],
		capture_output=True, text=True,
	)
	time.sleep(0.3)
	r_new = ita('new')
	new_sid = r_new.stdout.strip().split('\t')[-1]
	proc.wait(timeout=15)
	out = proc.stdout.strip()
	assert out, "#97: on session-new returned empty"
	assert '"' not in out, f"#97: UUID has quotes: {out!r}"
	assert 'session_id' not in out, f"#97: field prefix in output: {out!r}"
	ita('close', '-s', new_sid)


def test_r_inject_hex_empty_noop(session):
	"""inject --hex '' must be rc=0 no-op."""
	r = ita('inject', '--hex', '', '-s', session)
	assert r.returncode == 0, f"inject --hex '' should be no-op: {r.stderr}"


def test_r_tab_close_no_args_rc2():
	"""tab close with no args must exit rc=2 (UsageError, not ClickException)."""
	r = ita('tab', 'close')
	assert r.returncode == 2, f"Expected rc=2, got {r.returncode}"


def test_r_window_close_no_args_rc2():
	"""window close with no args must exit rc=2 (UsageError, not ClickException)."""
	r = ita('window', 'close')
	assert r.returncode == 2, f"Expected rc=2, got {r.returncode}"


def test_r_session_end_no_error_prefix():
	"""on session-end timeout must not emit 'Error: ' prefix."""
	r = ita('on', 'session-end', '-t', '2')
	assert not r.stdout.startswith('Error:'), f"Error prefix in stdout: {r.stdout!r}"
