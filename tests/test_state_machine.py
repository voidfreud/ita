"""Tests for CONTRACT §7 state machine surfacing (cluster: state-machine).

Asserts the `state` field is present and valid on the three surfaces that
expose session metadata in --json mode:

  - `ita status --json`            (list, each entry)
  - `ita session info -s <id> --json` (single record)
  - `ita overview --json`          (windows[].tabs[].sessions[])

And that the two most-coupled derivations produce the right value:

  - `locked` when another PID holds the writelock
  - `dead`   when the session is gone

Issues addressed: #267, #257, #292.
"""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ita, ita_ok  # noqa: E402
from ita._state import VALID_STATES  # noqa: E402  (canonical enum)

pytestmark = [pytest.mark.integration, pytest.mark.contract]


WRITELOCK_FILE = Path.home() / ".ita_writelock"


def _find_session(sessions: list[dict], sid: str) -> dict | None:
	for s in sessions:
		if s.get('session_id') == sid:
			return s
	return None


# ── 1. status --json carries state on every entry ────────────────────────────

@pytest.mark.regression
def test_state_field_present_in_status_json(session):
	out = ita_ok('status', '--json')
	data = json.loads(out)
	assert isinstance(data, list) and data, "status --json returned empty"
	for entry in data:
		assert 'state' in entry, f"missing 'state' field: {entry!r}"
		assert entry['state'] in VALID_STATES, (
			f"invalid state {entry['state']!r} not in {VALID_STATES}"
		)


# ── 2. overview --json carries state on every session node ───────────────────

@pytest.mark.regression
def test_state_field_present_in_overview_json(session):
	out = ita_ok('overview', '--json', '--no-preview')
	data = json.loads(out)
	assert 'windows' in data
	saw_any = False
	for w in data['windows']:
		for t in w.get('tabs', []):
			for s in t.get('sessions', []):
				saw_any = True
				assert 'state' in s, f"missing 'state' in overview session: {s!r}"
				assert s['state'] in VALID_STATES, (
					f"invalid state {s['state']!r} not in {VALID_STATES}"
				)
	assert saw_any, "overview --json had no sessions"


# ── 3. session info --json carries state ─────────────────────────────────────

@pytest.mark.regression
def test_session_info_includes_state(session):
	out = ita_ok('session', 'info', '-s', session, '--json')
	data = json.loads(out)
	assert data.get('session_id') == session
	assert 'state' in data, f"session info missing 'state': {data!r}"
	assert data['state'] in VALID_STATES


# ── 4. locked derivation — a fake live writelock from another PID ────────────

@pytest.mark.regression
def test_state_locked_when_other_process_holds_writelock(session):
	"""Write a writelock entry with a live PID that isn't ours; expect
	derive_state to report `locked` via status --json."""
	# PID 1 is always alive and is not us — stable surrogate for "other live PID".
	other_pid = 1
	assert other_pid != os.getpid()
	original = WRITELOCK_FILE.read_text() if WRITELOCK_FILE.exists() else None
	try:
		existing = json.loads(original) if original else {}
		existing[session] = {
			'pid': other_pid,
			'cookie': 'test-cookie-state-machine',
			'ts': 0,
		}
		WRITELOCK_FILE.write_text(json.dumps(existing) + '\n')

		out = ita_ok('status', '--json')
		data = json.loads(out)
		entry = _find_session(data, session)
		assert entry is not None, f"session {session} not found in status"
		assert entry['state'] == 'locked', (
			f"expected locked, got {entry['state']!r}"
		)
	finally:
		# Restore exactly what was there before (or remove if nothing).
		if original is None:
			WRITELOCK_FILE.unlink(missing_ok=True)
		else:
			WRITELOCK_FILE.write_text(original)


# ── 5. dead derivation — closed session drops out of status ──────────────────

@pytest.mark.regression
def test_state_dead_when_session_closed():
	"""Create a session, capture its id, close it, then confirm it no
	longer appears (the only observable 'dead' surface: absence from the
	app tree). `session info` on a dead sid errors with not-found, which
	is the agent-observable equivalent of state=dead."""
	from helpers import TEST_SESSION_PREFIX  # type: ignore[import-not-found]

	r = ita('new', '--name', f'{TEST_SESSION_PREFIX}dead-probe')
	assert r.returncode == 0, f"new failed: {r.stderr}"
	sid = r.stdout.strip().split('\t')[-1]

	# Close — now the session is 'dead'.
	r = ita('close', '-s', sid)
	assert r.returncode == 0, f"close failed: {r.stderr}"

	# Observable consequence 1: not in status --json
	data = json.loads(ita_ok('status', '--json'))
	assert _find_session(data, sid) is None, (
		f"closed session still listed: {sid}"
	)

	# Observable consequence 2: session info returns not-found
	r = ita('session', 'info', '-s', sid, '--json')
	assert r.returncode != 0, "session info on dead sid should fail"
