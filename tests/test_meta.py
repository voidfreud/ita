"""Tests for _meta.py: commands, doctor."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ita, ita_ok

pytestmark = pytest.mark.integration


# ══════════════════════════════════════════════════════════════════════════════
# commands
# ══════════════════════════════════════════════════════════════════════════════

class TestCommands:
	def test_happy_valid_json(self):
		"""Happy: `commands` always outputs valid JSON."""
		r = ita('commands')
		assert r.returncode == 0
		data = json.loads(r.stdout)
		assert isinstance(data, dict)

	def test_root_name_is_ita(self):
		"""Happy: top-level name is 'ita'."""
		r = ita_ok('commands')
		data = json.loads(r)
		assert data['name'] == 'ita'

	def test_commands_key_present(self):
		"""Happy: root object has 'commands' list."""
		r = ita_ok('commands')
		data = json.loads(r)
		assert 'commands' in data
		assert isinstance(data['commands'], list)
		assert len(data['commands']) > 0

	def test_known_commands_in_tree(self):
		"""Happy: well-known top-level commands appear in the tree."""
		r = ita_ok('commands')
		data = json.loads(r)
		names = {c['name'] for c in data['commands']}
		for expected in ('status', 'new', 'run', 'profile', 'theme', 'doctor'):
			assert expected in names, f"Expected {expected!r} in command tree"

	def test_each_entry_has_name_and_help(self):
		"""Contract: every command entry has 'name' and 'help' fields."""
		r = ita_ok('commands')
		data = json.loads(r)
		def _check(entries):
			for entry in entries:
				assert 'name' in entry, f"Missing 'name': {entry}"
				assert 'help' in entry, f"Missing 'help': {entry}"
				if 'commands' in entry:
					_check(entry['commands'])
		_check(data['commands'])

	@pytest.mark.contract
	def test_json_schema(self):
		"""Contract: output validates against the command-tree schema."""
		import jsonschema
		entry_schema = {
			'type': 'object',
			'required': ['name', 'help'],
			'properties': {
				'name': {'type': 'string'},
				'help': {'type': 'string'},
			},
		}
		root_schema = {
			'type': 'object',
			'required': ['name', 'commands'],
			'properties': {
				'name': {'type': 'string'},
				'commands': {'type': 'array', 'items': entry_schema},
			},
		}
		r = ita_ok('commands')
		jsonschema.validate(json.loads(r), root_schema)

	@pytest.mark.edge
	def test_json_flag_same_output(self):
		"""Edge: --json flag doesn't alter the output (it's always JSON)."""
		r_plain = ita_ok('commands')
		r_flag = ita_ok('commands', '--json')
		assert json.loads(r_plain) == json.loads(r_flag)

	@pytest.mark.contract
	def test_no_null_bytes(self):
		"""Contract: output contains no null bytes."""
		r = ita_ok('commands')
		assert '\x00' not in r

	@pytest.mark.contract
	def test_subgroups_have_commands_key(self):
		"""Contract: group-type entries (Click Groups) expose a 'commands' list."""
		r = ita_ok('commands')
		data = json.loads(r)
		# 'profile' is a known group
		profile_entry = next(
			(c for c in data['commands'] if c['name'] == 'profile'), None
		)
		assert profile_entry is not None, "'profile' not found in command tree"
		assert 'commands' in profile_entry


# ══════════════════════════════════════════════════════════════════════════════
# doctor
# ══════════════════════════════════════════════════════════════════════════════

_KNOWN_CHECKS = (
	'iTerm2 reachable',
	'Python API responding',
	'iTerm2 version',
	'Shell integration',
	'uv available',
	'tmux available',
)


class TestDoctor:
	def test_happy_exits_zero(self):
		"""Happy: doctor exits 0 when iTerm2 is reachable."""
		r = ita('doctor')
		assert r.returncode == 0

	def test_output_non_empty(self):
		"""Happy: doctor writes something to stdout."""
		r = ita('doctor')
		assert r.stdout.strip()

	def test_known_check_names_present(self):
		"""Happy: output contains all expected check names."""
		r = ita('doctor')
		assert r.returncode == 0
		for check in _KNOWN_CHECKS:
			assert check in r.stdout, f"Expected check {check!r} in doctor output"

	def test_checks_have_symbol(self):
		"""Happy: every output line starts with ✓ or ✗."""
		r = ita('doctor')
		assert r.returncode == 0
		lines = [ln for ln in r.stdout.strip().splitlines() if ln.strip()]
		assert lines, "No output lines"
		for line in lines:
			assert line.startswith('✓') or line.startswith('✗'), \
				f"Line doesn't start with status symbol: {line!r}"

	@pytest.mark.edge
	def test_iterm2_reachable_check_passes(self):
		"""Edge: since tests only run when iTerm2 is up, reachable check must be ✓."""
		r = ita('doctor')
		assert r.returncode == 0
		passing = [ln for ln in r.stdout.splitlines() if 'iTerm2 reachable' in ln]
		assert passing, "iTerm2 reachable check not in output"
		assert passing[0].startswith('✓'), \
			f"Expected ✓ for 'iTerm2 reachable', got: {passing[0]!r}"

	@pytest.mark.edge
	def test_python_api_check_passes(self):
		"""Edge: Python API responding check must pass when iTerm2 is up."""
		r = ita('doctor')
		assert r.returncode == 0
		line = next(
			(l for l in r.stdout.splitlines() if 'Python API responding' in l), None
		)
		assert line is not None, "'Python API responding' check not in output"
		assert line.startswith('✓'), f"Expected ✓, got: {line!r}"

	@pytest.mark.edge
	def test_version_check_includes_version_string(self):
		"""Edge: iTerm2 version line includes a version detail in parentheses."""
		r = ita('doctor')
		assert r.returncode == 0
		line = next(
			(l for l in r.stdout.splitlines() if 'iTerm2 version' in l), None
		)
		assert line is not None
		# When it passes it should show e.g. "✓ iTerm2 version (3.5.x)"
		if line.startswith('✓'):
			assert '(' in line, f"Expected version detail in parentheses: {line!r}"

	@pytest.mark.contract
	def test_no_null_bytes(self):
		"""Contract: no null bytes in doctor output."""
		r = ita('doctor')
		assert '\x00' not in r.stdout

	@pytest.mark.contract
	def test_no_ansi_in_non_tty(self):
		"""Contract: when stdout is a pipe (non-TTY), no ANSI escape codes leaked."""
		r = ita('doctor')
		import re
		ansi = re.compile(r'\x1b\[[0-9;]*m')
		assert not ansi.search(r.stdout), f"ANSI codes in output: {r.stdout!r}"

	@pytest.mark.state
	def test_idempotent(self):
		"""State: running doctor twice produces identical output structure."""
		r1 = ita('doctor')
		r2 = ita('doctor')
		# Same lines, same symbols (not exact match — version numbers OK to vary)
		lines1 = [l.split('(')[0].strip() for l in r1.stdout.strip().splitlines()]
		lines2 = [l.split('(')[0].strip() for l in r2.stdout.strip().splitlines()]
		assert lines1 == lines2
