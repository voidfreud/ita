"""Shared fixtures, helpers, and markers for the ita test suite.

Cleanup discipline (TESTING.md §4.1, #341):
  L1 — per-test addfinalizer in `session` / `shared_session`
  L2 — try/finally inside multi-create fixtures (session_factory etc.)
  L3 — atexit hook that closes every `ita-test-*` session
  L4 — hard-ceiling sentinel: > 50 ita-test-* sessions aborts the run
  L5 — prefer tabs over windows (smaller blast radius per leak)

Layers L3 + L4 added here as the catastrophic-leak circuit breaker.
"""
import atexit
import pytest

from helpers import (  # noqa: F401
	ITA, ita, ita_ok, _extract_sid, _all_session_ids,
	_open_test_sessions, _close_test_sessions,
	_all_window_ids, _close_window, _close_orphan_default_windows,
	_orphan_default_windows,
	TEST_SESSION_PREFIX,
)


# ── L3: atexit safety net ──────────────────────────────────────────────────
# Runs even on signal / unhandled exception / pytest internal crash.
# Belt-and-braces: if every other layer fails, this still closes orphans.

def _atexit_close_test_sessions():
	"""Last-ditch cleanup. Idempotent. Best-effort: swallows all errors so
	atexit can never itself crash the interpreter.

	Closes test sessions AND orphan default windows (#348) — iTerm2 spawns
	a default shell when an empty window loses its session, so closing the
	session leaves the window. Sweeping orphans here catches that gap."""
	try:
		survivors = _open_test_sessions()
		if survivors:
			_close_test_sessions(survivors)
	except Exception:
		pass
	try:
		_close_orphan_default_windows()
	except Exception:
		pass

atexit.register(_atexit_close_test_sessions)


# ── L4: hard-ceiling sentinel ──────────────────────────────────────────────
# Between tests, count `ita-test-*` sessions. If > LEAK_CEILING, abort the
# entire pytest run loudly. Stops a leaky test from cascading into 500
# sessions and crashing the host.

LEAK_CEILING = 50


def _count_test_sessions() -> int:
	try:
		return len(_open_test_sessions())
	except Exception:
		return 0


def _count_orphan_windows() -> int:
	try:
		return len(_orphan_default_windows())
	except Exception:
		return 0


def pytest_runtest_teardown(item, nextitem):
	"""After every test, check the leak ceiling on BOTH ita-test-* sessions
	AND orphan default windows (#348). Hard-abort if either exceeded —
	emergency-close survivors first so the abort itself doesn't leave the
	machine in a worse state."""
	sess_count = _count_test_sessions()
	win_count = _count_orphan_windows()
	if sess_count > LEAK_CEILING or win_count > LEAK_CEILING:
		try:
			_close_test_sessions(_open_test_sessions())
		except Exception:
			pass
		try:
			_close_orphan_default_windows()
		except Exception:
			pass
		pytest.exit(
			f"\n\n*** LEAK CEILING EXCEEDED ***\n"
			f"  ita-test-* sessions: {sess_count}\n"
			f"  orphan default windows: {win_count}\n"
			f"  ceiling per kind: {LEAK_CEILING}\n"
			f"A test created objects without cleaning them up. The run is "
			f"aborted to protect the host machine. Last test: {item.nodeid}\n",
			returncode=2,
		)

# Import fixtures from sub-package so pytest collects them.
# hypothesis_profiles are registered at import time inside fixtures.environment.
from fixtures import session_factory, broadcast_domain, protected_session, clean_iterm, shell  # noqa: F401


@pytest.fixture
def session(request):
	"""Fresh iTerm2 session per test. Named 'ita-test-<testname>' for leak detection.
	Guaranteed teardown via finalizer (not yield) so it runs even on hard failures.

	#348: snapshots windows BEFORE create; if `ita new` produced a NEW window,
	closes that window in teardown too (otherwise iTerm2 leaves an orphan
	default-shell window behind when our session is closed).
	"""
	safe_name = (TEST_SESSION_PREFIX + request.node.name[:30]).replace(' ', '_')
	windows_before = _all_window_ids()
	r = ita('new', '--name', safe_name)
	assert r.returncode == 0, f"Failed to create session: {r.stderr}"
	sid = _extract_sid(r.stdout)
	assert sid, "Session ID returned empty"
	new_windows = _all_window_ids() - windows_before

	def _teardown():
		ita('close', '-s', sid, timeout=10)
		for wid in new_windows:
			_close_window(wid)

	request.addfinalizer(_teardown)
	return sid


@pytest.fixture(scope='module')
def shared_session(request):
	"""Module-scoped session for read-only tests (faster than per-test).

	#348: same window-tracking discipline as `session`."""
	safe_name = (TEST_SESSION_PREFIX + 'shared-' + request.module.__name__[:20]).replace(' ', '_')
	windows_before = _all_window_ids()
	r = ita('new', '--name', safe_name)
	assert r.returncode == 0, f"Failed to create module session: {r.stderr}"
	sid = _extract_sid(r.stdout)
	new_windows = _all_window_ids() - windows_before

	def _teardown():
		ita('close', '-s', sid, timeout=10)
		for wid in new_windows:
			_close_window(wid)

	request.addfinalizer(_teardown)
	return sid


@pytest.fixture(autouse=True, scope='session')
def sweep_leaked_sessions():
	"""Snapshot sessions + windows before the run; clean up new ones after.

	Pre-run: closes any ita-test-* sessions from a previous aborted run, plus
	any orphan default windows (#348).
	Post-run: closes any sessions or windows that appeared during the run."""
	# Pre-run: close survivors from previous runs
	old_survivors = _open_test_sessions()
	if old_survivors:
		_close_test_sessions(old_survivors)
	_close_orphan_default_windows()
	# Snapshot: what existed BEFORE any test ran
	baseline_sessions = _all_session_ids()
	baseline_windows = _all_window_ids()
	yield
	# Post-run: close everything that appeared during the test run
	after_sessions = _all_session_ids()
	leaked = after_sessions - baseline_sessions
	if leaked:
		_close_test_sessions(list(leaked))
	# Window-leak sweep (#348): any window present now that wasn't pre-run is
	# either an orphan or test-created. Close orphans by heuristic; user windows
	# are protected because they don't match the "single-Default-session" shape.
	after_windows = _all_window_ids()
	new_windows = after_windows - baseline_windows
	if new_windows:
		_close_orphan_default_windows()


def pytest_configure(config):
	config.addinivalue_line('markers', 'integration: requires live iTerm2 with Python API')
	config.addinivalue_line('markers', 'stress: slow cross-session / load tests')
	config.addinivalue_line('markers', 'regression: guards against known fixed bugs')
	config.addinivalue_line('markers', 'known_broken: documents known bug, expected to fail until fixed')
	config.addinivalue_line('markers', 'contract: cross-cutting contract tests (json, exit codes, hygiene)')
	config.addinivalue_line('markers', 'edge: edge-case tests')
	config.addinivalue_line('markers', 'error: error-path tests')
	config.addinivalue_line('markers', 'state: state/idempotency tests')
	config.addinivalue_line('markers', 'property: hypothesis property-based tests')
	config.addinivalue_line('markers', 'adversarial: concurrent / race-condition tests')
	config.addinivalue_line('markers', 'perf: latency benchmark tests')
	config.addinivalue_line('markers', 'shell_matrix: cross-shell compatibility tests (bash/zsh/fish)')
	config.addinivalue_line('markers', 'broadcast: broadcast-domain tests')
	config.addinivalue_line('markers', 'xfail_flaky: async race — filed as bug, not fixed here')


def pytest_collection_modifyitems(config, items):
	"""Auto-skip integration/stress if iTerm2 unreachable."""
	iterm2_up = ita('status', timeout=5).returncode == 0
	skip = pytest.mark.skip(reason='iTerm2 not reachable')
	for item in items:
		if not iterm2_up and ('integration' in item.keywords or 'stress' in item.keywords):
			item.add_marker(skip)
