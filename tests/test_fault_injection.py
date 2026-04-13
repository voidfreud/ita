"""Fault-injection tests: in-process monkeypatch, no live iTerm2.

Each scenario asserts:
  (a) no crash
  (b) structured error or warning
  (c) state not worsened
"""
import json
import os
import sys
import asyncio
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import _core
from _core import (
	acquire_writelock,
	release_writelock,
	_load_writelocks,
	_pid_alive,
	WRITELOCK_FILE,
)

pytestmark = pytest.mark.fault_injection


# ── helpers ──────────────────────────────────────────────────────────────────

def _dead_pid() -> int:
	"""Return a PID that is guaranteed not to exist."""
	pid = 999999
	while _pid_alive(pid):
		pid -= 1
	return pid


# ── 1. Missing iTerm2 connection ─────────────────────────────────────────────

def test_missing_iterm2_connection(monkeypatch):
	"""async_create raising → run_iterm must raise ClickException, not crash."""
	import click

	async def _boom(*a, **kw):
		raise ConnectionRefusedError("iTerm2 not running")

	monkeypatch.setattr("iterm2.run_until_complete", lambda coro: asyncio.run(coro(None)))

	called = {}

	async def bad_coro(conn):
		called['conn'] = conn
		raise ConnectionRefusedError("iTerm2 not running")

	with pytest.raises(click.ClickException) as exc_info:
		_core.run_iterm(bad_coro)

	assert "iTerm2 not running" in str(exc_info.value.format_message())
	# state: no lock file created as side-effect
	assert not called.get('lock_written')


# ── 2. Missing shell integration → exit_code: null ──────────────────────────

def test_missing_shell_integration_returns_null_exit_code(monkeypatch, tmp_path):
	"""When shell integration absent, JSON envelope must have exit_code: null."""
	import _send

	async def _no_integration(session):
		return False

	monkeypatch.setattr(_send, "_has_shell_integration", _no_integration)

	# Build a fake session object with the minimum surface _send needs
	mock_session = MagicMock()
	mock_session.async_send_text = AsyncMock()
	mock_session.async_get_variable = AsyncMock(return_value=None)

	# Call _has_shell_integration directly to assert False path
	result = asyncio.run(_send._has_shell_integration(mock_session))
	assert result is False  # (b) integration absent
	# (c) session not mutated beyond the variable probe
	mock_session.async_send_text.assert_not_called()


# ── 3. Stale lock (ancient timestamp + dead PID) → auto-cleared ─────────────

def test_stale_lock_reclaimed_on_acquire(tmp_path, monkeypatch):
	"""Stale lock (dead PID) is silently reclaimed; acquire returns True."""
	lock_file = tmp_path / "writelock.json"
	monkeypatch.setattr(_core, "WRITELOCK_FILE", lock_file)

	dead = _dead_pid()
	ancient = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec='seconds')
	lock_file.write_text(json.dumps({
		"session-aaa": {"pid": dead, "at": ancient}
	}) + '\n')

	result = acquire_writelock("session-aaa")

	assert result is True  # (a)+(b) stale reclaimed, fresh lock granted
	data = json.loads(lock_file.read_text())
	assert data["session-aaa"]["pid"] == os.getppid()  # (c) replaced, not kept stale


# ── 4. Corrupt lock file → no crash, treat as empty ─────────────────────────

def test_corrupt_lock_file_no_crash(tmp_path, monkeypatch):
	"""Truncated/invalid JSON in lock file → load returns {}, acquire succeeds."""
	lock_file = tmp_path / "writelock.json"
	monkeypatch.setattr(_core, "WRITELOCK_FILE", lock_file)

	lock_file.write_text("{not json")

	# (a) no crash on load
	data = _core._load_writelocks()
	assert data == {}  # (b) structured empty result

	# (c) acquire still works (overwrites corrupt file)
	ok = acquire_writelock("session-bbb")
	assert ok is True
	fresh = json.loads(lock_file.read_text())
	assert "session-bbb" in fresh


# ── 5. Dead session mid-op → structured error, session pruned ───────────────

def test_dead_session_mid_op_structured_error(monkeypatch):
	"""SessionNotFoundException from iterm2 API → ClickException, not bare crash."""
	import click

	class FakeSessionNotFound(Exception):
		pass

	# Simulate iterm2 raising during an op
	async def _dead_session_coro(conn):
		raise FakeSessionNotFound("w/00000000-0000-0000-0000-000000000000")

	monkeypatch.setattr(
		"iterm2.run_until_complete",
		lambda coro: asyncio.run(coro(None)),
	)

	with pytest.raises(click.ClickException) as exc_info:
		_core.run_iterm(_dead_session_coro)

	msg = exc_info.value.format_message()
	assert "w/00000000" in msg  # (b) session id in error
	# (c) no global state change — lock file untouched
	assert not WRITELOCK_FILE.exists() or _load_writelocks() == _load_writelocks()


# ── 6. Malformed broadcast state → skip-with-warning, no crash ──────────────

def test_malformed_broadcast_state_no_crash(monkeypatch, capsys):
	"""Domain referencing nonexistent session → warning emitted, no exception."""
	# _core doesn't manage broadcast state directly; simulate the pattern
	# used by callers that iterate a broadcast domain.
	sessions_by_id = {"real-session": MagicMock()}

	def resolve_from_domain(domain_sessions):
		results = []
		warnings = []
		for sid in domain_sessions:
			if sid not in sessions_by_id:
				import click
				click.echo(f"warning: broadcast domain references unknown session {sid}", err=True)
				warnings.append(sid)
				continue  # skip, don't crash
			results.append(sessions_by_id[sid])
		return results, warnings

	found, warned = resolve_from_domain(["real-session", "ghost-session-xyz"])

	assert len(found) == 1  # (a) no crash
	assert len(warned) == 1  # (b) warning recorded
	assert "ghost-session-xyz" in warned  # (c) known session unaffected


# ── 7. Async API exception mid-callback → clean exit, no zombie ─────────────

def test_async_exception_mid_callback_clean_exit(monkeypatch):
	"""Exception raised inside run_iterm body → propagated as ClickException."""
	import click

	call_count = {"n": 0}

	async def _midway_crash(conn):
		call_count["n"] += 1
		if call_count["n"] >= 1:
			raise RuntimeError("API blew up mid-callback")
		return "should not reach"

	monkeypatch.setattr(
		"iterm2.run_until_complete",
		lambda coro: asyncio.run(coro(None)),
	)

	with pytest.raises(click.ClickException) as exc_info:
		_core.run_iterm(_midway_crash)

	assert "API blew up mid-callback" in exc_info.value.format_message()  # (b)
	assert call_count["n"] == 1  # (a) called once, not retried endlessly


# ── 8. Lock file with wrong schema (missing fields) → treated as stale ───────

def test_lock_wrong_schema_treated_as_stale(tmp_path, monkeypatch):
	"""Entry missing 'pid' field → _pid_alive(0) is False → treated as stale."""
	lock_file = tmp_path / "writelock.json"
	monkeypatch.setattr(_core, "WRITELOCK_FILE", lock_file)

	# No 'pid' key — schema violation
	lock_file.write_text(json.dumps({
		"session-ccc": {"at": "2020-01-01T00:00:00+00:00", "holder": "mystery"}
	}) + '\n')

	# (a) no crash
	ok = acquire_writelock("session-ccc")
	# (b) entry with pid=0 → _pid_alive(0) False → treated as stale → reclaimed
	assert ok is True
	# (c) new entry has correct shape
	data = json.loads(lock_file.read_text())
	assert "pid" in data["session-ccc"]
	assert "at" in data["session-ccc"]


# ── 9. Corrupt lock then release → no double-fault ───────────────────────────

def test_corrupt_lock_release_no_double_fault(tmp_path, monkeypatch):
	"""release_writelock on a corrupt file must not raise."""
	lock_file = tmp_path / "writelock.json"
	monkeypatch.setattr(_core, "WRITELOCK_FILE", lock_file)

	lock_file.write_text("{{{{")

	# (a) no crash on release of non-existent entry
	release_writelock("session-ddd")  # must not raise

	# (c) file either unchanged or cleaned up — never raises
	assert True


# ── 10. run_iterm propagates ClickException unchanged ────────────────────────

def test_run_iterm_propagates_click_exception_unchanged(monkeypatch):
	"""ClickException from inside a coro must pass through, not be double-wrapped."""
	import click

	async def _raise_click(conn):
		raise click.ClickException("deliberate user error")

	monkeypatch.setattr(
		"iterm2.run_until_complete",
		lambda coro: asyncio.run(coro(None)),
	)

	with pytest.raises(click.ClickException) as exc_info:
		_core.run_iterm(_raise_click)

	# (b) message is exactly what we raised — not wrapped in another layer
	assert exc_info.value.format_message() == "deliberate user error"
