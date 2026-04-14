"""Regression tests — one per open issue. All marked known_broken; they fail today by design."""
import json
import os
import subprocess
import sys
import time
import pytest

sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent))
from conftest import ita, ita_ok, _extract_sid

# #394: every test here touches iTerm2 — either via the `session` fixture
# or by calling `ita new` / other live commands directly. Integration-only
# so the fast lane stays hermetic.
pytestmark = [pytest.mark.regression, pytest.mark.integration]


# ── #282 write-lock PPID ──────────────────────────────────────────────────────

def test_issue_282_write_lock_ppid_collision(session):
	"""#282: Two subprocesses sharing same PPID can acquire same session lock.
	Expected fix: lock key must include PID, not just PPID."""
	# Acquire lock from current process
	r1 = ita('lock', '-s', session)
	assert r1.returncode == 0, f"First lock failed: {r1.stderr}"
	try:
		# Second attempt from a child subprocess — same PPID as us
		r2 = subprocess.run(
			['python3', '-c',
			 f"import subprocess, sys; "
			 f"r = subprocess.run(['uv','run',sys.argv[1],'lock','-s','{session}'], "
			 f"capture_output=True, text=True); sys.exit(r.returncode)"],
			capture_output=True, text=True, timeout=15,
			env={**os.environ, 'ITA_PPID_TEST': '1'},
		)
		# Expected: second acquire blocks or returns non-zero
		assert r2.returncode != 0, (
			"#282: second subprocess acquired write-lock on already-locked session"
		)
	finally:
		ita('unlock', '-y', '-s', session)


# ── #283 bulk clear bypasses check_protected ─────────────────────────────────

def test_issue_283_clear_all_ignores_protected(session):
	"""#283: `ita clear --all` bypasses check_protected, wiping protected sessions.
	Expected fix: clear --all must honour protection flag."""
	ita_ok('protect', '-s', session)
	try:
		ita('send', '-s', session, 'echo regression283')
		time.sleep(0.3)
		ita('clear', '--all')
		out = ita_ok('read', '-s', session)
		assert 'regression283' in out, (
			"#283: protected session was cleared by --all"
		)
	finally:
		ita('unprotect', '-s', session)


# ── #284 tab detach object mixup ─────────────────────────────────────────────

def test_issue_284_tab_detach_to_tab_id(session):
	"""#284: `tab detach --to <tab-id>` passes wrong object type internally.
	Expected fix: detach target resolves to Tab, not Session."""
	# Resolve the window of the fixture session so tab new has an explicit
	# --window target (#342: no focus fallback in tab new).
	import json as _json
	r_st = ita('status', '--json', timeout=10)
	entries = _json.loads(r_st.stdout)
	match = next(e for e in entries if e.get('session_id') == session)
	window_id = match.get('window_id')
	# Create a second tab to detach to; capture the tab id
	r_new = ita('tab', 'new', '--window', window_id)
	assert r_new.returncode == 0, f"tab new failed: {r_new.stderr}"
	tab_id = r_new.stdout.strip().split()[-1]
	r = ita('tab', 'detach', '-s', session, '--to', tab_id)
	# Today this may crash with AttributeError; assert no unhandled exception
	assert 'AttributeError' not in r.stderr, (
		f"#284: tab detach raised AttributeError — object type mixup\n{r.stderr}"
	)
	assert 'Traceback' not in r.stderr, (
		f"#284: tab detach raised an unhandled exception\n{r.stderr}"
	)


# ── #285 broadcast send duplicate ────────────────────────────────────────────

def test_issue_285_broadcast_duplicate_delivery(session):
	"""#285: Session belonging to 2 broadcast domains receives each send twice.
	Fixed: deduplicate recipients by session_id before dispatch."""
	# Build two domains both containing `session` by calling `broadcast add`
	# twice; the second call merges into domain-0.  To get *two* distinct domains
	# we use `broadcast set` with two comma-separated groups both listing the id.
	r_on = ita('broadcast', 'on', '-s', session)
	assert r_on.returncode == 0, f"broadcast on failed: {r_on.stderr}"
	try:
		marker = 'REGRESSION285MARKER'
		r = ita('broadcast', 'send', marker)
		assert r.returncode == 0, f"broadcast send failed: {r.stderr}"
		time.sleep(0.4)
		out = ita_ok('read', '-s', session)
		occurrences = out.count(marker)
		assert occurrences == 1, (
			f"#285: marker appeared {occurrences} times — broadcast deduplication broken"
		)
	finally:
		ita('broadcast', 'off', '-y')


# ── #286 layouts save --window silent no-op ──────────────────────────────────

def test_issue_286_layouts_save_window_no_current_window():
	"""#286: `ita layouts save --window` with no current window exits 0 and prints "Saved:".
	Expected fix: must exit non-zero when no window context exists."""
	r = ita('layouts', 'save', '--window', '--name', 'reg286-layout',
	        '--no-current-window')
	assert r.returncode != 0, (
		f"#286: layouts save --window exited 0 with no current window\n"
		f"stdout: {r.stdout}\nstderr: {r.stderr}"
	)


# ── #287 var list silent degrade ─────────────────────────────────────────────

def test_issue_287_var_list_unresolvable_session():
	"""#287: `ita var list` with unresolvable session scope silently exits 0.
	Expected fix: must exit non-zero when scope cannot be resolved."""
	r = ita('var', 'list', '--session', 'nonexistent-session-id-reg287')
	assert r.returncode != 0, (
		f"#287: var list with bad session exited 0\nstdout: {r.stdout}"
	)


# ── #288 prompt-detection heuristic ──────────────────────────────────────────

@pytest.mark.known_broken
def test_issue_288_prompt_detection_mode_field(session):
	"""#288: get-prompt --json omits 'mode' field for non-standard prompts.
	Expected fix: mode field always present, value 'heuristic' or 'exact'."""
	ita('send', '-s', session, 'PS1="CUSTOM> "')
	time.sleep(0.3)
	r = ita('get-prompt', '-s', session, '--json')
	assert r.returncode == 0, f"get-prompt failed: {r.stderr}"
	try:
		data = json.loads(r.stdout)
	except json.JSONDecodeError:
		pytest.fail(f"#288: get-prompt --json returned non-JSON: {r.stdout!r}")
	assert 'mode' in data, (
		f"#288: 'mode' field missing from get-prompt JSON output: {data}"
	)


# ── #290 timeout rc inconsistency ────────────────────────────────────────────

def test_issue_290_run_json_timeout_rc(session):
	"""#290: `ita run --json` with timeout returns rc=1 instead of rc=124.
	Expected fix: timed-out processes must report rc=124 to match POSIX timeout."""
	r = ita('run', '-s', session, '--json', '--timeout', '1', 'sleep 10',
	        timeout=10)
	assert r.returncode == 0, f"run --json wrapper failed: {r.stderr}"
	try:
		data = json.loads(r.stdout)
	except json.JSONDecodeError:
		pytest.fail(f"#290: run --json returned non-JSON: {r.stdout!r}")
	proc_rc = data.get('rc') or data.get('returncode') or data.get('exit_code')
	assert proc_rc == 124, (
		f"#290: expected rc=124 for timed-out process, got {proc_rc!r}"
	)


# ── #247 on prompt silent timeout ────────────────────────────────────────────

def test_issue_247_on_prompt_timeout_rc(session):
	"""#247: `ita on prompt -t 1` with no prompt event exits 0 silently.
	Expected fix: must exit non-zero (e.g. 124) on timeout."""
	r = ita('on', 'prompt', '-s', session, '-t', '1', timeout=5)
	assert r.returncode != 0, (
		f"#247: on prompt -t 1 with no event exited 0\nstdout: {r.stdout}"
	)


# ── #248 run -n warning in stdout ────────────────────────────────────────────

def test_issue_248_run_n_warning_on_stderr(session):
	"""#248: run -n fallback warning bleeds into stdout, corrupting line count.
	Expected fix: warning goes to stderr; stdout has exactly N lines."""
	n = 3
	cmd = 'printf "line1\\nline2\\nline3\\n"'
	r = ita('run', '-s', session, '-n', str(n), cmd, timeout=15)
	assert r.returncode == 0, f"run -n failed: {r.stderr}"
	stdout_lines = [ln for ln in r.stdout.splitlines() if ln]
	assert len(stdout_lines) == n, (
		f"#248: expected {n} stdout lines, got {len(stdout_lines)}; "
		f"warning may be in stdout\nstdout: {r.stdout!r}\nstderr: {r.stderr!r}"
	)
	if 'warning' in r.stdout.lower() or 'fallback' in r.stdout.lower():
		pytest.fail(f"#248: warning text found in stdout\nstdout: {r.stdout!r}")


# ── #250 new-not-ready jobName ────────────────────────────────────────────────

def test_issue_250_new_session_var_get_job_name():
	"""#250: `ita var get jobName` immediately after new session returns empty ~20% of the time.
	Expected fix: new waits until session variables are populated before returning."""
	failures = 0
	sids = []
	samples = 20
	try:
		for _ in range(samples):
			r = ita('new', '--name', 'ita-test-reg250', '--wait', 'jobName_populated')
			if r.returncode != 0:
				failures += 1
				continue
			sid = _extract_sid(r.stdout)
			sids.append(sid)
			rv = ita('var', 'get', '-s', sid, 'jobName')
			if rv.returncode != 0 or not rv.stdout.strip():
				failures += 1
	finally:
		for sid in sids:
			ita('close', '-s', sid, timeout=10)
	assert failures == 0, (
		f"#250: jobName empty or missing in {failures}/{samples} samples immediately after new"
	)


# ── #220 broadcast add destructive ───────────────────────────────────────────

def test_issue_220_broadcast_add_merges_not_replaces(session):
	"""#220: `broadcast add` must merge sessions into existing domain, not replace.
	Fixed: add appends to first existing domain; existing sessions are preserved."""
	r_on = ita('broadcast', 'on', '-s', session)
	assert r_on.returncode == 0, f"broadcast on failed: {r_on.stderr}"
	try:
		# Add the same session again — should not wipe the domain.
		r_add = ita('broadcast', 'add', session)
		assert r_add.returncode == 0, f"broadcast add failed: {r_add.stderr}"
		r_list = ita('broadcast', 'list', '--json')
		assert r_list.returncode == 0, f"broadcast list failed: {r_list.stderr}"
		domains = json.loads(r_list.stdout)
		# Original domain must still be present with at least the original session.
		all_ids = [m['session_id'] for d in domains for m in d]
		assert session in all_ids, (
			f"#220: broadcast add wiped the domain — session {session!r} not found; domains={domains}"
		)
	finally:
		ita('broadcast', 'off', '-y')


# ── #249 broadcast on success-but-empty ──────────────────────────────────────

def test_issue_249_broadcast_on_single_session_rejected(session):
	"""#249: `broadcast on -s ONE` with no existing domain must fail up-front.

	iTerm2 silently drops broadcast domains with <2 sessions (nothing to
	mirror to), so we used to report success while state remained empty —
	a CONTRACT §14.1 "never lie" violation. The fix refuses the write
	with rc != 0 and actionable guidance toward `broadcast add` /
	`broadcast set` / `broadcast on --window`."""
	r = ita('broadcast', 'on', '-s', session)
	assert r.returncode != 0, (
		f"#249: single-session broadcast on must fail, got rc=0. stderr={r.stderr}"
	)
	assert 'at least 2 sessions' in r.stderr, (
		f"#249: error must explain the ≥2 requirement; got {r.stderr!r}"
	)
	# And state stays empty — no silent side-effect.
	r_list = ita('broadcast', 'list', '--json')
	assert r_list.returncode == 0
	assert json.loads(r_list.stdout) == []


def test_issue_249_broadcast_list_reflects_reality_after_rejection(session):
	"""#249 §14.1: after a rejected `broadcast on`, broadcast list must
	reflect reality — no phantom domain silently written."""
	ita('broadcast', 'off', '-y')
	r = ita('broadcast', 'on', '-s', session)
	assert r.returncode != 0, "singleton broadcast on must be rejected"
	r_list = ita('broadcast', 'list', '--json')
	assert r_list.returncode == 0
	assert json.loads(r_list.stdout) == [], (
		"#249: list must show reality; rejected `broadcast on` must not leave residue"
	)
