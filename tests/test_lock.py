"""Tests for _lock.py: lock, unlock commands."""
import sys
import pytest

sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent))
from conftest import ita, ita_ok

pytestmark = pytest.mark.integration

# ── lock happy path ───────────────────────────────────────────────────────────

def test_lock_acquires(session):
	r = ita('lock', '-s', session)
	assert r.returncode == 0
	assert 'Write-locked' in r.stdout
	# Clean up
	ita('unlock', '-y', '-s', session)


def test_lock_list_shows_locked(session):
	ita_ok('lock', '-s', session)
	try:
		out = ita_ok('lock', '--list')
		assert session in out
	finally:
		ita('unlock', '-y', '-s', session)


def test_lock_list_empty_when_none():
	r = ita('lock', '--list')
	assert r.returncode == 0
	# Just ensure it doesn't crash; may say "No write-locks." or list others


# ── lock state ────────────────────────────────────────────────────────────────

@pytest.mark.state
def test_lock_persists_to_next_invocation(session):
	ita_ok('lock', '-s', session)
	try:
		# A second call to lock --list should still see it
		out = ita_ok('lock', '--list')
		assert session in out
	finally:
		ita('unlock', '-y', '-s', session)


@pytest.mark.state
def test_locked_session_refuses_write(session):
	ita_ok('lock', '-s', session)
	try:
		r = ita('run', '-s', session, 'echo hi')
		# Locked sessions should be refused by write commands
		assert r.returncode != 0
		assert 'write-lock' in r.stderr.lower() or 'locked' in r.stderr.lower()
	finally:
		ita('unlock', '-y', '-s', session)


@pytest.mark.state
def test_after_unlock_write_succeeds(session):
	ita_ok('lock', '-s', session)
	ita_ok('unlock', '-y', '-s', session)
	r = ita('run', '-s', session, 'echo hi')
	assert r.returncode == 0


# ── lock error ────────────────────────────────────────────────────────────────

@pytest.mark.error
def test_lock_nonexistent_session():
	r = ita('lock', '-s', '__no_such_session_xyz__')
	assert r.returncode != 0


# ── unlock happy path ─────────────────────────────────────────────────────────

def test_unlock_releases_lock(session):
	ita_ok('lock', '-s', session)
	r = ita('unlock', '-y', '-s', session)
	assert r.returncode == 0
	assert 'Unlocked' in r.stdout or 'Cleared' in r.stdout


def test_unlock_dry_run_does_not_release(session):
	ita_ok('lock', '-s', session)
	try:
		r = ita('unlock', '--dry-run', '-s', session)
		assert r.returncode == 0
		# Lock should still be present
		out = ita_ok('lock', '--list')
		assert session in out
	finally:
		ita('unlock', '-y', '-s', session)


# ── unlock error ──────────────────────────────────────────────────────────────

@pytest.mark.error
def test_unlock_not_locked_session(session):
	# Session exists but is not locked — should say so, not crash
	r = ita('unlock', '-y', '-s', session)
	assert r.returncode == 0
	assert 'Not write-locked' in r.stdout


@pytest.mark.error
def test_unlock_nonexistent_session():
	r = ita('unlock', '-y', '-s', '__no_such_session_xyz__')
	assert r.returncode != 0


# ── unlock state ──────────────────────────────────────────────────────────────

@pytest.mark.state
def test_unlock_removes_from_list(session):
	ita_ok('lock', '-s', session)
	ita_ok('unlock', '-y', '-s', session)
	r = ita('lock', '--list')
	# Either "No write-locks." or just doesn't contain this session
	assert r.returncode == 0
	assert session not in r.stdout


@pytest.mark.state
def test_lock_unlock_idempotent_on_relock(session):
	ita_ok('lock', '-s', session)
	ita_ok('unlock', '-y', '-s', session)
	# Can lock again after unlock
	r = ita('lock', '-s', session)
	assert r.returncode == 0
	ita('unlock', '-y', '-s', session)


# ── contract ──────────────────────────────────────────────────────────────────

@pytest.mark.contract
def test_unlock_quiet_suppresses_output(session):
	ita_ok('lock', '-s', session)
	r = ita('unlock', '-y', '-q', '-s', session)
	assert r.returncode == 0
	# CONTRACT §3: --quiet silences success-path stderr ("Unlocked: …").
	# Both streams must be empty on the happy path.
	assert r.stdout.strip() == ''
	assert r.stderr.strip() == '', f"--quiet leaked to stderr: {r.stderr!r}"
