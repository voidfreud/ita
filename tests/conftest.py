"""Shared fixtures, helpers, and markers for the ita test suite."""
import pytest

from helpers import (  # noqa: F401
	ITA, ita, ita_ok, _extract_sid, _all_session_ids,
	_open_test_sessions, _close_test_sessions,
	TEST_SESSION_PREFIX,
)

# Import fixtures from sub-package so pytest collects them.
# hypothesis_profiles are registered at import time inside fixtures.environment.
from fixtures import session_factory, broadcast_domain, protected_session, clean_iterm, shell  # noqa: F401


@pytest.fixture
def session(request):
	"""Fresh iTerm2 session per test. Named 'ita-test-<testname>' for leak detection.
	Guaranteed teardown via finalizer (not yield) so it runs even on hard failures."""
	safe_name = (TEST_SESSION_PREFIX + request.node.name[:30]).replace(' ', '_')
	r = ita('new', '--name', safe_name)
	assert r.returncode == 0, f"Failed to create session: {r.stderr}"
	sid = _extract_sid(r.stdout)
	assert sid, "Session ID returned empty"

	def _teardown():
		ita('close', '-s', sid, timeout=10)

	request.addfinalizer(_teardown)
	return sid


@pytest.fixture(scope='module')
def shared_session(request):
	"""Module-scoped session for read-only tests (faster than per-test)."""
	safe_name = (TEST_SESSION_PREFIX + 'shared-' + request.module.__name__[:20]).replace(' ', '_')
	r = ita('new', '--name', safe_name)
	assert r.returncode == 0, f"Failed to create module session: {r.stderr}"
	sid = _extract_sid(r.stdout)

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
