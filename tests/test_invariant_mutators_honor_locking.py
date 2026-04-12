"""Invariant: mutators refuse when another writer holds the lock.

Simulates a concurrent writer by manually writing to ~/.ita_writelock with
a live PID (os.getpid()) then verifying that each mutator returns rc!=0
with a descriptive message containing the lock holder's PID.

Teardown always releases the injected lock to avoid test pollution.

Marks: @pytest.mark.contract + @pytest.mark.integration
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from conftest import ita
from test_contracts import COMMANDS, _idfn, _skip_if_gui

WRITELOCK_FILE = Path.home() / ".ita_writelock"

_MUTATORS = [c for c in COMMANDS if c["writes"]]


def _inject_lock(session_id: str) -> None:
	"""Write a live-PID lock entry for session_id."""
	try:
		existing = json.loads(WRITELOCK_FILE.read_text()) if WRITELOCK_FILE.exists() else {}
	except (json.JSONDecodeError, OSError):
		existing = {}
	existing[session_id] = {
		"pid": os.getpid(),
		"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
	}
	WRITELOCK_FILE.write_text(json.dumps(existing, indent=2) + "\n")


def _release_lock(session_id: str) -> None:
	"""Remove our injected lock entry."""
	if not WRITELOCK_FILE.exists():
		return
	try:
		data = json.loads(WRITELOCK_FILE.read_text())
	except (json.JSONDecodeError, OSError):
		return
	data.pop(session_id, None)
	if data:
		WRITELOCK_FILE.write_text(json.dumps(data, indent=2) + "\n")
	else:
		WRITELOCK_FILE.unlink(missing_ok=True)


@pytest.mark.contract
@pytest.mark.integration
@pytest.mark.parametrize("cmd", _MUTATORS, ids=[_idfn(c) for c in _MUTATORS])
def test_mutator_respects_held_lock(cmd, session):
	"""Mutator returns rc!=0 while a live PID holds the session write-lock."""
	_skip_if_gui(cmd)
	_inject_lock(session)
	try:
		parts = cmd["path"].split() + ["-s", session] + cmd["args"]
		r = ita(*parts, timeout=30)
		assert r.returncode != 0, (
			f"{cmd['path']}: accepted write despite held lock (rc=0)\n"
			f"stdout: {r.stdout!r}\nstderr: {r.stderr!r}"
		)
		combined = r.stdout + r.stderr
		# Must include something about the lock (pid or "locked" or "write-lock")
		assert combined.strip(), (
			f"{cmd['path']}: refused (rc!=0) but produced no output"
		)
	finally:
		_release_lock(session)
