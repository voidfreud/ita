"""Shared low-level helpers — imported by both conftest.py and the fixtures sub-package.

Kept separate to break the conftest ↔ fixtures circular import.
"""
import json
import subprocess
from pathlib import Path

# Canonical ita invocation for tests: run the installed package via
# `uv run python -m ita`. Single source of truth — any test that shells
# out to ita should use the `ita(...)` helper below, not a hardcoded path.
REPO_ROOT = Path(__file__).parent.parent
ITA_CMD = ['uv', 'run', '--project', str(REPO_ROOT), 'python', '-m', 'ita']
# Back-compat: some tests import `ITA` from helpers/conftest and build their
# own subprocess argv around it. Keep ITA as a list so callers can splat it.
ITA = ['python', '-m', 'ita']

TEST_SESSION_PREFIX = 'ita-test-'


def ita(*args, timeout=30):
	"""Run an ita subcommand. Returns CompletedProcess."""
	return subprocess.run(
		ITA_CMD + list(args),
		capture_output=True, text=True, timeout=timeout,
	)


def ita_ok(*args, **kwargs):
	"""Run ita and assert rc=0. Returns stdout stripped."""
	r = ita(*args, **kwargs)
	assert r.returncode == 0, (
		f"ita {args} failed (rc={r.returncode})\nstdout: {r.stdout}\nstderr: {r.stderr}"
	)
	return r.stdout.strip()


def _extract_sid(output: str) -> str:
	"""Extract session ID from 'ita new' output (name\\tUUID format)."""
	parts = output.strip().split('\t')
	return parts[-1] if len(parts) > 1 else parts[0]


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


# ── Window-leak helpers (#348) ─────────────────────────────────────────────
# iTerm2 spawns a default `-zsh` shell when an otherwise-empty window loses
# its session — so closing a test SESSION leaves an orphan WINDOW behind
# unless the test also closes the window. These helpers let fixtures track
# windows they create AND let the safety-net sweep detect orphans.

def _all_window_ids() -> set[str]:
	"""Snapshot of all current iTerm2 window IDs."""
	r = ita('window', 'list', '--json', timeout=10)
	if r.returncode != 0:
		return set()
	try:
		windows = json.loads(r.stdout)
	except (json.JSONDecodeError, ValueError):
		return set()
	return {w['window_id'] for w in windows}


def _close_window(wid: str) -> None:
	"""Best-effort close of a window. Requires --allow-window-close
	(CONTRACT §10). Errors swallowed — used in cleanup paths."""
	ita('window', 'close', wid, '--allow-window-close', '-y', timeout=10)


def _orphan_default_windows() -> list[str]:
	"""Window IDs that look like test orphans: single tab, single session,
	session name starts with 'Default' (iTerm2's default-shell name when it
	respawns into an emptied window). Heuristic — narrow on purpose."""
	r = ita('overview', '--json', timeout=10)
	if r.returncode != 0:
		return []
	try:
		data = json.loads(r.stdout)
	except (json.JSONDecodeError, ValueError):
		return []
	orphans = []
	for w in data.get('windows', []):
		tabs = w.get('tabs', [])
		if len(tabs) != 1:
			continue
		sessions = tabs[0].get('sessions', [])
		if len(sessions) != 1:
			continue
		name = sessions[0].get('session_name', '')
		if name.startswith('Default'):
			orphans.append(w['window_id'])
	return orphans


def _close_orphan_default_windows() -> int:
	"""Close every window matching the orphan heuristic. Returns count closed."""
	wids = _orphan_default_windows()
	for wid in wids:
		_close_window(wid)
	return len(wids)
