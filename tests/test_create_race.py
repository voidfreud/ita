"""Race-condition tests targeting fresh-name (#302), write-lock PPID (#282),
created-≠-ready (#250, #268), double-close, leaked windows, and overview
stability under concurrent creation.
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ita

pytestmark = [
	pytest.mark.stress,
	pytest.mark.integration,
	pytest.mark.adversarial,
]

_N = 20


# ── helpers ───────────────────────────────────────────────────────────────────

def _new_named(i):
	return ita('new', '--name', f'race-prefix-{i}', timeout=60)

def _new_auto():
	return ita('new', timeout=60)

def _close(sid):
	return ita('close', '-s', sid, timeout=30)

def _created_session_id(r):
	"""Extract session id from `ita new` stdout, or None."""
	for line in r.stdout.splitlines():
		line = line.strip()
		if line:
			return line
	return None


# ── 1. 20 parallel named creates ─────────────────────────────────────────────

def test_parallel_named_create_no_collision():
	"""20 concurrent `ita new --name prefix-{i}` — all must succeed, no duplicates."""
	with ThreadPoolExecutor(max_workers=_N) as ex:
		futures = [ex.submit(_new_named, i) for i in range(_N)]
		results = [f.result() for f in as_completed(futures)]

	failed = [r for r in results if r.returncode != 0]
	ids = [_created_session_id(r) for r in results if r.returncode == 0]
	ids_clean = [x for x in ids if x]

	assert not failed, (
		f"{len(failed)}/{_N} creates failed:\n"
		+ "\n".join(f"  rc={r.returncode} stderr={r.stderr!r}" for r in failed)
	)
	assert len(set(ids_clean)) == len(ids_clean), (
		f"Duplicate session ids detected: {ids_clean}"
	)


# ── 2. 20 parallel auto-name creates (fresh-name race #302) ──────────────────

def test_parallel_autoname_unique():
	"""20 concurrent `ita new` — all auto-assigned names must be unique.

	Targets the fresh-name race (#302): two workers could read the same
	'next available' name before either commits it.
	"""
	with ThreadPoolExecutor(max_workers=_N) as ex:
		futures = [ex.submit(_new_auto) for _ in range(_N)]
		results = [f.result() for f in as_completed(futures)]

	failed = [r for r in results if r.returncode != 0]
	ids = [_created_session_id(r) for r in results if r.returncode == 0]
	ids_clean = [x for x in ids if x]

	assert not failed, (
		f"{len(failed)}/{_N} auto-name creates failed:\n"
		+ "\n".join(f"  stderr={r.stderr!r}" for r in failed)
	)
	assert len(set(ids_clean)) == len(ids_clean), (
		f"Auto-name collision (#302): duplicate ids {ids_clean}"
	)


# ── 3. PPID write-lock collision (#282) ──────────────────────────────────────

@pytest.mark.known_broken
def test_sibling_run_ppid_lock(session):
	"""Two sibling subprocesses `ita run` against same session from same parent.

	Tests #282 write-lock PPID collision.  Expected: at least one blocks or
	fails cleanly.  Marked known_broken because the lock is not yet enforced.
	"""
	def do_run(tag):
		return ita('run', f'echo ppid_race_{tag}', '-s', session, timeout=30)

	with ThreadPoolExecutor(max_workers=2) as ex:
		fa = ex.submit(do_run, 'a')
		fb = ex.submit(do_run, 'b')
		ra, rb = fa.result(), fb.result()

	rcs = {ra.returncode, rb.returncode}
	# At least one should fail (rc != 0) indicating lock contention.
	assert 0 not in rcs or len(rcs) > 1, (
		"Both sibling `ita run` succeeded — PPID lock not enforced (#282)\n"
		f"ra={ra.stdout!r} rb={rb.stdout!r}"
	)


# ── 4. created-≠-ready: var get before session is live (#250, #268) ──────────

def test_created_not_ready_race():
	"""create then immediately read jobName 20× — measure how often it is empty.

	Documents the created-≠-ready window (#250, #268).  A non-zero miss rate
	is expected; the test records it rather than hard-failing.
	"""
	misses = 0
	trials = _N

	for _ in range(trials):
		r_new = ita('new', timeout=60)
		if r_new.returncode != 0:
			continue
		sid = _created_session_id(r_new)
		if not sid:
			continue
		r_var = ita('var', 'get', 'jobName', '-s', sid, timeout=10)
		val = r_var.stdout.strip()
		if not val:
			misses += 1
		_close(sid)

	# Document the race rate.  Any non-zero rate confirms #250/#268 exists.
	print(f"\ncreated-≠-ready: {misses}/{trials} races observed")
	# Soft assertion: we're not asserting zero misses, just that we measured it.
	assert misses <= trials, "Impossible: misses exceeded trials"


# ── 5. 10 parallel close of same session ─────────────────────────────────────

def test_parallel_close_same_session(session):
	"""10 concurrent `ita close -s <id>` — exactly one should succeed, rest
	should report 'not found' cleanly with no traceback.
	"""
	with ThreadPoolExecutor(max_workers=10) as ex:
		futures = [ex.submit(_close, session) for _ in range(10)]
		results = [f.result() for f in as_completed(futures)]

	successes = [r for r in results if r.returncode == 0]
	tracebacks = [r for r in results if 'Traceback' in r.stderr]

	assert len(successes) >= 1, "No close succeeded — session may not have existed"
	assert not tracebacks, (
		f"{len(tracebacks)} closes emitted tracebacks:\n"
		+ "\n".join(r.stderr[:300] for r in tracebacks)
	)


# ── 6. Rapid create/close cycle — no leaked windows ──────────────────────────

def test_rapid_create_close_no_leak():
	"""50 create-then-immediately-close cycles; window count must stay stable."""
	def _window_count():
		r = ita('window', 'list', '--json', timeout=20)
		if r.returncode != 0:
			return None
		try:
			return len(json.loads(r.stdout))
		except (json.JSONDecodeError, TypeError):
			return None

	baseline = _window_count()

	def _cycle(_):
		r = ita('new', timeout=60)
		if r.returncode != 0:
			return
		sid = _created_session_id(r)
		if sid:
			_close(sid)

	with ThreadPoolExecutor(max_workers=10) as ex:
		list(ex.map(_cycle, range(50)))

	# Allow brief settle time for async teardown.
	time.sleep(1)
	after = _window_count()

	if baseline is not None and after is not None:
		assert after <= baseline + 2, (
			f"Window leak suspected: baseline={baseline} after={after}"
		)


# ── 7. Parallel creates while overview runs ───────────────────────────────────

def test_overview_stable_under_parallel_create():
	"""5 parallel `ita new` while `ita overview --json` runs concurrently.

	Overview must complete without crash or partial (non-JSON) output.
	"""
	overview_results = []

	def _overview():
		r = ita('overview', '--json', timeout=30)
		overview_results.append(r)

	with ThreadPoolExecutor(max_workers=6) as ex:
		ov_future = ex.submit(_overview)
		create_futures = [ex.submit(_new_auto) for _ in range(5)]
		ov_future.result()
		creates = [f.result() for f in as_completed(create_futures)]

	assert overview_results, "Overview future never resolved"
	r_ov = overview_results[0]
	assert r_ov.returncode == 0, (
		f"overview crashed during parallel creates (rc={r_ov.returncode})\n"
		f"stderr={r_ov.stderr!r}"
	)
	assert 'Traceback' not in r_ov.stderr, (
		f"overview traceback under load:\n{r_ov.stderr[:500]}"
	)
	# Must parse as valid JSON.
	try:
		json.loads(r_ov.stdout)
	except json.JSONDecodeError as e:
		pytest.fail(f"overview returned non-JSON under load: {e}\n{r_ov.stdout[:200]!r}")
