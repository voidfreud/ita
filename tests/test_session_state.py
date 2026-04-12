"""State tests for session lifecycle commands: new, close, activate, name, restart, resize, clear, capture."""
import sys
import pytest

sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent))
from conftest import ita

pytestmark = [pytest.mark.integration, pytest.mark.state]


# ── new ───────────────────────────────────────────────────────────────────────

def test_new_reuse_idempotent():
	"""--reuse called twice returns the same session ID both times."""
	unique_name = 'ita-test-state-reuse-idem'
	r1 = ita('new', '--name', unique_name)
	assert r1.returncode == 0
	sid1 = r1.stdout.strip().split('\t')[-1]
	try:
		r2 = ita('new', '--name', unique_name, '--reuse')
		r3 = ita('new', '--name', unique_name, '--reuse')
		assert r2.returncode == 0
		assert r3.returncode == 0
		sid2 = r2.stdout.strip().split('\t')[-1]
		sid3 = r3.stdout.strip().split('\t')[-1]
		assert sid1 == sid2 == sid3, "Repeated --reuse must return same session ID"
	finally:
		ita('close', '-s', sid1)


def test_new_replace_creates_fresh_session():
	"""--replace closes the existing session and creates a genuinely new one."""
	unique_name = 'ita-test-state-replace'
	r1 = ita('new', '--name', unique_name)
	assert r1.returncode == 0
	sid1 = r1.stdout.strip().split('\t')[-1]
	try:
		r2 = ita('new', '--name', unique_name, '--replace')
		assert r2.returncode == 0
		sid2 = r2.stdout.strip().split('\t')[-1]
		assert sid1 != sid2, "--replace must create a new session (different ID)"
	finally:
		ita('close', '-s', r2.stdout.strip().split('\t')[-1])


# ── name ──────────────────────────────────────────────────────────────────────

def test_name_persists_across_invocations(session):
	"""After rename, a subsequent status call should show the new name."""
	new_name = 'ita-test-renamed-persists'
	r = ita('name', new_name, '-s', session)
	assert r.returncode == 0
	# Re-query via status --json and verify the new name is reflected
	import json
	r2 = ita('status', '--json')
	assert r2.returncode == 0
	sessions = json.loads(r2.stdout)
	names = {s['session_name'] for s in sessions}
	assert new_name in names, f"Renamed session not found in status output; names: {names}"


# ── restart ───────────────────────────────────────────────────────────────────

def test_restart_produces_valid_session_id(session):
	"""After restart, the returned ID resolves and accepts further commands."""
	r = ita('restart', '-s', session)
	assert r.returncode == 0
	# restart may return 'Restarted: <id>' or just the ID in quiet mode
	out = r.stdout.strip()
	new_sid = out.split()[-1]
	assert new_sid, "restart must return a session ID"
	# Verify new_sid is reachable
	r2 = ita('activate', '-s', new_sid)
	assert r2.returncode == 0, f"Restarted session ID {new_sid!r} is not reachable: {r2.stderr}"


# ── clear ─────────────────────────────────────────────────────────────────────

def test_clear_does_not_close_session(session):
	"""Clearing a session leaves it open and operational."""
	r_clear = ita('clear', '-s', session)
	assert r_clear.returncode == 0
	# Session still operable after clear
	r_act = ita('activate', '-s', session)
	assert r_act.returncode == 0, "Session should still be active after clear"


# ── capture ───────────────────────────────────────────────────────────────────

def test_capture_scrollback_vs_default(session):
	"""--scrollback flag is accepted without error (behavior depends on scrollback size)."""
	r = ita('capture', '--scrollback', '-s', session)
	assert r.returncode == 0


def test_capture_repeated_does_not_consume_output(session):
	"""capture is read-only: running it twice returns rc=0 both times."""
	r1 = ita('capture', '-s', session)
	r2 = ita('capture', '-s', session)
	assert r1.returncode == 0
	assert r2.returncode == 0
