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
