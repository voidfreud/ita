"""Unit tests for cross-cutting flags (#139 --quiet, #142 --json, #143 --dry-run/--confirm/-y).

Tests stub run_iterm so no live iTerm2 connection is required.
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

SRC = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(SRC))

import _core  # noqa: E402

cli = _core.cli


def _stub(return_value=None):
	"""Make run_iterm synchronous and return a chosen value."""
	def _fake(coro):
		return return_value
	return _fake


# ── #143 --dry-run / --confirm / -y ─────────────────────────────────────────

@pytest.mark.parametrize("cmd", [
	["broadcast", "off", "--dry-run"],
	["broadcast", "on", "--dry-run"],
	["var", "set", "foo", "bar", "--dry-run"],
	["pref", "set", "FOO", "1", "--dry-run"],
])
def test_dry_run_does_not_mutate(cmd):
	runner = CliRunner()
	called = {'n': 0}
	def _spy(coro):
		called['n'] += 1
	with patch.object(_core, 'run_iterm', _spy):
		# Also patch the run_iterm re-exports in modules.
		import _config
		import _layout
		with patch.object(_config, 'run_iterm', _spy), patch.object(_layout, 'run_iterm', _spy):
			result = runner.invoke(cli, cmd)
	assert result.exit_code == 0, result.output
	assert called['n'] == 0, "run_iterm must not be called for --dry-run"
	assert 'Would' in result.output


def test_confirm_non_tty_errors_without_yes():
	runner = CliRunner()
	import _config
	with patch.object(_core, 'run_iterm', _stub()), \
			patch.object(_config, 'run_iterm', _stub()):
		result = runner.invoke(cli, ["broadcast", "off", "--confirm"], input="")
	assert result.exit_code != 0
	assert 'TTY' in result.output or 'yes' in result.output.lower()


def test_confirm_yes_proceeds():
	runner = CliRunner()
	import _config
	with patch.object(_core, 'run_iterm', _stub()), \
			patch.object(_config, 'run_iterm', _stub()):
		result = runner.invoke(cli, ["broadcast", "off", "--confirm", "-y"])
	assert result.exit_code == 0, result.output


# ── #139 --quiet ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("cmd", [
	["broadcast", "off", "-q"],
	["var", "set", "foo", "bar", "-q"],
])
def test_quiet_suppresses_stderr_success(cmd):
	runner = CliRunner()
	import _config
	with patch.object(_core, 'run_iterm', _stub()), \
			patch.object(_config, 'run_iterm', _stub()):
		result = runner.invoke(cli, cmd)
	assert result.exit_code == 0, result.output
	# --quiet swallows the Set:/Broadcast disabled. confirmation.
	assert 'Set:' not in result.output
	assert 'disabled' not in result.output.lower() or 'Would' in result.output


# ── #142 --json parity ─────────────────────────────────────────────────────

def test_var_get_json():
	runner = CliRunner()
	import _config
	with patch.object(_core, 'run_iterm', _stub('hello')), \
			patch.object(_config, 'run_iterm', _stub('hello')):
		result = runner.invoke(cli, ["var", "get", "foo", "--json"])
	assert result.exit_code == 0, result.output
	data = json.loads(result.output)
	assert data == {'name': 'user.foo', 'value': 'hello', 'scope': 'session'}


def test_pref_list_json():
	runner = CliRunner()
	import _config
	with patch.object(_core, 'run_iterm', _stub(['A', 'B'])), \
			patch.object(_config, 'run_iterm', _stub(['A', 'B'])):
		result = runner.invoke(cli, ["pref", "list", "--json"])
	assert result.exit_code == 0, result.output
	assert json.loads(result.output) == ['A', 'B']


def test_var_set_json_emits_ok():
	runner = CliRunner()
	import _config
	with patch.object(_core, 'run_iterm', _stub()), \
			patch.object(_config, 'run_iterm', _stub()):
		result = runner.invoke(cli, ["var", "set", "foo", "bar", "--json", "-y"])
	assert result.exit_code == 0, result.output
	data = json.loads(result.output)
	assert data['ok'] is True
	assert data['name'] == 'user.foo'


# ── confirm_or_skip helper direct unit ─────────────────────────────────────

def test_confirm_or_skip_dry_run_returns_false(capsys):
	assert _core.confirm_or_skip("do stuff", dry_run=True, yes=False) is False
	out = capsys.readouterr().out
	assert 'Would' in out and 'do stuff' in out


def test_confirm_or_skip_yes_returns_true():
	assert _core.confirm_or_skip("do stuff", dry_run=False, yes=True) is True
