"""Invariant: stdout hygiene.

1. --json output parses as valid JSON.
2. Text mode (no --json) emits no prose banners on stdout — specifically no
   "Warning:" banners or the #248 `run -n` warning leaking to stdout.

Marks: @pytest.mark.contract + @pytest.mark.integration
"""
import json
import re
import pytest

from conftest import ita
from test_contracts import COMMANDS, _idfn, _skip_if_gui, _JSON_SCHEMA
import jsonschema

_JSON_CMDS = [c for c in COMMANDS if c["json"]]

# Patterns that must NOT appear on stdout in text mode.
# "Warning:" covers the #248 `run -n` stdout leak and similar banner bleed.
_STDOUT_BANNED = re.compile(r'^(Warning:|Error:|Traceback|usage:)', re.MULTILINE | re.IGNORECASE)


@pytest.mark.contract
@pytest.mark.integration
@pytest.mark.parametrize("cmd", _JSON_CMDS, ids=[_idfn(c) for c in _JSON_CMDS])
def test_json_output_parses(cmd, session):
	"""--json output is valid JSON conforming to the minimal envelope schema."""
	_skip_if_gui(cmd)
	parts = cmd["path"].split() + cmd["args"]
	if cmd["takes_s"]:
		parts += ["-s", session]
	parts += ["--json"]
	r = ita(*parts, timeout=30)
	assert r.returncode == 0, (
		f"{cmd['path']} --json failed rc={r.returncode}\n"
		f"stdout: {r.stdout}\nstderr: {r.stderr}"
	)
	try:
		data = json.loads(r.stdout)
	except json.JSONDecodeError as exc:
		pytest.fail(f"{cmd['path']} --json not valid JSON: {exc}\nraw: {r.stdout!r}")
	jsonschema.validate(data, _JSON_SCHEMA)


@pytest.mark.contract
@pytest.mark.integration
@pytest.mark.parametrize("cmd", COMMANDS, ids=[_idfn(c) for c in COMMANDS])
def test_text_mode_no_prose_banners_on_stdout(cmd, session):
	"""In text mode, stdout contains no Warning:/Error: banners (refs #248)."""
	_skip_if_gui(cmd)
	parts = cmd["path"].split() + cmd["args"]
	if cmd["takes_s"]:
		parts += ["-s", session]
	r = ita(*parts, timeout=30)
	# Only check stdout, not stderr — banners on stderr are acceptable.
	assert not _STDOUT_BANNED.search(r.stdout), (
		f"{cmd['path']}: banned prose banner found on stdout:\n{r.stdout[:600]}"
	)


@pytest.mark.contract
@pytest.mark.integration
def test_run_n_warning_not_on_stdout(session):
	"""ita run -n warning must not leak to stdout (issue #248)."""
	r = ita("run", "-s", session, "-n", "echo hi", timeout=30)
	assert "Warning" not in r.stdout, (
		f"run -n Warning leaked to stdout:\n{r.stdout}"
	)
