"""Adversarial concurrency & lifecycle tests — step 3 of issue #136.

Scenarios covered:
  1. Two concurrent `ita run` against the same session simultaneously.
  2. Stale session mid-command: session force-closed while `ita run` is in flight.
  3. Broadcast drift: broadcast domain with half the sessions externally closed.
  7. Rapid create/destroy: 100 new/close pairs in a tight loop.
  8. Disconnect during event wait: `ita on session-end` subprocess killed mid-wait.

NOT covered here: profile-deleted-mid-theme (scenario 4) — the race window is too
tight to trigger reliably without an internal hook; skipped per charter §3.
"""
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ita

pytestmark = [pytest.mark.adversarial, pytest.mark.integration]


# ── 1. Concurrent run — same session ─────────────────────────────────────────

@pytest.mark.adversarial
@pytest.mark.integration
def test_concurrent_run_same_session(session):
	"""Two `ita run` issued simultaneously against ONE session.

	The interesting question is NOT whether they both succeed (serialized) but
	whether the process exits cleanly in all cases — no hang, no uncaught
	exception, no zombie subprocess.  Whatever the actual behavior (serial,
	interleaved, second-errors), lock it down so regressions show up.
	"""
	results = {}

	def do_run(key, cmd):
		results[key] = ita('run', cmd, '-s', session, timeout=30)

	t1 = threading.Thread(target=do_run, args=('a', 'echo concurrent_same_a'))
	t2 = threading.Thread(target=do_run, args=('b', 'echo concurrent_same_b'))
	t1.start()
	t2.start()
	t1.join(timeout=35)
	t2.join(timeout=35)

	assert 'a' in results, "Thread A never completed — potential hang"
	assert 'b' in results, "Thread B never completed — potential hang"

	# Both must exit cleanly.  rc=0 (serialized) or rc=1 (contention error) are
	# both acceptable; rc>1 / uncaught exception / hang are NOT.
	rc_a = results['a'].returncode
	rc_b = results['b'].returncode
	assert rc_a in (0, 1), (
		f"Concurrent run A: unexpected rc={rc_a}\n"
		f"stdout:{results['a'].stdout!r}\nstderr:{results['a'].stderr!r}"
	)
	assert rc_b in (0, 1), (
		f"Concurrent run B: unexpected rc={rc_b}\n"
		f"stdout:{results['b'].stdout!r}\nstderr:{results['b'].stderr!r}"
	)

	# At least one must succeed (we're not testing a lock that rejects all).
	assert rc_a == 0 or rc_b == 0, (
		"Both concurrent runs failed — possible deadlock or unexpected lock behaviour. "
		f"rc_a={rc_a}, rc_b={rc_b}"
	)


# ── 2. Stale session mid-command ──────────────────────────────────────────────

@pytest.mark.adversarial
@pytest.mark.integration
def test_stale_session_mid_run():
	"""Start a long `ita run --timeout 30`; externally close the session mid-flight.

	ita must exit cleanly: no hang beyond the subprocess timeout, no bare
	Python traceback in stderr.  rc may be non-zero (error path is fine).

	Potential bug: if ita hangs waiting on iTerm2 callback after the session
	disappears, this test will reach its own timeout.  Tag known_broken if so.
	"""
	r_new = ita('new')
	assert r_new.returncode == 0, f"Could not create session: {r_new.stderr}"
	sid = r_new.stdout.strip().split('\t')[-1]

	run_result = {}
	exception_holder = {}

	def do_long_run():
		try:
			run_result['r'] = ita('run', 'sleep 30', '--timeout', '30', '-s', sid, timeout=40)
		except subprocess.TimeoutExpired as e:
			exception_holder['timeout'] = e

	t = threading.Thread(target=do_long_run)
	t.start()

	# Give ita time to start and connect to the session before we kill it.
	time.sleep(2)
	ita('close', '-s', sid, timeout=10)

	t.join(timeout=45)

	assert not t.is_alive(), (
		"ita run hung after session was closed — potential deadlock. "
		"This is a bug candidate: ita should detect session-gone and exit."
	)
	assert 'timeout' not in exception_holder, (
		"subprocess.TimeoutExpired: ita run did not exit within 40 s after "
		"session was force-closed. Hang bug candidate."
	)

	r = run_result.get('r')
	if r is not None:
		# No bare traceback — stderr may carry an error message, that's fine.
		assert 'Traceback (most recent call last)' not in r.stderr, (
			f"Uncaught Python exception after session close:\n{r.stderr}"
		)


# ── 3. Broadcast drift — dead sessions in domain ─────────────────────────────

@pytest.mark.adversarial
@pytest.mark.integration
def test_broadcast_drift_dead_sessions():
	"""broadcast on a set of sessions, externally close half, then broadcast send.

	ita must not crash.  Acceptable outcomes: partial success, skip dead handles,
	or rc=1 with a clear error.  Unacceptable: unhandled exception, hang.
	"""
	# Spin up 4 sessions manually (no session_factory fixture yet — TODO #237).
	sids = []
	try:
		for i in range(4):
			r = ita('new')
			assert r.returncode == 0, f"Failed to create session {i}: {r.stderr}"
			sids.append(r.stdout.strip().split('\t')[-1])

		time.sleep(1)

		# Enable broadcast on all four.
		for sid in sids:
			r = ita('broadcast', 'on', '-s', sid)
			assert r.returncode == 0, f"broadcast on failed for {sid}: {r.stderr}"

		# Close the second half while the domain is still active.
		dead = sids[2:]
		for sid in dead:
			ita('close', '-s', sid, timeout=10)

		time.sleep(0.5)

		# Now broadcast send — must not crash.
		r = ita('broadcast', 'send', 'echo drift_test')
		assert r.returncode in (0, 1), (
			f"broadcast send to partially-dead domain: unexpected rc={r.returncode}\n"
			f"stdout:{r.stdout!r}\nstderr:{r.stderr!r}"
		)
		assert 'Traceback (most recent call last)' not in r.stderr, (
			f"Uncaught exception during broadcast send to dead handles:\n{r.stderr}"
		)

	finally:
		ita('broadcast', 'off')
		# Clean up surviving sessions.
		for sid in sids:
			ita('close', '-s', sid, timeout=10)


# ── 7. Rapid create/destroy ───────────────────────────────────────────────────

@pytest.mark.adversarial
@pytest.mark.integration
def test_rapid_create_destroy():
	"""100 `ita new` / `ita close` pairs in a tight loop.

	Goal: no orphaned sessions, no crash, window count roughly stable.

	Note: without the `clean_iterm` fixture (planned, #237) we can't do a hard
	diff of window counts.  We approximate by counting ita-test-* sessions
	before and after and asserting the delta is ≤ 2 (to tolerate the teardown
	fixture's own session).

	TODO: tighten to an exact assertion once `clean_iterm` lands.
	"""
	import json

	def _session_count():
		r = ita('status', '--json', timeout=10)
		if r.returncode != 0:
			return -1
		try:
			return len(json.loads(r.stdout))
		except (json.JSONDecodeError, ValueError):
			return -1

	baseline = _session_count()
	errors = []

	for i in range(100):
		r_new = ita('new', timeout=15)
		if r_new.returncode != 0:
			errors.append(f"new #{i}: rc={r_new.returncode} {r_new.stderr[:80]}")
			continue
		sid = r_new.stdout.strip().split('\t')[-1]
		r_close = ita('close', '-s', sid, timeout=10)
		if r_close.returncode != 0:
			errors.append(f"close #{i} ({sid}): rc={r_close.returncode} {r_close.stderr[:80]}")

	# Allow a few failures — iTerm2 can throttle.
	assert len(errors) <= 5, (
		f"Too many new/close failures ({len(errors)}/100):\n" + "\n".join(errors[:10])
	)

	# Window count should roughly return to baseline (allow ±3 for timing slop).
	after = _session_count()
	if baseline >= 0 and after >= 0:
		assert abs(after - baseline) <= 3, (
			f"Session count drifted after 100 create/destroy cycles: "
			f"baseline={baseline}, after={after}. "
			f"Possible orphan leak — TODO: tighten with clean_iterm (#237)."
		)


# ── 8. Disconnect during event wait ──────────────────────────────────────────

@pytest.mark.adversarial
@pytest.mark.integration
def test_disconnect_during_event_wait(session):
	"""`ita on session-end` in a subprocess; SIGTERM the subprocess mid-wait.

	Expected: subprocess exits with signal termination (rc < 0 on Unix) or 1.
	Forbidden: zombie subprocess, hung process, uncaught Python traceback printed
	before death.
	"""
	import signal

	proc = subprocess.Popen(
		['uv', 'run', 'python', '-m', 'ita',
		 'on', 'session-end', '-t', '30', '-s', session],
		stdout=subprocess.PIPE,
		stderr=subprocess.PIPE,
		text=True,
	)

	# Let it start and register with iTerm2.
	time.sleep(2)

	# Send SIGTERM — clean shutdown signal.
	proc.send_signal(signal.SIGTERM)

	try:
		stdout, stderr = proc.communicate(timeout=10)
	except subprocess.TimeoutExpired:
		proc.kill()
		proc.communicate()
		pytest.fail(
			"ita on session-end did not exit within 10 s after SIGTERM — "
			"zombie/hang bug candidate. Should be filed as a known bug."
		)

	# rc < 0 means killed by signal (expected on SIGTERM if no handler),
	# rc = 0 or 1 means clean exit.  rc > 1 suggests a crash.
	rc = proc.returncode
	assert rc in (-15, -2, 0, 1), (
		f"`ita on session-end` after SIGTERM: unexpected rc={rc}\n"
		f"stdout:{stdout!r}\nstderr:{stderr!r}"
	)
	assert 'Traceback (most recent call last)' not in stderr, (
		f"Uncaught Python exception on SIGTERM:\n{stderr}"
	)
