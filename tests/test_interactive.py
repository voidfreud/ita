"""Tests for _interactive.py: alert, ask, pick, save-dialog, menu *, repl."""
import json
import sys
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ita, ita_ok

pytestmark = pytest.mark.integration

# ── Candidate bug note (non-blocking) ───────────────────────────────────────
# alert / ask / pick / save-dialog have no --dry-run or non-blocking mode.
# Invoking them live would open a modal dialog and block the test runner.
# Tests below are therefore limited to --help / argument-parsing paths.
# Marked xfail(known_broken) where we expect a real assertion that can't yet
# execute. Filed as candidate feature gap: "add --dry-run to modal commands".


# ── Helpers ──────────────────────────────────────────────────────────────────

def _help(cmd, *sub):
	"""Return --help output for a command, assert rc=0."""
	r = ita(cmd, *sub, '--help')
	assert r.returncode == 0, r.stderr
	return r.stdout


# ══════════════════════════════════════════════════════════════════════════════
# alert
# ══════════════════════════════════════════════════════════════════════════════

class TestAlert:
	def test_help_registered(self):
		"""Happy: command is registered and --help exits 0."""
		out = _help('alert')
		assert 'TITLE' in out
		assert 'MESSAGE' in out

	@pytest.mark.edge
	def test_help_shows_button_option(self):
		"""Edge: --button option is advertised."""
		out = _help('alert')
		assert '--button' in out

	@pytest.mark.error
	def test_missing_args_nonzero(self):
		"""Error: invoking without required args exits non-zero."""
		r = ita('alert')
		assert r.returncode != 0

	@pytest.mark.error
	def test_missing_message_nonzero(self):
		"""Error: title without message exits non-zero."""
		r = ita('alert', 'MyTitle')
		assert r.returncode != 0

	@pytest.mark.contract
	def test_no_null_bytes_in_help(self):
		"""Contract: --help output has no null bytes."""
		out = _help('alert')
		assert '\x00' not in out

	@pytest.mark.known_broken
	@pytest.mark.xfail(reason='no --dry-run mode; modal dialog would block runner')
	def test_dry_run_not_implemented(self):
		"""Known gap: alert has no testable dry-run path."""
		r = ita('alert', 'Title', 'Body', '--dry-run')
		assert r.returncode == 0


# ══════════════════════════════════════════════════════════════════════════════
# ask
# ══════════════════════════════════════════════════════════════════════════════

class TestAsk:
	def test_help_registered(self):
		out = _help('ask')
		assert 'TITLE' in out
		assert 'MESSAGE' in out

	@pytest.mark.edge
	def test_help_shows_default_option(self):
		out = _help('ask')
		assert '--default' in out

	@pytest.mark.error
	def test_missing_args_nonzero(self):
		r = ita('ask')
		assert r.returncode != 0

	@pytest.mark.contract
	def test_no_null_bytes_in_help(self):
		assert '\x00' not in _help('ask')

	@pytest.mark.known_broken
	@pytest.mark.xfail(reason='no --dry-run mode; modal dialog would block runner')
	def test_dry_run_not_implemented(self):
		r = ita('ask', 'Title', 'Body', '--dry-run')
		assert r.returncode == 0


# ══════════════════════════════════════════════════════════════════════════════
# pick
# ══════════════════════════════════════════════════════════════════════════════

class TestPick:
	def test_help_registered(self):
		out = _help('pick')
		assert 'Usage:' in out

	@pytest.mark.edge
	def test_help_shows_ext_and_multi(self):
		out = _help('pick')
		assert '--ext' in out
		assert '--multi' in out

	@pytest.mark.contract
	def test_no_null_bytes_in_help(self):
		assert '\x00' not in _help('pick')

	@pytest.mark.known_broken
	@pytest.mark.xfail(reason='no --dry-run mode; modal dialog would block runner')
	def test_dry_run_not_implemented(self):
		r = ita('pick', '--dry-run')
		assert r.returncode == 0


# ══════════════════════════════════════════════════════════════════════════════
# save-dialog
# ══════════════════════════════════════════════════════════════════════════════

class TestSaveDialog:
	def test_help_registered(self):
		out = _help('save-dialog')
		assert 'Usage:' in out

	@pytest.mark.edge
	def test_help_shows_name_option(self):
		out = _help('save-dialog')
		assert '--name' in out

	@pytest.mark.contract
	def test_no_null_bytes_in_help(self):
		assert '\x00' not in _help('save-dialog')

	@pytest.mark.known_broken
	@pytest.mark.xfail(reason='no --dry-run mode; modal dialog would block runner')
	def test_dry_run_not_implemented(self):
		r = ita('save-dialog', '--dry-run')
		assert r.returncode == 0


# ══════════════════════════════════════════════════════════════════════════════
# menu list
# ══════════════════════════════════════════════════════════════════════════════

class TestMenuList:
	@pytest.mark.integration
	def test_happy_returns_items(self):
		"""Happy: menu list returns non-empty output."""
		r = ita_ok('menu', 'list')
		assert r.strip()

	@pytest.mark.integration
	def test_json_valid_array(self):
		"""Happy: --json emits a valid JSON array with title/enabled keys."""
		r = ita('menu', 'list', '--json')
		assert r.returncode == 0
		data = json.loads(r.stdout)
		assert isinstance(data, list)
		assert len(data) > 0
		first = data[0]
		assert 'title' in first
		assert 'enabled' in first

	@pytest.mark.integration
	@pytest.mark.contract
	def test_json_schema(self):
		"""Contract: every item in --json output matches expected schema."""
		import jsonschema
		schema = {
			'type': 'array',
			'items': {
				'type': 'object',
				'required': ['title', 'enabled'],
				'properties': {
					'title': {'type': 'string'},
					'enabled': {'type': 'boolean'},
				},
				'additionalProperties': True,
			},
		}
		r = ita('menu', 'list', '--json')
		assert r.returncode == 0
		jsonschema.validate(json.loads(r.stdout), schema)

	@pytest.mark.integration
	@pytest.mark.edge
	def test_group_filter(self):
		"""Edge: --group filters to only that group's items."""
		r = ita('menu', 'list', '--group', 'Shell')
		assert r.returncode == 0
		for line in r.stdout.strip().splitlines():
			assert line.startswith('Shell/')

	@pytest.mark.integration
	@pytest.mark.edge
	def test_group_filter_json(self):
		"""Edge: --group with --json limits output to filtered group."""
		r = ita('menu', 'list', '--group', 'Edit', '--json')
		assert r.returncode == 0
		data = json.loads(r.stdout)
		for item in data:
			assert item['title'].startswith('Edit/')

	@pytest.mark.contract
	def test_no_null_bytes_in_help(self):
		assert '\x00' not in _help('menu', 'list')


# ══════════════════════════════════════════════════════════════════════════════
# menu select
# ══════════════════════════════════════════════════════════════════════════════

class TestMenuSelect:
	def test_help_registered(self):
		out = _help('menu', 'select')
		assert 'ITEM' in out

	@pytest.mark.error
	def test_missing_item_nonzero(self):
		"""Error: invoking select without ITEM exits non-zero."""
		r = ita('menu', 'select')
		assert r.returncode != 0

	@pytest.mark.integration
	@pytest.mark.error
	def test_unknown_item_error(self):
		"""Error: totally unknown item identifier produces ClickException."""
		r = ita('menu', 'select', 'TOTALLY_NONEXISTENT_ITEM_XYZ')
		assert r.returncode != 0

	@pytest.mark.known_broken
	@pytest.mark.xfail(reason='live menu invocation may cause side-effects / require display')
	def test_live_select_known_item(self):
		"""Known gap: happy-path for menu select requires live window focus."""
		r = ita('menu', 'select', 'Shell/Close')
		assert r.returncode == 0


# ══════════════════════════════════════════════════════════════════════════════
# menu state
# ══════════════════════════════════════════════════════════════════════════════

class TestMenuState:
	def test_help_registered(self):
		out = _help('menu', 'state')
		assert 'ITEM' in out

	@pytest.mark.error
	def test_missing_item_nonzero(self):
		r = ita('menu', 'state')
		assert r.returncode != 0

	@pytest.mark.integration
	def test_known_item_returns_state(self):
		"""Happy: querying a known menu item returns checked/enabled fields."""
		r = ita('menu', 'state', 'Shell/Close')
		assert r.returncode == 0
		assert 'enabled:' in r.stdout

	@pytest.mark.integration
	def test_known_item_json(self):
		"""Happy: --json emits title/enabled/checked keys."""
		r = ita('menu', 'state', 'Shell/Close', '--json')
		assert r.returncode == 0
		data = json.loads(r.stdout)
		assert 'title' in data
		assert 'enabled' in data
		assert 'checked' in data

	@pytest.mark.integration
	@pytest.mark.contract
	def test_json_schema(self):
		"""Contract: menu state --json matches schema."""
		import jsonschema
		schema = {
			'type': 'object',
			'required': ['title', 'enabled', 'checked'],
			'properties': {
				'title': {'type': 'string'},
				'enabled': {'type': 'boolean'},
				'checked': {'type': 'boolean'},
			},
		}
		r = ita('menu', 'state', 'Shell/Close', '--json')
		assert r.returncode == 0
		jsonschema.validate(json.loads(r.stdout), schema)

	@pytest.mark.integration
	@pytest.mark.error
	def test_bad_identifier_error(self):
		"""Error: unknown menu item returns non-zero."""
		r = ita('menu', 'state', 'TOTALLY_NONEXISTENT_ITEM_XYZ')
		assert r.returncode != 0

	@pytest.mark.property
	@pytest.mark.integration
	@given(st.text(min_size=1, max_size=64))
	@settings(max_examples=10)
	def test_arbitrary_item_never_crashes(self, item):
		"""Property: arbitrary menu item strings never cause an unhandled exception."""
		r = ita('menu', 'state', item)
		# Either 0 (found) or non-zero (not found) — never an unhandled Python traceback
		assert 'Traceback' not in r.stderr


# ══════════════════════════════════════════════════════════════════════════════
# repl
# ══════════════════════════════════════════════════════════════════════════════

class TestRepl:
	def test_help_registered(self):
		out = _help('repl')
		assert 'Usage:' in out

	@pytest.mark.contract
	def test_no_null_bytes_in_help(self):
		assert '\x00' not in _help('repl')

	@pytest.mark.edge
	def test_eof_exits_cleanly(self):
		"""Edge: EOF on stdin causes repl to exit with rc=0 (no crash)."""
		import subprocess
		ITA = ['python', '-m', 'ita']
		r = subprocess.run(
			['uv', 'run', *ITA, 'repl'],
			input='',
			capture_output=True, text=True, timeout=15,
		)
		# Should exit 0 and print "Bye."
		assert r.returncode == 0
		assert 'Bye' in r.stdout

	@pytest.mark.edge
	def test_exit_command_quits(self):
		"""Edge: typing 'exit' causes the repl to quit."""
		import subprocess
		ITA = ['python', '-m', 'ita']
		r = subprocess.run(
			['uv', 'run', *ITA, 'repl'],
			input='exit\n',
			capture_output=True, text=True, timeout=15,
		)
		assert r.returncode == 0
		assert 'Bye' in r.stdout

	@pytest.mark.edge
	def test_blank_lines_ignored(self):
		"""Edge: blank input lines don't crash."""
		import subprocess
		ITA = ['python', '-m', 'ita']
		r = subprocess.run(
			['uv', 'run', *ITA, 'repl'],
			input='\n\n\nexit\n',
			capture_output=True, text=True, timeout=15,
		)
		assert r.returncode == 0

	@pytest.mark.error
	def test_unknown_command_nonzero_inner(self):
		"""Error: unknown sub-command inside repl prints error but repl itself exits 0."""
		import subprocess
		ITA = ['python', '-m', 'ita']
		r = subprocess.run(
			['uv', 'run', *ITA, 'repl'],
			input='totally-nonexistent-subcommand\nexit\n',
			capture_output=True, text=True, timeout=15,
		)
		# repl outer process should still exit 0
		assert r.returncode == 0
