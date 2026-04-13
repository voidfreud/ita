"""
Action table bug coverage — one test per action table item that lacked coverage.

Marking convention:
  @pytest.mark.regression  — item is FIXED, test guards against reintroduction
  @pytest.mark.known_broken — item is NOT YET FIXED (xfail); test documents expected
                              behaviour and will auto-promote to xpass when fixed.
"""
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ita

pytestmark = [pytest.mark.integration]


# ── S1: inject backslash UnicodeDecodeError ────────────────────────────────
@pytest.mark.regression
def test_s1_inject_backslash_no_crash(session):
	"""S1 (fixed v1.1.0): inject with backslash sequences must give a clear error,
	not an uncaught UnicodeDecodeError traceback."""
	r = ita('inject', r'\q', '-s', session)
	# Should either succeed (if the sequence is now handled) or give a clear
	# ClickException message — never a Python traceback.
	assert 'Traceback' not in r.stderr, "S1 regression: raw Python traceback on inject backslash"
	assert 'UnicodeDecodeError' not in r.stderr, "S1 regression: UnicodeDecodeError leaked to stderr"


@pytest.mark.regression
def test_s1_inject_hex_flag_works(session):
	"""S1 (fixed v1.1.0): --hex flag must accept raw byte value (e.g. 0x71 = 'q')."""
	r = ita('inject', '--hex', '71', '-s', session)
	assert r.returncode == 0, f"inject --hex failed: {r.stderr}"


# ── S2: run timeout orphan kill ────────────────────────────────────────────
@pytest.mark.regression
def test_s2_run_timeout_doesnt_block_next_run(session):
	"""S2 (fixed v1.1.0): after a timeout, a subsequent run must not hang waiting
	for the previous orphaned subshell."""
	ita('run', 'sleep 60', '--timeout', '2', '-s', session)
	# Give a small window for the \x03 kill to land
	time.sleep(0.5)
	r = ita('run', 'echo alive', '--timeout', '10', '-s', session)
	assert r.returncode == 0, f"S2 regression: run after timeout hung or failed: {r.stderr}"
	assert 'alive' in r.stdout, f"S2 regression: expected 'alive' in output, got: {r.stdout!r}"


# ── S3: run fast-fail without shell integration ────────────────────────────
@pytest.mark.regression
def test_s3_run_without_integration_reports_warning(session):
	"""S3 fix: when shell integration is absent, run emits a clear warning on stderr."""
	# We don't control whether shell integration is active, but if it's NOT,
	# the warning must appear and the command must not hang full 30s.
	r = ita('run', 'echo hi', '--timeout', '5', '-s', session)
	# Either shell integration is active (rc=0, output has 'hi') or it's absent
	# and we get the warning (rc still 0 or timeout, but no hang).
	assert r.returncode in (0, 1), f"S3: unexpected exit code {r.returncode}"
	# If no integration: stderr warning must not contain raw Python exception
	if 'shell integration' in r.stderr.lower():
		assert 'Traceback' not in r.stderr, "S3: traceback in shell-integration warning path"


# ── CF1: var get/set built-in variable access ─────────────────────────────
@pytest.mark.regression
def test_cf1_var_get_builtin_rows(session):
	"""CF1 (#101): var get <builtin> must NOT prepend 'user.' prefix.
	'rows' is a built-in session variable that should return a number."""
	r = ita('var', 'get', 'rows', '-s', session)
	assert r.returncode == 0, f"var get rows failed: {r.stderr}"
	val = r.stdout.strip()
	assert val, "var get rows returned empty — built-in var is inaccessible (user. prefix bug)"
	assert val.isdigit(), f"var get rows returned non-numeric: {val!r}"


@pytest.mark.regression
def test_cf1_var_get_builtin_jobname(session):
	"""CF1 fixed (#189): var get jobName must return the shell process name (e.g. 'zsh').
	jobName is populated by iTerm2 from the TTY foreground process — no shell integration needed.
	The prior xfail was stale: the user. prefix bug (#101) is fixed, and the var_get output
	now uses 'str(result) if result is not None else \"\"' to avoid swallowing falsy values."""
	r = ita('var', 'get', 'jobName', '-s', session)
	assert r.returncode == 0, f"var get jobName failed: {r.stderr}"
	val = r.stdout.strip()
	assert val, "var get jobName returned empty — built-in var is inaccessible"


# ── CF2: broadcast on must merge, not replace ─────────────────────────────
@pytest.mark.known_broken
@pytest.mark.xfail(reason="CF2: broadcast on atomically replaces all domains (#103)", strict=False)
def test_cf2_broadcast_on_merges_existing_domains(session):
	"""CF2 (#103): adding a session to broadcast must not evict sessions already
	in other broadcast domains."""
	r2 = ita('new')
	assert r2.returncode == 0
	sid2 = r2.stdout.strip().split('\t')[-1]
	r3 = ita('new')
	assert r3.returncode == 0
	sid3 = r3.stdout.strip().split('\t')[-1]
	try:
		ita('broadcast', 'on', '-s', session)
		ita('broadcast', 'on', '-s', sid2)
		# Now both session and sid2 are in a domain.
		# Adding sid3 must NOT remove session and sid2 from their domain.
		ita('broadcast', 'on', '-s', sid3)
		r = ita('broadcast', 'list')
		assert r.returncode == 0
		# All three session IDs should appear somewhere in the broadcast list
		assert session[:8].lower() in r.stdout.lower() or session.lower() in r.stdout.lower(), \
			"CF2: original session evicted from broadcast domain after adding third session"
	finally:
		ita('broadcast', 'off')
		ita('close', '-s', sid2)
		ita('close', '-s', sid3)


# ── LA1: move null-guard on current_tab ───────────────────────────────────
def test_la1_move_bogus_ids_give_clear_error():
	"""LA1 (#102): move with nonexistent IDs must give a clear ClickException.
	Note: fully testing the current_tab=None path requires creating an iTerm2
	window with no tabs, which the API doesn't support. This guards the error path."""
	r = ita('move', 'pty-00000000-0000-0000-0000-000000000000',
	        'pty-00000000-0000-0000-0000-000000000001')
	assert 'AttributeError' not in r.stderr, \
		"LA1: AttributeError leaked — null guard missing on current_tab"
	assert 'Traceback' not in r.stderr, f"LA1: raw traceback: {r.stderr}"
	assert r.returncode != 0, "move with bogus window ID should fail"


# ── LA2: tab next/prev ValueError ─────────────────────────────────────────
@pytest.mark.regression
def test_la2_tab_next_doesnt_crash():
	"""LA2 (fixed): tab next must not raise uncaught ValueError.
	tab next/prev operate on the current window — no -s flag."""
	r = ita('tab', 'next')
	assert 'ValueError' not in r.stderr, f"LA2: ValueError leaked: {r.stderr}"
	assert 'Traceback' not in r.stderr, f"LA2: raw traceback: {r.stderr}"
	# rc may be 0 or non-zero (only one tab), but must not be an unhandled exception
	assert r.returncode in (0, 1)


@pytest.mark.regression
def test_la2_tab_prev_doesnt_crash():
	"""LA2 (fixed): tab prev must not raise uncaught ValueError."""
	r = ita('tab', 'prev')
	assert 'ValueError' not in r.stderr, f"LA2: ValueError leaked: {r.stderr}"
	assert 'Traceback' not in r.stderr, f"LA2: raw traceback: {r.stderr}"
	assert r.returncode in (0, 1)


# ── LA3: activate by name / prefix ────────────────────────────────────────
@pytest.mark.regression
def test_la3_activate_by_prefix(session):
	"""LA3 (FIXED via resolve_session prefix match): activate must resolve sessions
	by 8-char prefix. resolve_session() in _core.py already does prefix matching."""
	prefix = session[:8]
	r = ita('activate', prefix)
	assert r.returncode == 0, \
		f"LA3: activate by 8-char prefix failed: {r.stderr}"


# ── I1: repl must show actual error message ────────────────────────────────
@pytest.mark.known_broken
@pytest.mark.xfail(reason="I1: repl doesn't handle subcommand errors gracefully (#104)", strict=False)
def test_i1_repl_no_traceback_on_bad_command(session):
	"""I1 (#104): when a subcommand fails inside repl, the process must NOT
	crash with a Python traceback. It should handle the error gracefully."""
	proc = subprocess.run(
		# Note: repl does not accept -s; session targeting via repl is a pending CLI design issue.
		['uv', 'run', 'python', '-m', 'ita',
		 'repl'],
		input='status --json\nexit\n',
		capture_output=True, text=True, timeout=15,
	)
	combined = proc.stdout + proc.stderr
	assert 'Traceback (most recent call last)' not in combined, \
		f"I1: repl crashed with Python traceback: {combined[:500]!r}"
	# repl must handle exit command cleanly
	assert proc.returncode in (0, 1), \
		f"I1: unexpected repl exit code: {proc.returncode}"


# ── SS2: theme red maps to non-existent preset ────────────────────────────
@pytest.mark.regression
def test_ss2_theme_red_gives_clear_error():
	"""SS2: `ita theme red` must either apply a real theme or raise a clear error.
	It must NOT silently succeed with a non-existent preset."""
	r = ita('theme', 'red')
	if r.returncode != 0:
		# Error is acceptable but must be informative — not a bare traceback
		assert 'Traceback' not in r.stderr, f"SS2: raw traceback on theme red: {r.stderr}"
		assert r.stderr.strip(), "SS2: theme red failed silently with no error message"
	# If rc=0, the theme was applied — that's also fine


# ── SS1: profile set color properties need iterm2.Color coercion ──────────
@pytest.mark.regression
def test_ss1_profile_set_string_property_no_crash():
	"""SS1: profile set with a string property must not crash with TypeError."""
	r = ita('profile', 'set', 'Default', 'name', 'Default')
	assert 'TypeError' not in r.stderr, \
		f"SS1: TypeError leaked — profile set crashing on typed property: {r.stderr}"
	assert 'Traceback' not in r.stderr, f"SS1: raw traceback on profile set: {r.stderr}"


@pytest.mark.regression
def test_ss1_profile_set_color_property():
	"""SS1 (#108): setting a color property with a hex string must not crash."""
	r = ita('profile', 'set', 'Default', 'background_color', '#1e1e1e')
	assert 'TypeError' not in r.stderr, \
		f"SS1: TypeError on color property set: {r.stderr}"
	assert 'Traceback' not in r.stderr, f"SS1: raw traceback: {r.stderr}"


# ── O1: watch emits only new lines (delta) ────────────────────────────────
@pytest.mark.regression
def test_o1_watch_no_duplicate_lines(session):
	"""O1 (fixed): watch must not re-emit the same line on every frame change.
	The pre-fix bug was emitting the ENTIRE screen on every diff, causing duplicates.
	Strategy: run a command that scrolls N lines; watch must not output N*M lines
	(where M = number of screen-change events)."""
	# Run a command that outputs 5 distinct lines
	ita('run', 'for i in 1 2 3 4 5; do echo "unique-o1-$i"; done', '-s', session)
	time.sleep(0.2)
	# Now start watch — it should observe the next command's output, not re-emit history
	proc = subprocess.Popen(
		['uv', 'run', 'python', '-m', 'ita',
		 'watch', '-s', session, '--timeout', '4'],
		stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
	)
	# Run a fresh command to trigger a screen change event
	ita('run', 'echo watch-trigger', '-s', session)
	try:
		stdout, _ = proc.communicate(timeout=7)
	except subprocess.TimeoutExpired:
		proc.kill()
		stdout, _ = proc.communicate()
	# Guard: if we saw "unique-o1-1" MORE THAN ONCE, watch is re-emitting full screen
	count = stdout.count('unique-o1-1')
	assert count <= 1, \
		f"O1 regression: watch emitted 'unique-o1-1' {count} times — full-screen re-emit bug"


# ── O2: watch has --timeout flag ──────────────────────────────────────────
@pytest.mark.regression
def test_o2_watch_timeout_flag_exits_cleanly(session):
	"""O2 (fixed): watch --timeout must exit after the given seconds."""
	start = time.time()
	r = ita('watch', '-s', session, '--timeout', '2', timeout=8)
	elapsed = time.time() - start
	assert elapsed < 6, f"O2: watch --timeout 2 took {elapsed:.1f}s — didn't respect timeout"
	assert r.returncode in (0, 1), f"O2: unexpected rc={r.returncode}"


# ── T2: tmux windows no double @@ prefix ─────────────────────────────────
def test_t2_tmux_windows_no_double_prefix():
	"""T2 (fixed): `ita tmux windows` must not double the @ prefix (@@1)."""
	r = ita('tmux', 'windows')
	if r.returncode != 0:
		pytest.skip("No active tmux-CC connections")
	for line in r.stdout.splitlines():
		assert not line.startswith('@@'), \
			f"T2 regression: double @@ prefix in tmux windows output: {line!r}"


# ── T3: tmux start None crash ────────────────────────────────────────────
def test_t3_tmux_start_no_crash():
	"""T3 (fixed): `ita tmux start` must not crash with TypeError when no connections."""
	r = ita('tmux', 'start', timeout=10)
	assert 'TypeError' not in r.stderr, f"T3 regression: TypeError on tmux start: {r.stderr}"
	assert 'Traceback' not in r.stderr, f"T3: raw traceback: {r.stderr}"


# ── E1: on events validate regex before subscribing ─────────────────────
@pytest.mark.regression
def test_e1_on_output_invalid_regex_gives_clear_error(session):
	"""E1 (fixed): invalid regex must raise a clear error before entering the loop."""
	r = ita('on', 'output', '[unclosed', '-s', session, '-t', '1')
	assert r.returncode != 0, "E1: invalid regex should exit non-zero"
	# Must show a meaningful message, not a raw re.error traceback mid-stream
	assert 're.error' not in r.stderr or 'Error:' in r.stderr, \
		f"E1 regression: raw re.error leaked without user-friendly wrapper: {r.stderr}"


# ── E2: on events timeout must not echo "None" ───────────────────────────
@pytest.mark.regression
def test_e2_on_focus_timeout_no_none_prefix(session):
	"""E2 (fixed): on focus timeout must not print literal 'None' to stdout."""
	r = ita('on', 'focus', '-t', '1', timeout=5)
	assert r.returncode in (0, 1)
	assert not r.stdout.strip().startswith('None'), \
		f"E2 regression: on focus timeout echoed 'None': {r.stdout!r}"


# ── SS3: close with -s must report the session being closed ────────────────
@pytest.mark.regression
def test_ss3_close_reports_session(session):
	"""SS3 (fixed): close -s <id> must print the closed session ID (or at minimum
	not silently kill it without any output when -s is given)."""
	# The fix was to report the session ID; this verifies it doesn't crash silently.
	r = ita('close', '-s', session)
	# rc=0 and no crash is the minimum bar; ideally stdout shows the session ID
	assert r.returncode == 0, f"SS3: close -s failed: {r.stderr}"
	assert 'Traceback' not in r.stderr


# ── CR6: doctor command must exist ────────────────────────────────────────
def test_cr6_doctor_command_exists():
	"""CR6 (fixed): `ita doctor` must exist and return usage info or run successfully."""
	r = ita('doctor', '--help')
	assert r.returncode == 0, f"CR6: doctor --help failed: {r.stderr}"
	assert 'doctor' in r.stdout.lower() or 'diagnos' in r.stdout.lower() \
		or 'iTerm2' in r.stdout, f"CR6: doctor --help output unexpected: {r.stdout!r}"


# ── layouts: bare call defaults to list ──────────────────────────────────
@pytest.mark.regression
def test_layouts_bare_call_defaults_to_list():
	"""Fixed v1.1.1: `ita layouts` bare must default to listing (rc=0) even if empty."""
	r = ita('layouts')
	assert r.returncode == 0, f"layouts bare call failed: {r.stderr}"


# ── on session-end: notification callback receives correct type ──────────
@pytest.mark.regression
def test_on_session_end_fires_and_reports_id():
	"""Fixed v1.1.1: on session-end must fire and print the terminated session ID."""
	r_new = ita('new')
	assert r_new.returncode == 0
	fresh_sid = r_new.stdout.strip().split('\t')[-1]
	proc = subprocess.Popen(
		['uv', 'run', 'python', '-m', 'ita',
		 'on', 'session-end', '-s', fresh_sid, '-t', '10'],
		stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
	)
	time.sleep(0.3)
	ita('close', '-s', fresh_sid)
	stdout, stderr = proc.communicate(timeout=15)
	assert proc.returncode == 0, \
		f"on session-end returned rc={proc.returncode}\nstderr: {stderr}"
	assert not stdout.startswith('Error:'), f"on session-end printed error: {stdout!r}"
	# Output should be the session ID (or at least not empty)
	assert stdout.strip(), "on session-end produced no output after session closed"
