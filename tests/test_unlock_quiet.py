"""Fast-lane unit tests for `ita unlock --quiet` (issue #228).

CONTRACT §3: --quiet silences success-path stderr ("Unlocked: …",
"Not write-locked: …", "Cleared stale lock: …"). Errors/warnings still
emit regardless of --quiet.

These mock `run_iterm` so they exercise the click wiring + success_echo
routing without a live iTerm2 connection (integration coverage lives in
`test_lock.py::test_unlock_quiet_suppresses_output`).
"""
import sys
from pathlib import Path

from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from ita import _lock  # noqa: E402
from ita._core import cli  # noqa: E402


def _patch_resolve(monkeypatch, sid='SID-UNLOCK-228'):
	"""Make `run_iterm(...)` inside _lock return `sid` without iTerm2."""
	def _fake_run_iterm(coro):
		return sid
	monkeypatch.setattr(_lock, 'run_iterm', _fake_run_iterm)
	return sid


def test_unlock_quiet_not_locked_no_stderr(monkeypatch, tmp_path):
	# Isolate writelock file so we can guarantee "not locked" state.
	monkeypatch.setattr(_lock, 'WRITELOCK_FILE', tmp_path / '.writelock')
	sid = _patch_resolve(monkeypatch)
	r = CliRunner().invoke(
		cli, ['unlock', '-y', '-q', '-s', sid])
	assert r.exit_code == 0, r.output
	assert r.stderr == '', f"leaked: {r.stderr!r}"


def test_unlock_quiet_owned_lock_no_stderr(monkeypatch, tmp_path):
	monkeypatch.setattr(_lock, 'WRITELOCK_FILE', tmp_path / '.writelock')
	sid = _patch_resolve(monkeypatch)
	assert _lock.acquire_writelock(sid)
	r = CliRunner().invoke(
		cli, ['unlock', '-y', '-q', '-s', sid])
	assert r.exit_code == 0, r.output
	assert r.stderr == '', f"leaked on Unlocked path: {r.stderr!r}"


def test_unlock_quiet_stale_lock_no_stderr(monkeypatch, tmp_path):
	monkeypatch.setattr(_lock, 'WRITELOCK_FILE', tmp_path / '.writelock')
	sid = _patch_resolve(monkeypatch)
	# Write a stale entry (dead pid, foreign cookie) directly.
	import json
	(tmp_path / '.writelock').write_text(json.dumps({
		sid: {'pid': 1, 'cookie': 'foreign', 'at': '1970-01-01T00:00:00+00:00'}
	}) + '\n')
	# Force _pid_alive to report dead so the stale-reclaim branch fires.
	monkeypatch.setattr(_lock, '_pid_alive', lambda pid: False)
	r = CliRunner().invoke(
		cli, ['unlock', '-y', '-q', '-s', sid])
	assert r.exit_code == 0, r.output
	assert r.stderr == '', f"leaked on Cleared stale lock path: {r.stderr!r}"


def test_unlock_without_quiet_still_emits_stderr(monkeypatch, tmp_path):
	"""Sanity: without --quiet, success_echo must still write to stderr
	(otherwise the 'quiet' tests above would be vacuous)."""
	monkeypatch.setattr(_lock, 'WRITELOCK_FILE', tmp_path / '.writelock')
	sid = _patch_resolve(monkeypatch)
	assert _lock.acquire_writelock(sid)
	r = CliRunner().invoke(cli, ['unlock', '-y', '-s', sid])
	assert r.exit_code == 0, r.output
	assert 'Unlocked' in r.stderr, f"expected confirmation on stderr: {r.stderr!r}"
