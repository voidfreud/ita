"""Central contract tests — iterates every command from the §8 inventory.

Marks: @pytest.mark.contract + @pytest.mark.integration on all tests.
GUI-modal commands (alert/ask/pick/save-dialog) are skipped with a reference to #235.
"""
import json
import re
import pytest
import jsonschema

from conftest import ita

# ---------------------------------------------------------------------------
# Command inventory  (source of truth for parametrization)
#
# Fields:
#   path        CLI invocation path, space-separated (e.g. "tab next")
#   json        True if --json is supported
#   writes      True if command is in the write-class (refuses protected session)
#   takes_s     True if command accepts a -s / --session argument
#   gui         True if command requires a modal GUI dialog (skip → #235)
#   args        Extra args required to make the invocation non-interactive / valid
#               (list of strings; may be empty)
# ---------------------------------------------------------------------------
COMMANDS = [
	# Orientation
	{"path": "status",        "json": True,  "writes": False, "takes_s": False, "gui": False, "args": []},
	{"path": "focus",         "json": True,  "writes": False, "takes_s": False, "gui": False, "args": []},
	{"path": "version",       "json": False, "writes": False, "takes_s": False, "gui": False, "args": []},
	{"path": "protect",       "json": False, "writes": False, "takes_s": True,  "gui": False, "args": []},
	{"path": "unprotect",     "json": False, "writes": False, "takes_s": True,  "gui": False, "args": []},
	{"path": "session info",  "json": True,  "writes": False, "takes_s": True,  "gui": False, "args": []},
	# Session
	{"path": "new",           "json": True,  "writes": False, "takes_s": False, "gui": False, "args": []},
	{"path": "close",         "json": False, "writes": True,  "takes_s": True,  "gui": False, "args": []},
	{"path": "activate",      "json": False, "writes": False, "takes_s": True,  "gui": False, "args": []},
	{"path": "name",          "json": False, "writes": False, "takes_s": True,  "gui": False, "args": ["new-name"]},
	{"path": "restart",       "json": False, "writes": True,  "takes_s": True,  "gui": False, "args": []},
	{"path": "resize",        "json": False, "writes": False, "takes_s": True,  "gui": False, "args": ["--rows", "24", "--cols", "80"]},
	{"path": "clear",         "json": False, "writes": True,  "takes_s": True,  "gui": False, "args": []},
	{"path": "capture",       "json": False, "writes": False, "takes_s": True,  "gui": False, "args": []},
	# Send / run
	{"path": "run",           "json": True,  "writes": True,  "takes_s": True,  "gui": False, "args": ["echo hi"]},
	{"path": "send",          "json": False, "writes": True,  "takes_s": True,  "gui": False, "args": ["x"]},
	{"path": "inject",        "json": False, "writes": True,  "takes_s": True,  "gui": False, "args": ["x"]},
	{"path": "key",           "json": False, "writes": True,  "takes_s": True,  "gui": False, "args": ["ctrl-c"]},
	# Output / query
	{"path": "read",          "json": False, "writes": False, "takes_s": True,  "gui": False, "args": []},
	{"path": "wait",          "json": True,  "writes": False, "takes_s": True,  "gui": False, "args": ["--timeout", "1"]},
	{"path": "selection",     "json": True,  "writes": False, "takes_s": True,  "gui": False, "args": []},
	{"path": "copy",          "json": False, "writes": False, "takes_s": True,  "gui": False, "args": []},
	{"path": "get-prompt",    "json": True,  "writes": False, "takes_s": True,  "gui": False, "args": []},
	{"path": "watch",         "json": True,  "writes": False, "takes_s": True,  "gui": False, "args": ["--timeout", "1"]},
	# Lock
	{"path": "lock",          "json": False, "writes": False, "takes_s": True,  "gui": False, "args": []},
	{"path": "unlock",        "json": False, "writes": False, "takes_s": True,  "gui": False, "args": []},
	# Tab
	{"path": "tab new",       "json": False, "writes": False, "takes_s": False, "gui": False, "args": []},
	{"path": "tab close",     "json": False, "writes": False, "takes_s": False, "gui": False, "args": []},
	{"path": "tab activate",  "json": False, "writes": False, "takes_s": False, "gui": False, "args": []},
	{"path": "tab next",      "json": False, "writes": False, "takes_s": False, "gui": False, "args": []},
	{"path": "tab prev",      "json": False, "writes": False, "takes_s": False, "gui": False, "args": []},
	{"path": "tab goto",      "json": True,  "writes": False, "takes_s": False, "gui": False, "args": ["1"]},
	{"path": "tab list",      "json": True,  "writes": False, "takes_s": False, "gui": False, "args": []},
	{"path": "tab info",      "json": True,  "writes": False, "takes_s": False, "gui": False, "args": []},
	{"path": "tab detach",    "json": False, "writes": False, "takes_s": False, "gui": False, "args": []},
	{"path": "tab move",      "json": False, "writes": False, "takes_s": False, "gui": False, "args": []},
	{"path": "tab profile",   "json": False, "writes": False, "takes_s": False, "gui": False, "args": []},
	{"path": "tab title",     "json": False, "writes": False, "takes_s": False, "gui": False, "args": ["my-title"]},
	# Window
	{"path": "window new",        "json": False, "writes": False, "takes_s": False, "gui": False, "args": []},
	{"path": "window close",      "json": False, "writes": False, "takes_s": False, "gui": False, "args": []},
	{"path": "window activate",   "json": False, "writes": False, "takes_s": False, "gui": False, "args": []},
	{"path": "window title",      "json": False, "writes": False, "takes_s": False, "gui": False, "args": ["my-title"]},
	{"path": "window fullscreen", "json": False, "writes": False, "takes_s": False, "gui": False, "args": []},
	{"path": "window frame",      "json": False, "writes": False, "takes_s": False, "gui": False, "args": []},
	{"path": "window list",       "json": True,  "writes": False, "takes_s": False, "gui": False, "args": []},
	# Pane
	{"path": "split", "json": False, "writes": False, "takes_s": True,  "gui": False, "args": []},
	{"path": "pane",  "json": False, "writes": False, "takes_s": False, "gui": False, "args": []},
	{"path": "move",  "json": False, "writes": False, "takes_s": False, "gui": False, "args": []},
	{"path": "swap",  "json": False, "writes": False, "takes_s": False, "gui": False, "args": []},
	# Config / var
	{"path": "var get",  "json": True, "writes": False, "takes_s": True,  "gui": False, "args": ["MY_VAR"]},
	{"path": "var set",  "json": True, "writes": False, "takes_s": True,  "gui": False, "args": ["MY_VAR", "val"]},
	{"path": "var list", "json": True, "writes": False, "takes_s": True,  "gui": False, "args": []},
	# Config / app
	{"path": "app version",  "json": False, "writes": False, "takes_s": False, "gui": False, "args": []},
	{"path": "app activate", "json": False, "writes": False, "takes_s": False, "gui": False, "args": []},
	{"path": "app hide",     "json": False, "writes": False, "takes_s": False, "gui": False, "args": []},
	{"path": "app quit",     "json": False, "writes": False, "takes_s": False, "gui": False, "args": []},
	{"path": "app theme",    "json": False, "writes": False, "takes_s": False, "gui": False, "args": []},
	# Config / pref
	{"path": "pref get",   "json": False, "writes": False, "takes_s": False, "gui": False, "args": ["PrefsCustomFolder"]},
	{"path": "pref set",   "json": True,  "writes": False, "takes_s": False, "gui": False, "args": ["PrefsCustomFolder", "/tmp"]},
	{"path": "pref list",  "json": True,  "writes": False, "takes_s": False, "gui": False, "args": []},
	{"path": "pref theme", "json": False, "writes": False, "takes_s": False, "gui": False, "args": []},
	{"path": "pref tmux",  "json": False, "writes": False, "takes_s": False, "gui": False, "args": []},
	# Broadcast
	{"path": "broadcast on",   "json": False, "writes": False, "takes_s": False, "gui": False, "args": []},
	{"path": "broadcast send", "json": False, "writes": False, "takes_s": False, "gui": False, "args": ["x"]},
	{"path": "broadcast off",  "json": False, "writes": False, "takes_s": False, "gui": False, "args": []},
	{"path": "broadcast add",  "json": False, "writes": False, "takes_s": False, "gui": False, "args": []},
	{"path": "broadcast set",  "json": False, "writes": False, "takes_s": False, "gui": False, "args": []},
	{"path": "broadcast list", "json": True,  "writes": False, "takes_s": False, "gui": False, "args": []},
	# Interactive (GUI-modal — skipped via #235)
	{"path": "alert",       "json": False, "writes": False, "takes_s": False, "gui": True,  "args": ["msg"]},
	{"path": "ask",         "json": False, "writes": False, "takes_s": False, "gui": True,  "args": ["q"]},
	{"path": "pick",        "json": False, "writes": False, "takes_s": False, "gui": True,  "args": ["a", "b"]},
	{"path": "save-dialog", "json": False, "writes": False, "takes_s": False, "gui": True,  "args": []},
	{"path": "menu list",   "json": True,  "writes": False, "takes_s": False, "gui": False, "args": []},
	{"path": "menu select", "json": False, "writes": False, "takes_s": False, "gui": True,  "args": ["File"]},
	{"path": "menu state",  "json": True,  "writes": False, "takes_s": False, "gui": False, "args": []},
	{"path": "repl",        "json": False, "writes": False, "takes_s": False, "gui": False, "args": []},
	# Management
	{"path": "profile list",  "json": True,  "writes": False, "takes_s": False, "gui": False, "args": []},
	{"path": "profile show",  "json": False, "writes": False, "takes_s": False, "gui": False, "args": ["Default"]},
	{"path": "profile get",   "json": False, "writes": False, "takes_s": False, "gui": False, "args": ["Default", "Name"]},
	{"path": "profile apply", "json": False, "writes": False, "takes_s": True,  "gui": False, "args": ["Default"]},
]

# Minimal JSON schema for this iteration — tightening is a follow-up.
_JSON_SCHEMA = {"type": ["object", "array"]}

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[mABCDEFGHJKSTflnprsu]')

_GUI_SKIP_REASON = (
	"Command requires a modal GUI dialog — skipped until non-interactive "
	"invocation path is available. See issue #235."
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _invoke(cmd: dict, extra: list[str] | None = None) -> tuple:
	"""Run a command entry, return (result, path_parts)."""
	parts = cmd["path"].split() + cmd["args"] + (extra or [])
	r = ita(*parts, timeout=30)
	return r, parts


def _skip_if_gui(cmd: dict) -> None:
	if cmd["gui"]:
		pytest.skip(_GUI_SKIP_REASON)


# ---------------------------------------------------------------------------
# Parametrize helpers — filter by field
# ---------------------------------------------------------------------------

def _cmds_with(field: str):
	return [c for c in COMMANDS if c.get(field)]


def _idfn(cmd):
	return cmd["path"].replace(" ", "_")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.contract
@pytest.mark.integration
@pytest.mark.parametrize("cmd", _cmds_with("json"), ids=[_idfn(c) for c in _cmds_with("json")])
def test_json_parity_when_supported(cmd, session):
	"""Commands with json=True emit valid JSON under --json."""
	_skip_if_gui(cmd)
	parts = cmd["path"].split() + cmd["args"]
	if cmd["takes_s"]:
		parts += ["-s", session]
	parts += ["--json"]
	r = ita(*parts, timeout=30)
	assert r.returncode == 0, (
		f"{cmd['path']} --json failed (rc={r.returncode})\nstdout: {r.stdout}\nstderr: {r.stderr}"
	)
	try:
		data = json.loads(r.stdout)
	except json.JSONDecodeError as exc:
		pytest.fail(f"{cmd['path']} --json output is not valid JSON: {exc}\nraw: {r.stdout!r}")
	jsonschema.validate(data, _JSON_SCHEMA)


@pytest.mark.contract
@pytest.mark.integration
@pytest.mark.parametrize("cmd", COMMANDS, ids=[_idfn(c) for c in COMMANDS])
def test_exit_code_contract(cmd, session):
	"""Success rc=0; error path rc!=0; no bare 'Error: 1' text."""
	_skip_if_gui(cmd)
	parts = cmd["path"].split() + cmd["args"]
	if cmd["takes_s"]:
		parts += ["-s", session]
	r = ita(*parts, timeout=30)

	# Success path: rc=0
	assert r.returncode == 0, (
		f"{cmd['path']} unexpected non-zero rc={r.returncode}\n"
		f"stdout: {r.stdout}\nstderr: {r.stderr}"
	)

	# Error path: invoke with a clearly invalid session/arg and expect rc != 0
	if cmd["takes_s"]:
		r_err = ita(*cmd["path"].split(), "-s", "nonexistent-session-000000", *cmd["args"], timeout=30)
		assert r_err.returncode != 0, (
			f"{cmd['path']} should fail on nonexistent session but returned rc=0"
		)
		# No bare "Error: 1" — must have a descriptive message
		combined = r_err.stdout + r_err.stderr
		assert "Error: 1" not in combined, (
			f"{cmd['path']} emitted bare 'Error: 1': {combined!r}"
		)


@pytest.mark.contract
@pytest.mark.integration
@pytest.mark.parametrize("cmd", COMMANDS, ids=[_idfn(c) for c in COMMANDS])
def test_output_hygiene(cmd, session):
	"""stdout/stderr contain no null bytes, BEL, or ANSI escapes in non-TTY mode."""
	_skip_if_gui(cmd)
	parts = cmd["path"].split() + cmd["args"]
	if cmd["takes_s"]:
		parts += ["-s", session]
	r = ita(*parts, timeout=30)
	combined = r.stdout + r.stderr

	assert "\x00" not in combined, f"{cmd['path']} output contains null byte"
	assert "\x07" not in combined, f"{cmd['path']} output contains BEL"
	assert not _ANSI_RE.search(combined), (
		f"{cmd['path']} output contains ANSI escape sequences in non-TTY mode: {combined!r}"
	)


@pytest.mark.contract
@pytest.mark.integration
@pytest.mark.parametrize("cmd", _cmds_with("takes_s"), ids=[_idfn(c) for c in _cmds_with("takes_s")])
def test_session_resolution_parity(cmd, session, shared_session):
	"""ita <cmd> -s <NAME> and -s <UUID-prefix> yield the same outcome."""
	_skip_if_gui(cmd)
	# Get both the name and a UUID prefix for the shared_session
	from pathlib import Path
	ITA = Path(__file__).parent.parent / 'src' / 'ita.py'

	r_info = ita('session', 'info', '-s', shared_session, '--json', timeout=10)
	if r_info.returncode != 0:
		pytest.skip("Could not fetch session info for parity test")
	try:
		info = json.loads(r_info.stdout)
	except (json.JSONDecodeError, ValueError):
		pytest.skip("session info did not return JSON")

	name = info.get("session_name") or info.get("name")
	uuid = info.get("session_id") or info.get("id")
	if not name or not uuid:
		pytest.skip("session info missing name or id fields")

	uuid_prefix = uuid[:8]
	base_parts = cmd["path"].split() + cmd["args"]

	r_name = ita(*base_parts, "-s", name, timeout=30)
	r_uuid = ita(*base_parts, "-s", uuid_prefix, timeout=30)

	# Both should succeed, or both should fail with same rc
	assert r_name.returncode == r_uuid.returncode, (
		f"{cmd['path']}: -s NAME rc={r_name.returncode} but -s UUID-prefix rc={r_uuid.returncode}\n"
		f"name stderr: {r_name.stderr}\nuuid stderr: {r_uuid.stderr}"
	)


@pytest.mark.contract
@pytest.mark.integration
@pytest.mark.parametrize(
	"cmd",
	[c for c in COMMANDS if c["writes"]],
	ids=[_idfn(c) for c in COMMANDS if c["writes"]],
)
@pytest.mark.parametrize("protected_session", [False], indirect=True)
def test_protection_refuses_writes(cmd, protected_session):
	"""Write-class commands refuse a protected session without --force."""
	_skip_if_gui(cmd)
	sid = protected_session["sid"]
	# Write without --force — must be refused
	parts = cmd["path"].split() + ["-s", sid] + cmd["args"]
	r = ita(*parts, timeout=30)
	assert r.returncode != 0, (
		f"{cmd['path']} should refuse protected session but returned rc=0"
	)
	combined = r.stdout + r.stderr
	assert combined.strip(), (
		f"{cmd['path']} refused protected session (rc!=0) but produced no output"
	)
