"""Shared fixtures, helpers, and markers for the ita test suite."""
import json
import subprocess
from pathlib import Path
import pytest

ITA = Path(__file__).parent.parent / 'src' / 'ita.py'

# Prefix used on all test-created sessions so they're identifiable for cleanup.
TEST_SESSION_PREFIX = 'ita-test-'


def ita(*args, timeout=30):
	"""Run an ita subcommand. Returns CompletedProcess."""
	return subprocess.run(
		['uv', 'run', str(ITA)] + list(args),
		capture_output=True, text=True, timeout=timeout,
	)


def ita_ok(*args, **kwargs):
	"""Run ita and assert rc=0. Returns stdout stripped."""
	r = ita(*args, **kwargs)
	assert r.returncode == 0, (
		f"ita {args} failed (rc={r.returncode})\nstdout: {r.stdout}\nstderr: {r.stderr}"
	)
	return r.stdout.strip()


def _all_session_ids() -> set[str]:
	"""Return set of all current iTerm2 session IDs."""
	r = ita('status', '--json', timeout=10)
	if r.returncode != 0:
		return set()
	try:
		sessions = json.loads(r.stdout)
	except (json.JSONDecodeError, ValueError):
		return set()
	return {s['session_id'] for s in sessions}


def _open_test_sessions() -> list[str]:
	"""Return session IDs of any surviving ita-test-* sessions."""
	r = ita('status', '--json', timeout=10)
	if r.returncode != 0:
		return []
	try:
		sessions = json.loads(r.stdout)
	except (json.JSONDecodeError, ValueError):
		return []
	return [
		s['session_id'] for s in sessions
		if s.get('session_name', '').startswith(TEST_SESSION_PREFIX)
	]


def _close_test_sessions(sids: list[str]) -> None:
	"""Close all given session IDs, ignoring errors."""
	for sid in sids:
		ita('close', '-s', sid, timeout=10)


@pytest.fixture
def session(request):
	"""Fresh iTerm2 session per test. Named 'ita-test-<testname>' for leak detection.
	Guaranteed teardown via finalizer (not yield) so it runs even on hard failures."""
	r = ita('new')
	assert r.returncode == 0, f"Failed to create session: {r.stderr}"
	sid = r.stdout.strip()
	assert sid, "Session ID returned empty"
	# Name it so leaked sessions are identifiable
	safe_name = (TEST_SESSION_PREFIX + request.node.name[:30]).replace(' ', '_')
	ita('name', '-s', sid, safe_name)

	def _teardown():
		ita('close', '-s', sid, timeout=10)

	request.addfinalizer(_teardown)
	return sid


@pytest.fixture(scope='module')
def shared_session(request):
	"""Module-scoped session for read-only tests (faster than per-test)."""
	r = ita('new')
	assert r.returncode == 0, f"Failed to create module session: {r.stderr}"
	sid = r.stdout.strip()
	safe_name = (TEST_SESSION_PREFIX + 'shared-' + request.module.__name__[:20]).replace(' ', '_')
	ita('name', '-s', sid, safe_name)

	def _teardown():
		ita('close', '-s', sid, timeout=10)

	request.addfinalizer(_teardown)
	return sid


@pytest.fixture(autouse=True, scope='session')
def sweep_leaked_sessions():
	"""Snapshot sessions before the run; clean up any new ones that survived after.

	Pre-run: closes any ita-test-* sessions from a previous aborted run.
	Post-run: closes any sessions that appeared DURING this run and weren't cleaned
	          up by individual test teardowns (covers inline session creation too)."""
	# Pre-run: close survivors from previous runs
	old_survivors = _open_test_sessions()
	if old_survivors:
		_close_test_sessions(old_survivors)
	# Snapshot: record which sessions existed BEFORE any test ran
	baseline = _all_session_ids()
	yield
	# Post-run: close everything that appeared during the test run and is still open
	after = _all_session_ids()
	leaked = after - baseline
	if leaked:
		_close_test_sessions(list(leaked))


def pytest_configure(config):
	config.addinivalue_line('markers', 'integration: requires live iTerm2 with Python API')
	config.addinivalue_line('markers', 'stress: slow cross-session / load tests')
	config.addinivalue_line('markers', 'regression: guards against known fixed bugs')
	config.addinivalue_line('markers', 'known_broken: documents known bug, expected to fail until fixed')


def pytest_collection_modifyitems(config, items):
	"""Auto-skip integration/stress if iTerm2 unreachable."""
	iterm2_up = ita('status', timeout=5).returncode == 0
	skip = pytest.mark.skip(reason='iTerm2 not reachable')
	for item in items:
		if not iterm2_up and ('integration' in item.keywords or 'stress' in item.keywords):
			item.add_marker(skip)
