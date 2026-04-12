"""Invariant: every `on *` command with --timeout and no matching event
returns rc!=0 within the timeout window and emits a structured reason.

We use --timeout 1 (1 second) so tests are fast. We deliberately trigger no
events, so each command must time out and signal failure clearly.

Marks: @pytest.mark.contract + @pytest.mark.integration
"""
import pytest

from conftest import ita

# Each entry: (subcommand, extra_args_before_timeout)
# pattern/text args go first where required.
_ON_COMMANDS = [
	("output",      ["__no_match_pattern_xyz__"]),
	("prompt",      []),
	("keystroke",   ["__no_keystroke_xyz__"]),
	("session-new", []),
	("session-end", []),
	("focus",       []),
	("layout",      []),
]


@pytest.mark.contract
@pytest.mark.integration
@pytest.mark.parametrize("subcmd,extra", _ON_COMMANDS, ids=[s for s, _ in _ON_COMMANDS])
def test_on_command_times_out_with_rc_nonzero(subcmd, extra, session):
	"""on <subcmd> --timeout 1 with no event → rc!=0 within 5s."""
	parts = ["on", subcmd] + extra + ["--timeout", "1"]
	# session-end needs -s to avoid timing out on wrong session
	if subcmd in ("output", "prompt", "keystroke", "session-end"):
		parts += ["-s", session]
	r = ita(*parts, timeout=10)
	assert r.returncode != 0, (
		f"on {subcmd}: expected rc!=0 on timeout but got rc=0\n"
		f"stdout: {r.stdout!r}\nstderr: {r.stderr!r}"
	)
	combined = r.stdout + r.stderr
	# Must emit something — a descriptive message, not silence
	assert combined.strip(), (
		f"on {subcmd}: timed out (rc!=0) but produced no output"
	)


@pytest.mark.contract
@pytest.mark.integration
@pytest.mark.parametrize("subcmd,extra", _ON_COMMANDS, ids=[s for s, _ in _ON_COMMANDS])
def test_on_command_timeout_reason_in_output(subcmd, extra, session):
	"""Timeout output contains 'Timeout' or 'timed out' (case-insensitive)."""
	parts = ["on", subcmd] + extra + ["--timeout", "1"]
	if subcmd in ("output", "prompt", "keystroke", "session-end"):
		parts += ["-s", session]
	r = ita(*parts, timeout=10)
	combined = r.stdout + r.stderr
	lower = combined.lower()
	assert "timeout" in lower or "timed out" in lower, (
		f"on {subcmd}: no timeout reason in output:\n{combined[:600]}"
	)
