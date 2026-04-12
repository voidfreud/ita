"""Cross-shell compatibility tests (bash / zsh / fish).

Uses the ``shell`` fixture which parametrizes over available shells.
Fish is skipped automatically when not installed.
All tests are marked ``integration`` + ``shell_matrix``.
"""
import json
import time
import pytest

from conftest import ita, ita_ok


pytestmark = [pytest.mark.integration, pytest.mark.shell_matrix]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wait_and_read(sid: str, delay: float = 0.5) -> str:
	"""Send a command, wait briefly, then read the session output."""
	time.sleep(delay)
	return ita_ok("read", "-s", sid)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_run_echo(shell):
	"""ita run 'echo hi' — stdout contains 'hi' in every shell."""
	sid = shell["sid"]
	r = ita("run", "-s", sid, "echo hi")
	assert r.returncode == 0, f"[{shell['shell']}] ita run failed: {r.stderr}"
	assert "hi" in r.stdout, f"[{shell['shell']}] 'hi' not found in: {r.stdout!r}"


def test_run_json_exit_code(shell):
	"""ita run --json exit_code matches the expected value for a zero-exit command."""
	sid = shell["sid"]
	r = ita("run", "-s", sid, "--json", "true")
	assert r.returncode == 0, f"[{shell['shell']}] ita run --json failed: {r.stderr}"
	data = json.loads(r.stdout)
	assert data.get("exit_code") == 0, (
		f"[{shell['shell']}] expected exit_code=0, got {data.get('exit_code')}"
	)


def test_send_read_shell_var(shell):
	"""ita send 'echo $SHELL' + ita read — output contains the right shell path."""
	sid = shell["sid"]
	shell_name = shell["shell"]
	ita_ok("send", "-s", sid, "echo $SHELL\n")
	output = _wait_and_read(sid)
	assert shell_name in output, (
		f"[{shell_name}] expected shell name in output, got: {output!r}"
	)


def test_prompt_detection_cwd(shell):
	"""get-prompt --json includes a non-empty 'cwd' key (prompt detection works)."""
	sid = shell["sid"]
	r = ita("get-prompt", "-s", sid, "--json")
	assert r.returncode == 0, f"[{shell['shell']}] get-prompt --json failed: {r.stderr}"
	data = json.loads(r.stdout)
	assert "cwd" in data and data["cwd"], (
		f"[{shell['shell']}] 'cwd' missing or empty in get-prompt output: {data}"
	)


def test_var_get_jobname(shell):
	"""ita var get jobName returns the shell binary name as the running job."""
	sid = shell["sid"]
	shell_name = shell["shell"]
	r = ita("var", "get", "-s", sid, "jobName")
	assert r.returncode == 0, f"[{shell_name}] ita var get jobName failed: {r.stderr}"
	assert shell_name in r.stdout, (
		f"[{shell_name}] expected shell name in jobName output, got: {r.stdout!r}"
	)


def test_error_command_nonzero_exit(shell):
	"""Running a nonexistent command exits with non-zero exit code in all shells."""
	sid = shell["sid"]
	r = ita("run", "-s", sid, "--json", "nonexistent-cmd-xyz")
	# ita run itself may succeed (rc=0) but the inner exit_code must be nonzero.
	# If ita run propagates the error rc, either form is acceptable.
	if r.returncode == 0:
		data = json.loads(r.stdout)
		assert data.get("exit_code") != 0, (
			f"[{shell['shell']}] expected nonzero exit_code for bad command, got: {data}"
		)
	else:
		# ita run itself returned nonzero — acceptable; the command failed as expected.
		pass
