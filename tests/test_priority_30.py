"""
Priority-30 contract tests.

Covers the 6 agent-critical invariants from TESTING.md + issues #265 #282 #283
#268 #278 #292.  Where the bug is open the test is marked @pytest.mark.known_broken
so it documents expected behaviour but does NOT block CI until the fix lands.

Distribution:
  8× never-lie   (silent no-op on missing targets)
  6× never-leak-traceback
  5× mutator-honors-protection
  4× exclusivity / write-lock
  3× planes-not-mixed
  2× timeout-explicit
  2× readiness
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ita, ita_ok, _extract_sid

pytestmark = [pytest.mark.contract, pytest.mark.integration]


# ─────────────────────────────────────────────────────────────
#  8× NEVER-LIE  — silent no-op on missing / nonexistent targets
# ─────────────────────────────────────────────────────────────

@pytest.mark.contract
@pytest.mark.known_broken  # #223
def test_trust_01_window_activate_missing_target():
	"""
	(a) Never-lie: commands on nonexistent targets must fail explicitly, not silently succeed.
	(b) Issue #223: window activate with bogus window ID.
	(c) rc != 0 and stderr contains a structured error, not silence.
	"""
	r = ita('window', 'activate', '--window', 'nonexistent-window-id-xxxxxxxx')
	assert r.returncode != 0, "window activate on missing target silently returned 0 (never-lie violation)"


@pytest.mark.contract
@pytest.mark.known_broken  # #225
def test_trust_02_tab_activate_name_missing():
	"""
	(a) Never-lie: tab activate --name for an unknown tab must not silently succeed.
	(b) Issue #225: tab activate by name when name doesn't exist.
	(c) rc != 0.
	"""
	r = ita('tab', 'activate', '--name', 'tab-that-does-not-exist-xyz')
	assert r.returncode != 0, "tab activate --name on missing tab silently returned 0 (never-lie violation)"


@pytest.mark.contract
@pytest.mark.known_broken  # #286
def test_trust_03_layouts_save_window_missing():
	"""
	(a) Never-lie: layouts save --window with nonexistent window ID must fail.
	(b) Issue #286: layouts save --window accepts invalid target without error.
	(c) rc != 0.
	"""
	r = ita('layouts', 'save', '--window', 'bogus-window-id-xxxxxxxx', '--name', 'ghost')
	assert r.returncode != 0, "layouts save --window with missing window silently returned 0"


@pytest.mark.contract
@pytest.mark.known_broken  # #287
def test_trust_04_var_list_missing_session():
	"""
	(a) Never-lie: var list on a nonexistent session ID must fail explicitly.
	(b) Issue #287: var list silently returns empty list for unknown session.
	(c) rc != 0.
	"""
	r = ita('var', 'list', '-s', 'deadbeef-0000-0000-0000-000000000000')
	assert r.returncode != 0, "var list on missing session silently returned 0"


@pytest.mark.contract
@pytest.mark.known_broken  # #249
def test_trust_05_broadcast_on_missing_session():
	"""
	(a) Never-lie: broadcast on targeting a missing session must not silently no-op.
	(b) Issue #249: broadcast on with bad session reference.
	(c) rc != 0.
	"""
	r = ita('broadcast', 'on', '-s', 'deadbeef-0000-0000-0000-000000000000')
	assert r.returncode != 0, "broadcast on for nonexistent session silently returned 0"


@pytest.mark.contract
def test_trust_06_on_prompt_timeout_missing_session():
	"""
	(a) Never-lie: on prompt --timeout on missing session must fail, not hang or no-op.
	(b) Issue #247: on prompt -s missing silently exits 0.
	(c) rc != 0 within timeout budget.
	"""
	r = ita('on', 'prompt', '-s', 'deadbeef-0000-0000-0000-000000000000', '--timeout', '2')
	assert r.returncode != 0, "on prompt on nonexistent session silently returned 0"


@pytest.mark.contract
@pytest.mark.known_broken  # #222
def test_trust_07_focus_null_path_schema():
	"""
	(a) Never-lie: focus --json must return a valid JSON object even when no session is focused.
	(b) Issue #222: focus --json may return null or malformed output when focus path is absent.
	(c) stdout is parseable JSON dict (not null, not empty).
	"""
	r = ita('focus', '--json')
	assert r.returncode == 0, f"focus --json failed: {r.stderr}"
	try:
		obj = json.loads(r.stdout)
	except json.JSONDecodeError:
		pytest.fail(f"focus --json produced non-JSON stdout: {r.stdout!r}")
	assert isinstance(obj, dict), f"focus --json returned non-dict: {obj!r}"


@pytest.mark.contract
@pytest.mark.known_broken  # #227
def test_trust_08_unlock_quiet_missing_session():
	"""
	(a) Never-lie: unlock --quiet on a session with no lock must not silently succeed (rc 0).
	(b) Issue #227: unlock --quiet on unlocked session returns 0 hiding the state.
	(c) rc != 0 so callers can detect the noop.
	"""
	r = ita('unlock', '--quiet', '-s', 'deadbeef-0000-0000-0000-000000000000')
	assert r.returncode != 0, "unlock --quiet on nonexistent/unlocked session silently returned 0"


# ─────────────────────────────────────────────────────────────
#  6× NEVER-LEAK-TRACEBACK
# ─────────────────────────────────────────────────────────────

@pytest.mark.contract
@pytest.mark.adversarial
@pytest.mark.known_broken  # #219
def test_trust_09_read_grep_bad_regex():
	"""
	(a) Never-leak-traceback: malformed regex to read --grep must yield structured error.
	(b) Issue #219: read --grep with invalid regex leaks traceback.
	(c) 'Traceback' absent from stderr.
	"""
	r = ita('read', '--grep', '[unclosed bracket', '-s', 'deadbeef-0000-0000-0000-000000000000')
	assert 'Traceback' not in r.stderr, f"Traceback leaked on bad regex: {r.stderr[:300]}"
	assert 'Error' in r.stderr or r.returncode != 0, "Bad regex produced no error signal"


@pytest.mark.contract
@pytest.mark.adversarial
def test_trust_10_invalid_uuid_session_flag():
	"""
	(a) Never-leak-traceback: -s with a non-UUID string must produce structured error.
	(b) Issue #292: all commands with malformed -s should not traceback.
	(c) 'Traceback' absent from stderr; rc != 0.
	"""
	r = ita('capture', '-s', 'not-a-uuid!!!')
	assert 'Traceback' not in r.stderr, f"Traceback leaked on invalid UUID: {r.stderr[:300]}"
	assert r.returncode != 0, "Invalid UUID accepted silently"


@pytest.mark.contract
@pytest.mark.adversarial
def test_trust_11_run_bad_regex_grep_flag():
	"""
	(a) Never-leak-traceback: run with malformed --grep pattern must not traceback.
	(b) Issue #292: no raw tracebacks invariant.
	(c) 'Traceback' absent from stderr.
	"""
	r = ita('run', 'echo hi', '--grep', '(unclosed', '-s', 'deadbeef-0000-0000-0000-000000000000')
	assert 'Traceback' not in r.stderr, f"Traceback on bad --grep: {r.stderr[:300]}"


@pytest.mark.contract
@pytest.mark.adversarial
@pytest.mark.fault_injection
def test_trust_12_malformed_protect_args():
	"""
	(a) Never-leak-traceback: protect with nonsensical flags must not traceback.
	(b) Issue #292: protect is a mutator; bad args must give ClickException.
	(c) 'Traceback' absent from stderr; rc != 0.
	"""
	r = ita('protect', '--unknown-flag-zzz')
	assert 'Traceback' not in r.stderr, f"Traceback on malformed protect args: {r.stderr[:300]}"
	assert r.returncode != 0, "Garbage flags accepted silently"


@pytest.mark.contract
@pytest.mark.adversarial
@pytest.mark.fault_injection
def test_trust_13_corrupt_broadcast_state_read():
	"""
	(a) Never-leak-traceback: broadcast status when state file is corrupt must not traceback.
	(b) Issue #292: corrupt state stub triggers unhandled exception.
	(c) 'Traceback' absent; rc may be non-zero but no raw exception.
	"""
	import tempfile
	state_path = Path.home() / '.ita' / 'broadcast_state.json'
	backup = None
	try:
		if state_path.exists():
			backup = state_path.read_bytes()
		state_path.parent.mkdir(parents=True, exist_ok=True)
		state_path.write_text('{{{invalid json}}}')
		r = ita('broadcast', 'status')
		assert 'Traceback' not in r.stderr, f"Traceback on corrupt broadcast state: {r.stderr[:300]}"
	finally:
		if backup is not None:
			state_path.write_bytes(backup)
		elif state_path.exists():
			state_path.unlink()


@pytest.mark.contract
@pytest.mark.adversarial
@pytest.mark.fault_injection
def test_trust_14_bad_json_input_send():
	"""
	(a) Never-leak-traceback: passing obviously bad data to send must not traceback.
	(b) Issue #292: send with NUL bytes or control chars in text.
	(c) 'Traceback' absent from stderr.
	"""
	r = ita('send', '\x00\x01\x02', '-s', 'deadbeef-0000-0000-0000-000000000000')
	assert 'Traceback' not in r.stderr, f"Traceback on NUL-byte send: {r.stderr[:300]}"


# ─────────────────────────────────────────────────────────────
#  5× MUTATOR-HONORS-PROTECTION
# ─────────────────────────────────────────────────────────────

@pytest.mark.contract
@pytest.mark.known_broken  # #218
def test_trust_15_name_refuses_protected(protected_session):
	"""
	(a) Mutator-honors-protection: name must refuse on a protected session without --force.
	(b) Issue #218: name command does not check protection flag.
	(c) rc != 0 without --force.
	"""
	r = ita('name', 'new-sneaky-name', '-s', protected_session)
	assert r.returncode != 0, "name mutated a protected session without --force"


@pytest.mark.contract
def test_trust_16_resize_refuses_protected(protected_session):
	"""
	(a) Mutator-honors-protection: resize must refuse on protected session without --force.
	(b) Issue #292 parametrized matrix.
	(c) rc != 0.
	"""
	r = ita('resize', '--rows', '30', '--cols', '100', '-s', protected_session)
	assert r.returncode != 0, "resize mutated a protected session without --force"


@pytest.mark.contract
@pytest.mark.known_broken  # #283
def test_trust_17_bulk_clear_refuses_protected(protected_session):
	"""
	(a) Mutator-honors-protection: bulk clear --all must respect protection per session.
	(b) Issue #283: bulk clear --all bypasses protection check entirely.
	(c) Protected session is NOT cleared; rc reflects partial failure or refuses outright.
	"""
	r = ita('clear', '--all')
	# Even if the bulk op partially succeeds on other sessions, the protected one
	# must not be wiped.  Best signal: rc != 0 (refused) or explicit warning.
	# We also verify the session still exists.
	check = ita('session', 'info', '-s', protected_session, '--json')
	assert check.returncode == 0, "Protected session was destroyed by bulk clear"


@pytest.mark.contract
@pytest.mark.known_broken  # #292
def test_trust_18_theme_refuses_protected(protected_session):
	"""
	(a) Mutator-honors-protection: app theme change must not affect a protected session's profile.
	(b) Issue #292: theme is a mutator that should honour protection.
	(c) rc != 0 when protection should block.
	"""
	r = ita('pref', 'theme', '--name', 'Dark Background', '-s', protected_session)
	assert r.returncode != 0, "theme mutator applied to protected session without --force"


@pytest.mark.contract
@pytest.mark.known_broken  # #292
def test_trust_19_profile_set_refuses_protected(protected_session):
	"""
	(a) Mutator-honors-protection: profile set must refuse on protected session without --force.
	(b) Issue #292: all mutators parametrized.
	(c) rc != 0.
	"""
	r = ita('profile', 'set', 'Default', '-s', protected_session)
	assert r.returncode != 0, "profile set applied to protected session without --force"


# ─────────────────────────────────────────────────────────────
#  4× EXCLUSIVITY / WRITE-LOCK
# ─────────────────────────────────────────────────────────────

@pytest.mark.contract
@pytest.mark.known_broken  # #282
def test_trust_20_sibling_writers_same_parent(session):
	"""
	(a) Exclusivity: two ita processes from the same parent must not both claim the lock.
	(b) Issue #282: lock uses getppid(), so siblings share ownership — lock is not exclusive.
	(c) Exactly one of the two lock attempts succeeds (rc 0); the other fails (rc != 0).
	"""
	# Launch two concurrent lock attempts from this (same) parent process.
	p1 = subprocess.Popen(
		['uv', 'run', str(Path(__file__).parent.parent / 'src' / 'ita.py'),
		 'lock', '-s', session],
		stdout=subprocess.PIPE, stderr=subprocess.PIPE,
	)
	p2 = subprocess.Popen(
		['uv', 'run', str(Path(__file__).parent.parent / 'src' / 'ita.py'),
		 'lock', '-s', session],
		stdout=subprocess.PIPE, stderr=subprocess.PIPE,
	)
	rc1 = p1.wait(timeout=15)
	rc2 = p2.wait(timeout=15)
	# Exactly one should hold the lock; the other should fail.
	successes = sum(1 for rc in (rc1, rc2) if rc == 0)
	assert successes == 1, (
		f"Expected exactly 1 lock claim to succeed, got {successes} "
		f"(rc1={rc1}, rc2={rc2}) — same-parent exclusivity broken (#282)"
	)
	# Cleanup
	ita('unlock', '-s', session)


@pytest.mark.contract
@pytest.mark.known_broken  # #282
def test_trust_21_lock_same_parent_second_claim_fails(session):
	"""
	(a) Exclusivity: a second lock call on the same session from same parent must fail.
	(b) Issue #282: getppid() collapses sibling ownership so the second claim is let through.
	(c) rc != 0 on the second lock attempt.
	"""
	r1 = ita('lock', '-s', session)
	assert r1.returncode == 0, f"First lock failed unexpectedly: {r1.stderr}"
	r2 = ita('lock', '-s', session)
	assert r2.returncode != 0, "Second lock from same parent succeeded — exclusivity broken (#282)"
	ita('unlock', '-s', session)


@pytest.mark.contract
@pytest.mark.known_broken  # #282
def test_trust_22_lock_lease_acquire_fails_for_non_holder(session):
	"""
	(a) Exclusivity: a non-holder acquiring the lease must fail.
	(b) Issue #282: same-parent flaw means non-holder is treated as holder.
	(c) After lock is held by one process, a second acquire returns non-zero.
	"""
	lock_r = ita('lock', '-s', session)
	assert lock_r.returncode == 0, "Could not acquire initial lock"
	# Attempt a second acquisition — should be denied.
	r = ita('lock', '-s', session)
	assert r.returncode != 0, "Non-holder acquired lock — exclusivity broken"
	ita('unlock', '-s', session)


@pytest.mark.contract
@pytest.mark.known_broken  # #258
def test_trust_23_bulk_ops_respect_lock(session):
	"""
	(a) Exclusivity: bulk ops (send --all) must refuse locked sessions.
	(b) Issue #258: bulk operations bypass the write-lock check.
	(c) rc != 0 or session content unchanged after bulk send against locked session.
	"""
	lock_r = ita('lock', '-s', session)
	assert lock_r.returncode == 0, "Could not acquire lock for test setup"
	r = ita('send', '--all', 'echo pwned')
	# The locked session must not have been written to; ideally rc != 0 overall.
	# Minimal invariant: no success report for the locked session.
	assert r.returncode != 0 or 'lock' in r.stderr.lower() or 'lock' in r.stdout.lower(), (
		"Bulk send succeeded against a locked session without error (#258)"
	)
	ita('unlock', '-s', session)


# ─────────────────────────────────────────────────────────────
#  3× PLANES-NOT-MIXED
# ─────────────────────────────────────────────────────────────

@pytest.mark.contract
@pytest.mark.known_broken  # #248 / #278
def test_trust_24_run_n_warning_not_on_stdout(session):
	"""
	(a) Planes-not-mixed: the 'run -n N' warning must NOT appear on stdout.
	(b) Issue #248/#278: warning is prepended to stdout, mixing control and data planes.
	(c) stdout contains no warning text; warning goes to stderr.
	"""
	r = ita('run', '-n', '1', 'echo hello', '-s', session)
	# The warning text is something like "WARNING" or "lines" — check stdout is clean.
	assert 'Warning' not in r.stdout and 'WARNING' not in r.stdout, (
		f"Control-plane warning leaked into stdout: {r.stdout[:200]}"
	)


@pytest.mark.contract
@pytest.mark.known_broken  # #278 / #292
def test_trust_25_success_banner_absent_from_json_stdout(session):
	"""
	(a) Planes-not-mixed: --json mode must not emit human prose banners on stdout.
	(b) Issue #278/#292: stdout is machine-clean invariant.
	(c) stdout in --json mode is valid JSON with no extra banner lines.
	"""
	r = ita('run', 'echo hi', '--json', '-s', session)
	if r.returncode != 0:
		pytest.skip("run --json not supported or session not ready")
	# Every line of stdout must be parseable JSON (or empty).
	for line in r.stdout.splitlines():
		line = line.strip()
		if not line:
			continue
		try:
			json.loads(line)
		except json.JSONDecodeError:
			pytest.fail(f"Non-JSON line on --json stdout: {line!r}")


@pytest.mark.contract
def test_trust_26_errors_go_to_stderr_not_stdout():
	"""
	(a) Planes-not-mixed: error messages must not appear on stdout.
	(b) Issue #278/#292: stderr is the error channel.
	(c) stdout is empty (or valid JSON); error text appears only on stderr.
	"""
	r = ita('capture', '-s', 'deadbeef-0000-0000-0000-000000000000')
	assert r.returncode != 0, "Expected failure on missing session"
	# The stdout must not contain the error prose.
	assert 'Error' not in r.stdout and 'error' not in r.stdout.lower(), (
		f"Error message leaked onto stdout: {r.stdout[:200]}"
	)
	assert len(r.stderr.strip()) > 0, "Error text missing from stderr"


# ─────────────────────────────────────────────────────────────
#  2× TIMEOUT-EXPLICIT
# ─────────────────────────────────────────────────────────────

@pytest.mark.contract
@pytest.mark.known_broken  # #290
def test_trust_27_run_json_exit_124_on_timeout(session):
	"""
	(a) Timeout-explicit: run --json must use exit code 124 (not 1) on timeout.
	(b) Issue #290: run timeout produces rc=1 conflated with process failure.
	(c) rc == 124 when the command times out.
	"""
	r = ita('run', 'sleep 60', '--timeout', '2', '--json', '-s', session, timeout=10)
	assert r.returncode == 124, (
		f"Expected rc=124 on timeout, got rc={r.returncode} (#290)"
	)


@pytest.mark.contract
def test_trust_28_on_prompt_timeout_exits_nonzero(session):
	"""
	(a) Timeout-explicit: on prompt --timeout that expires must exit non-zero.
	(b) Issue #247: on prompt --timeout silently exits 0 when no prompt arrives.
	(c) rc != 0 after timeout elapses with no matching event.
	"""
	# Use a very short timeout and don't trigger a prompt.
	r = ita('on', 'prompt', '-s', session, '--timeout', '1', timeout=5)
	assert r.returncode != 0, (
		f"on prompt --timeout exited 0 without a matching event (expected non-zero) (#247)"
	)


# ─────────────────────────────────────────────────────────────
#  2× READINESS
# ─────────────────────────────────────────────────────────────

@pytest.mark.contract
@pytest.mark.integration
@pytest.mark.known_broken  # #250 / #268
def test_trust_29_post_new_var_get_jobname_race():
	"""
	(a) Readiness: var get jobName immediately after new must not return empty due to race.
	(b) Issue #250/#268: var get jobName races shell integration startup after new.
	(c) jobName is non-empty within 5s of session creation (stabilize protocol).
	"""
	import uuid
	name = f'ita-test-readiness-{uuid.uuid4().hex[:8]}'
	r = ita('new', '--name', name)
	assert r.returncode == 0, f"new failed: {r.stderr}"
	sid = _extract_sid(r.stdout)
	try:
		deadline = time.time() + 5
		job_name = ''
		while time.time() < deadline:
			rv = ita('var', 'get', 'jobName', '-s', sid, '--json')
			if rv.returncode == 0:
				try:
					obj = json.loads(rv.stdout)
					job_name = obj.get('value', '') or obj.get('jobName', '')
				except (json.JSONDecodeError, AttributeError):
					job_name = rv.stdout.strip()
			if job_name:
				break
			time.sleep(0.3)
		assert job_name, (
			"jobName still empty 5s after new — post-new readiness race (#250/#268)"
		)
	finally:
		ita('close', '-s', sid)


@pytest.mark.contract
@pytest.mark.integration
@pytest.mark.known_broken  # #268
def test_trust_30_post_restart_shell_back(session):
	"""
	(a) Readiness: after restart the shell must be alive and responsive within 5s.
	(b) Issue #268: no stabilize primitive means callers sleep-and-pray after restart.
	(c) run echo alive succeeds within 5s of restart completing.
	"""
	r = ita('restart', '-s', session)
	assert r.returncode == 0, f"restart failed: {r.stderr}"
	deadline = time.time() + 5
	alive = False
	while time.time() < deadline:
		rv = ita('run', 'echo alive', '--timeout', '3', '-s', session)
		if rv.returncode == 0 and 'alive' in rv.stdout:
			alive = True
			break
		time.sleep(0.5)
	assert alive, "Shell not responsive within 5s after restart — readiness race (#268)"
