"""Invariant: fresh sessions become ready within a reasonable budget.

After `ita new`, poll until the session accepts a command or the budget
expires. Budget = 10s per session.

`ita stabilize` is now implemented (#268); xfail markers removed.

Marks: @pytest.mark.contract + @pytest.mark.integration
"""
import time
import pytest

from conftest import ita, ita_ok, _extract_sid, TEST_SESSION_PREFIX

_READY_BUDGET = 10  # seconds
_POLL_INTERVAL = 0.5


def _wait_until_ready(sid: str, budget: float = _READY_BUDGET) -> bool:
	"""Poll session info until rc=0. Returns True if ready within budget."""
	deadline = time.monotonic() + budget
	while time.monotonic() < deadline:
		r = ita("session", "info", "-s", sid, timeout=5)
		if r.returncode == 0:
			return True
		time.sleep(_POLL_INTERVAL)
	return False


@pytest.mark.contract
@pytest.mark.integration
def test_new_session_ready_within_budget(request):
	"""A freshly created session responds to `session info` within 10s."""
	name = (TEST_SESSION_PREFIX + "ready-check").replace(" ", "_")
	r = ita("new", "--name", name)
	assert r.returncode == 0, f"ita new failed: {r.stderr}"
	sid = _extract_sid(r.stdout)
	assert sid, "empty session id from ita new"

	try:
		ready = _wait_until_ready(sid)
		assert ready, (
			f"Session {sid[:8]}… not ready within {_READY_BUDGET}s after `ita new`"
		)
	finally:
		ita("close", "-s", sid, timeout=10)


@pytest.mark.contract
@pytest.mark.integration
def test_new_session_accepts_run_immediately(request):
	"""A freshly created session accepts `ita run echo hi` after stabilize."""
	name = (TEST_SESSION_PREFIX + "run-ready").replace(" ", "_")
	r = ita("new", "--name", name)
	assert r.returncode == 0, f"ita new failed: {r.stderr}"
	sid = _extract_sid(r.stdout)
	assert sid

	try:
		r_run = ita("run", "-s", sid, "echo __ready__", timeout=15)
		assert r_run.returncode == 0, (
			f"run immediately after new failed rc={r_run.returncode}\n"
			f"stdout: {r_run.stdout}\nstderr: {r_run.stderr}"
		)
		assert "__ready__" in r_run.stdout, (
			f"run output missing expected string:\n{r_run.stdout}"
		)
	finally:
		ita("close", "-s", sid, timeout=10)


@pytest.mark.contract
@pytest.mark.integration
def test_new_session_read_non_empty(request):
	"""A freshly created session has non-empty read output after shell init."""
	name = (TEST_SESSION_PREFIX + "read-ready").replace(" ", "_")
	r = ita("new", "--name", name)
	assert r.returncode == 0, f"ita new failed: {r.stderr}"
	sid = _extract_sid(r.stdout)
	assert sid

	try:
		_wait_until_ready(sid)
		r_read = ita("read", "-s", sid, timeout=10)
		assert r_read.returncode == 0, f"read failed: {r_read.stderr}"
		assert r_read.stdout.strip(), "read returned empty output on fresh session"
	finally:
		ita("close", "-s", sid, timeout=10)
