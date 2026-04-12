"""Tests for tmux -CC integration commands.

All tests require a live iTerm2 and are marked `integration`.
Tests that additionally require an active tmux server are marked with an
inline skip guard so they are skipped gracefully when tmux is not available.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ita, ita_ok

pytestmark = pytest.mark.integration


def _tmux_available() -> bool:
	return shutil.which('tmux') is not None


def _active_tmux_connection() -> bool:
	"""Return True if ita reports at least one tmux -CC connection."""
	r = ita('tmux', 'connections')
	return r.returncode == 0 and 'No active' not in r.stdout


# ── tmux connections ──────────────────────────────────────────────────────────

def test_tmux_connections_no_server():
	"""Happy: when no tmux connection exists, rc=0 with 'No active' message."""
	r = ita('tmux', 'connections')
	assert r.returncode == 0
	# Either empty list line or the sentinel message
	assert 'No active' in r.stdout or r.stdout.strip() == ''


@pytest.mark.contract
def test_tmux_connections_json_empty():
	"""Contract: --json with no connections emits [] and rc=0."""
	r = ita('tmux', 'connections', '--json')
	assert r.returncode == 0
	data = json.loads(r.stdout.strip())
	assert isinstance(data, list)


@pytest.mark.contract
def test_tmux_connections_json_schema():
	"""Contract: --json with active connections emits list of {id: ...} objects."""
	if not _active_tmux_connection():
		pytest.skip('No active tmux connection available')
	r = ita('tmux', 'connections', '--json')
	assert r.returncode == 0
	data = json.loads(r.stdout.strip())
	assert isinstance(data, list)
	for item in data:
		assert 'id' in item


# ── tmux windows ──────────────────────────────────────────────────────────────

def test_tmux_windows_no_connection():
	"""Happy: no tmux connection → windows returns empty list, rc=0."""
	if _active_tmux_connection():
		pytest.skip('tmux connection active; skipping no-connection path')
	r = ita('tmux', 'windows')
	assert r.returncode == 0


@pytest.mark.contract
def test_tmux_windows_json_empty():
	"""Contract: --json with no windows emits [] and rc=0."""
	r = ita('tmux', 'windows', '--json')
	assert r.returncode == 0
	data = json.loads(r.stdout.strip())
	assert isinstance(data, list)


@pytest.mark.contract
def test_tmux_windows_json_schema():
	"""Contract: --json with active windows emits {tmux_window_id, tab_id, connection_id}."""
	if not _active_tmux_connection():
		pytest.skip('No active tmux connection available')
	r = ita('tmux', 'windows', '--json')
	assert r.returncode == 0
	data = json.loads(r.stdout.strip())
	assert isinstance(data, list)
	for w in data:
		assert 'tmux_window_id' in w
		assert 'tab_id' in w
		assert 'connection_id' in w


# ── tmux cmd ──────────────────────────────────────────────────────────────────

@pytest.mark.error
def test_tmux_cmd_no_connection():
	"""Error: tmux cmd without an active connection → rc=1, helpful message."""
	if _active_tmux_connection():
		pytest.skip('tmux connection active; skipping no-connection path')
	r = ita('tmux', 'cmd', 'list-sessions')
	assert r.returncode == 1
	assert 'tmux start' in r.stderr or 'No active' in r.stderr


@pytest.mark.error
def test_tmux_cmd_missing_arg():
	"""Error: tmux cmd with no COMMAND argument → rc=2 (missing arg)."""
	r = ita('tmux', 'cmd')
	assert r.returncode == 2


def test_tmux_cmd_happy():
	"""Happy: sends a command to tmux and gets output."""
	if not _tmux_available():
		pytest.skip('tmux binary not available')
	if not _active_tmux_connection():
		pytest.skip('No active tmux connection available')
	r = ita('tmux', 'cmd', 'list-sessions')
	assert r.returncode == 0


# ── tmux start ────────────────────────────────────────────────────────────────

@pytest.mark.state
def test_tmux_start_reuse_warning(session):
	"""State: tmux start when a connection already exists warns on stderr and reuses."""
	if not _active_tmux_connection():
		pytest.skip('No active tmux connection available')
	r = ita('tmux', 'start', '-s', session)
	assert r.returncode == 0
	assert 'Reusing' in r.stderr or 'existing' in r.stderr.lower()


def test_tmux_start_needs_tmux(session):
	"""Edge: tmux start when tmux binary absent → rc=1 with helpful message."""
	if _tmux_available():
		pytest.skip('tmux is installed; skipping absent-binary path')
	r = ita('tmux', 'start', '-s', session)
	assert r.returncode == 1
	assert 'tmux' in r.stderr.lower()


# ── tmux stop ─────────────────────────────────────────────────────────────────

@pytest.mark.edge
def test_tmux_stop_no_connection():
	"""Edge: tmux stop with no connection prints warning on stderr, rc=0."""
	if _active_tmux_connection():
		pytest.skip('tmux connection active; skipping no-connection path')
	r = ita('tmux', 'stop')
	assert r.returncode == 0
	assert 'No active' in r.stderr


# ── tmux visible ──────────────────────────────────────────────────────────────

@pytest.mark.error
def test_tmux_visible_no_connection():
	"""Error: tmux visible without a connection → rc=1."""
	if _active_tmux_connection():
		pytest.skip('tmux connection active; skipping no-connection path')
	r = ita('tmux', 'visible', '@1', 'on')
	assert r.returncode == 1
	assert 'tmux start' in r.stderr or 'No active' in r.stderr


@pytest.mark.error
def test_tmux_visible_invalid_state():
	"""Error: tmux visible with invalid state value → rc=2 (click.Choice)."""
	r = ita('tmux', 'visible', '@1', 'maybe')
	assert r.returncode == 2


# ── tmux detach ───────────────────────────────────────────────────────────────

@pytest.mark.error
def test_tmux_detach_no_connection():
	"""Error: tmux detach without connection → rc=1."""
	if _active_tmux_connection():
		pytest.skip('tmux connection active; skipping no-connection path')
	r = ita('tmux', 'detach')
	assert r.returncode == 1
	assert 'No active' in r.stderr


# ── tmux kill-session ─────────────────────────────────────────────────────────

@pytest.mark.error
def test_tmux_kill_session_no_connection():
	"""Error: tmux kill-session without connection → rc=1."""
	if _active_tmux_connection():
		pytest.skip('tmux connection active; skipping no-connection path')
	r = ita('tmux', 'kill-session', 'mysession')
	assert r.returncode == 1
	assert 'No active' in r.stderr


def test_tmux_kill_session_no_arg_no_connection():
	"""Error: tmux kill-session (no session arg) without connection → rc=1."""
	if _active_tmux_connection():
		pytest.skip('tmux connection active; skipping no-connection path')
	r = ita('tmux', 'kill-session')
	assert r.returncode == 1


# ── output hygiene (cross-cutting) ───────────────────────────────────────────

@pytest.mark.contract
def test_tmux_connections_no_ansi_leak():
	"""Contract: non-TTY stdout contains no ANSI escape sequences."""
	r = ita('tmux', 'connections')
	assert r.returncode == 0
	assert '\x1b[' not in r.stdout


@pytest.mark.contract
def test_tmux_windows_no_ansi_leak():
	"""Contract: non-TTY stdout contains no ANSI escape sequences."""
	r = ita('tmux', 'windows')
	assert r.returncode == 0
	assert '\x1b[' not in r.stdout
