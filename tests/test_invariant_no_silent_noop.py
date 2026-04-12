"""Invariant: missing target must not silently succeed.

For every command that takes a session: passing a nonexistent session must
yield rc!=0 OR (if --json) an envelope with ok=false.

Marks: @pytest.mark.contract + @pytest.mark.integration
"""
import json
import pytest

from conftest import ita
from test_contracts import COMMANDS, _idfn, _skip_if_gui

_BAD_SESSION = "nonexistent-session-000000"

_SESSION_CMDS = [c for c in COMMANDS if c["takes_s"]]


def _check_no_silent_noop(cmd, extra_args=None):
	parts = cmd["path"].split() + ["-s", _BAD_SESSION] + cmd["args"] + (extra_args or [])
	r = ita(*parts, timeout=30)
	if r.returncode != 0:
		return  # clearly non-zero — invariant satisfied

	# rc=0: only acceptable if --json and ok=false
	if extra_args and "--json" in extra_args:
		try:
			data = json.loads(r.stdout)
		except (json.JSONDecodeError, ValueError):
			pytest.fail(
				f"{cmd['path']} rc=0 on missing session with --json but output is not JSON:\n"
				f"{r.stdout!r}"
			)
		assert data.get("ok") is False, (
			f"{cmd['path']} rc=0 on missing session — expected ok=false in JSON envelope, "
			f"got: {r.stdout!r}"
		)
	else:
		pytest.fail(
			f"{cmd['path']} returned rc=0 on nonexistent session (silent noop)\n"
			f"stdout: {r.stdout!r}\nstderr: {r.stderr!r}"
		)


@pytest.mark.contract
@pytest.mark.integration
@pytest.mark.parametrize("cmd", _SESSION_CMDS, ids=[_idfn(c) for c in _SESSION_CMDS])
def test_missing_session_is_not_silent_noop(cmd, session):
	"""rc!=0 (or ok=false) when session target does not exist."""
	_skip_if_gui(cmd)
	_check_no_silent_noop(cmd)


@pytest.mark.contract
@pytest.mark.integration
@pytest.mark.parametrize(
	"cmd",
	[c for c in _SESSION_CMDS if c["json"]],
	ids=[_idfn(c) for c in _SESSION_CMDS if c["json"]],
)
def test_missing_session_json_envelope_not_ok(cmd, session):
	"""With --json, missing session emits ok=false not silent success."""
	_skip_if_gui(cmd)
	_check_no_silent_noop(cmd, extra_args=["--json"])
