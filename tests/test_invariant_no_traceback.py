"""Invariant: no command ever emits a Python traceback.

Bad input × every command — stdout+stderr must not contain "Traceback".

Marks: @pytest.mark.contract + @pytest.mark.integration
"""
import pytest

from conftest import ita
from test_contracts import COMMANDS, _idfn, _skip_if_gui

_BAD_SESSION = "nonexistent-session-000000"


@pytest.mark.contract
@pytest.mark.integration
@pytest.mark.parametrize("cmd", COMMANDS, ids=[_idfn(c) for c in COMMANDS])
def test_no_traceback_bad_session(cmd, session):
	"""Passing a bogus session (or no session) never produces a traceback."""
	_skip_if_gui(cmd)
	# Use bad session when the command accepts one; otherwise use wrong/extra args.
	if cmd["takes_s"]:
		parts = cmd["path"].split() + ["-s", _BAD_SESSION] + cmd["args"]
	else:
		# Inject a clearly bad positional arg to force error path
		parts = cmd["path"].split() + ["__bad_arg_999__"] + cmd["args"]
	r = ita(*parts, timeout=30)
	combined = r.stdout + r.stderr
	assert "Traceback" not in combined, (
		f"{cmd['path']}: traceback found in output\n{combined[:800]}"
	)


@pytest.mark.contract
@pytest.mark.integration
@pytest.mark.parametrize("cmd", COMMANDS, ids=[_idfn(c) for c in COMMANDS])
def test_no_traceback_missing_required_args(cmd, session):
	"""Invoking with missing required args never produces a traceback."""
	_skip_if_gui(cmd)
	# Run with no args at all (ignores required positionals / session)
	parts = cmd["path"].split()
	r = ita(*parts, timeout=30)
	combined = r.stdout + r.stderr
	assert "Traceback" not in combined, (
		f"{cmd['path']} (no args): traceback found in output\n{combined[:800]}"
	)
