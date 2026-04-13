"""Signal-interruption regression tests — agent-plugin scenario.

An agent process may SIGINT/SIGTERM/SIGKILL ita subprocesses at any point.
These tests assert clean exit, no zombie sessions, no corrupt locks.
"""
import json
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ita, _all_session_ids

ITA = ['python', '-m', 'ita']

pytestmark = [pytest.mark.adversarial, pytest.mark.integration]


# ── helpers ───────────────────────────────────────────────────────────────────

def _popen(*args):
	"""Start ita subcommand via Popen. Returns Popen object."""
	return subprocess.Popen(
		['uv', 'run', *ITA] + list(args),
		stdout=subprocess.PIPE,
		stderr=subprocess.PIPE,
		text=True,
	)


def _interrupt_and_wait(proc, sig=signal.SIGINT, wait_timeout=5):
	"""Send sig to proc, wait up to wait_timeout seconds. Returns (rc, stdout, stderr)."""
	time.sleep(0.4)  # let it start
	proc.send_signal(sig)
	try:
		proc.wait(timeout=wait_timeout)
	except subprocess.TimeoutExpired:
		proc.kill()
		proc.wait()
	stdout = proc.stdout.read() if proc.stdout else ''
	stderr = proc.stderr.read() if proc.stderr else ''
	return proc.returncode, stdout, stderr


def _no_traceback(stderr: str) -> bool:
	return 'Traceback' not in stderr and 'Error\n' not in stderr


# ── 1. SIGINT during `ita run 'sleep 10'` ────────────────────────────────────

def test_sigint_during_run(session_factory):
	"""SIGINT mid-run: rc != 0, no traceback, originating session still alive."""
	sids = session_factory(1)
	sid = sids[0]

	proc = _popen('run', 'sleep 10', '-s', sid)
	rc, _, stderr = _interrupt_and_wait(proc, signal.SIGINT)

	assert rc != 0, f"expected non-zero exit after SIGINT, got {rc}"
	assert _no_traceback(stderr), f"traceback in stderr:\n{stderr}"
	# session must still be reachable
	r = ita('status', '--json')
	alive = {s['session_id'] for s in json.loads(r.stdout or '[]')}
	assert sid in alive, "session died after SIGINT to ita run"


# ── 2. SIGTERM during `ita run 'sleep 10'` ───────────────────────────────────

def test_sigterm_during_run(session_factory):
	"""SIGTERM mid-run: rc != 0, no traceback, session still alive."""
	sids = session_factory(1)
	sid = sids[0]

	proc = _popen('run', 'sleep 10', '-s', sid)
	rc, _, stderr = _interrupt_and_wait(proc, signal.SIGTERM)

	assert rc != 0, f"expected non-zero exit after SIGTERM, got {rc}"
	assert _no_traceback(stderr), f"traceback in stderr:\n{stderr}"
	r = ita('status', '--json')
	alive = {s['session_id'] for s in json.loads(r.stdout or '[]')}
	assert sid in alive, "session died after SIGTERM to ita run"


# ── 3. SIGINT during `ita on session-end` ────────────────────────────────────

def test_sigint_during_on_session_end():
	"""SIGINT while waiting for session-end: exits within 2 s, no zombie process."""
	proc = _popen('on', 'session-end', '--timeout', '60')
	t0 = time.monotonic()
	proc.send_signal(signal.SIGINT)
	try:
		proc.wait(timeout=2)
	except subprocess.TimeoutExpired:
		proc.kill()
		proc.wait()
		pytest.fail("ita on session-end did not exit within 2 s after SIGINT")

	elapsed = time.monotonic() - t0
	assert elapsed < 3, f"too slow to exit: {elapsed:.1f}s"
	_, stderr = proc.stdout.read(), proc.stderr.read()
	assert _no_traceback(stderr), f"traceback:\n{stderr}"


# ── 4. SIGKILL during `ita run` — no dangling write-lock ─────────────────────

def test_sigkill_no_dangling_lock(session_factory):
	"""SIGKILL must not leave a write-lock that blocks subsequent runs."""
	sids = session_factory(1)
	sid = sids[0]

	proc = _popen('run', 'sleep 10', '-s', sid)
	time.sleep(0.4)
	proc.send_signal(signal.SIGKILL)
	proc.wait(timeout=5)

	# Second invocation must succeed (no stale lock)
	r = ita('run', 'echo hi', '-s', sid, timeout=15)
	assert r.returncode == 0, (
		f"second run failed after SIGKILL — possible dangling lock\n"
		f"stdout: {r.stdout}\nstderr: {r.stderr}"
	)
	assert 'hi' in r.stdout, f"expected 'hi' in output, got: {r.stdout!r}"


# ── 5. SIGINT during `ita broadcast send` mid-delivery ───────────────────────

def test_sigint_during_broadcast_send(broadcast_domain):
	"""SIGINT mid-broadcast: partial delivery tolerated, no crash, siblings intact."""
	sids = broadcast_domain  # 2 sessions already in broadcast-on group

	proc = _popen('broadcast', 'send', 'hello world')
	rc, _, stderr = _interrupt_and_wait(proc, signal.SIGINT, wait_timeout=5)

	# rc may be 0 (completed before signal) or non-zero — both acceptable
	assert _no_traceback(stderr), f"traceback after SIGINT on broadcast send:\n{stderr}"
	# sibling sessions must remain reachable
	r = ita('status', '--json')
	alive = {s['session_id'] for s in json.loads(r.stdout or '[]')}
	for sid in sids:
		assert sid in alive, f"session {sid} vanished after broadcast SIGINT"


# ── 6. SIGINT during `ita new` — no half-created session leaked ──────────────

def test_sigint_during_new():
	"""SIGINT during session creation must not leak a half-created session."""
	before = _all_session_ids()

	proc = _popen('new', '--name', 'ita-test-signal-new-leak')
	time.sleep(0.1)  # interrupt very early, before connection fully established
	proc.send_signal(signal.SIGINT)
	try:
		proc.wait(timeout=5)
	except subprocess.TimeoutExpired:
		proc.kill()
		proc.wait()

	time.sleep(0.5)  # give iTerm2 a moment to reflect any creation
	after = _all_session_ids()
	new_sessions = after - before

	# Allow at most 1 new session (race: signal arrived after creation completed)
	# but it must be closeable — not a zombie
	assert len(new_sessions) <= 1, (
		f"SIGINT during new leaked {len(new_sessions)} unexpected sessions: {new_sessions}"
	)
	# Clean up any session that did get created
	for sid in new_sessions:
		ita('close', '-s', sid, timeout=10)


# ── 7. SIGTERM during `ita stabilize` — known_broken pending #268 ─────────────

@pytest.mark.known_broken
@pytest.mark.xfail(
	reason="ita stabilize not yet implemented (#268); test is a regression anchor",
	strict=False,
)
def test_sigterm_during_stabilize(session_factory):
	"""SIGTERM during stabilize must not corrupt session state."""
	sids = session_factory(1)
	sid = sids[0]

	proc = _popen('stabilize', '-s', sid)
	rc, _, stderr = _interrupt_and_wait(proc, signal.SIGTERM)

	assert _no_traceback(stderr), f"traceback after SIGTERM on stabilize:\n{stderr}"
	# Session still reachable
	r = ita('status', '--json')
	alive = {s['session_id'] for s in json.loads(r.stdout or '[]')}
	assert sid in alive, "session vanished after SIGTERM to stabilize"


# ── 8. SIGINT during parallel writers — #282-related ─────────────────────────

def test_sigint_during_parallel_writers(session_factory):
	"""SIGINT one of N parallel run invocations — others must complete or fail cleanly.

	Related to #282 (write-lock PPID). Assert no traceback and no lock starvation
	on subsequent invocations.
	"""
	sids = session_factory(2)

	procs = [_popen('run', 'sleep 10', '-s', sid) for sid in sids]
	time.sleep(0.4)

	# Kill only the first writer
	procs[0].send_signal(signal.SIGINT)
	try:
		procs[0].wait(timeout=5)
	except subprocess.TimeoutExpired:
		procs[0].kill()
		procs[0].wait()

	# Let the second one also receive SIGINT
	procs[1].send_signal(signal.SIGINT)
	try:
		procs[1].wait(timeout=5)
	except subprocess.TimeoutExpired:
		procs[1].kill()
		procs[1].wait()

	for proc in procs:
		stderr = proc.stderr.read() if proc.stderr else ''
		assert _no_traceback(stderr), f"traceback in parallel writer after SIGINT:\n{stderr}"

	# Both sessions still usable — no lock starvation
	for sid in sids:
		r = ita('run', 'echo ok', '-s', sid, timeout=15)
		assert r.returncode == 0, (
			f"session {sid} unusable after parallel SIGINT\nstderr: {r.stderr}"
		)
