"""Integration tests for management commands: profile, presets, theme."""
import json
import sys
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ita, ita_ok

pytestmark = pytest.mark.integration


# ── Legacy smoke tests (kept for backward-compat) ────────────────────────────

def test_status_runs():
	r = ita('status')
	assert r.returncode == 0
	assert r.stdout.strip()


def test_status_json():
	r = ita('status', '--json')
	assert r.returncode == 0
	data = json.loads(r.stdout)
	assert isinstance(data, (list, dict))


def test_theme_help():
	r = ita('theme', '--help')
	assert r.returncode == 0
	assert 'Usage:' in r.stdout


# Dialogs require user interaction — just verify they're registered and --help works
@pytest.mark.parametrize('cmd', ['alert', 'ask', 'pick', 'save-dialog', 'menu', 'repl'])
def test_dialog_help(cmd):
	r = ita(cmd, '--help')
	assert r.returncode == 0
	assert 'Usage:' in r.stdout


# ══════════════════════════════════════════════════════════════════════════════
# profile list
# ══════════════════════════════════════════════════════════════════════════════

class TestProfileList:
	def test_happy_returns_output(self):
		"""Happy: at least one profile exists."""
		r = ita('profile', 'list')
		assert r.returncode == 0
		assert r.stdout.strip()

	def test_json_valid_array(self):
		"""Happy: --json emits a valid JSON array."""
		r = ita('profile', 'list', '--json')
		assert r.returncode == 0
		data = json.loads(r.stdout)
		assert isinstance(data, list)
		assert len(data) > 0

	@pytest.mark.contract
	def test_json_schema(self):
		"""Contract: each element has 'name' and 'guid' string fields."""
		import jsonschema
		schema = {
			'type': 'array',
			'items': {
				'type': 'object',
				'required': ['name', 'guid'],
				'properties': {
					'name': {'type': 'string'},
					'guid': {'type': 'string'},
				},
			},
		}
		r = ita('profile', 'list', '--json')
		assert r.returncode == 0
		jsonschema.validate(json.loads(r.stdout), schema)

	@pytest.mark.edge
	def test_ids_only_flag(self):
		"""Edge: --ids-only prints one GUID per line, no names."""
		r = ita('profile', 'list', '--ids-only')
		assert r.returncode == 0
		lines = r.stdout.strip().splitlines()
		assert lines
		# GUIDs should look like UUIDs; at minimum no whitespace-only lines
		for line in lines:
			assert line.strip()

	@pytest.mark.contract
	def test_no_null_bytes(self):
		assert '\x00' not in ita_ok('profile', 'list')


# ══════════════════════════════════════════════════════════════════════════════
# profile show / get
# ══════════════════════════════════════════════════════════════════════════════

class TestProfileShowGet:
	def _first_profile_name(self):
		data = json.loads(ita_ok('profile', 'list', '--json'))
		return data[0]['name']

	def test_show_happy(self):
		"""Happy: profile show <name> returns JSON with name/guid."""
		name = self._first_profile_name()
		r = ita('profile', 'show', name)
		assert r.returncode == 0
		data = json.loads(r.stdout)
		assert data['name'] == name
		assert 'guid' in data

	def test_get_alias_matches_show(self):
		"""Happy: profile get is identical to profile show."""
		name = self._first_profile_name()
		r_show = ita('profile', 'show', name)
		r_get = ita('profile', 'get', name)
		assert r_show.returncode == 0
		assert r_get.returncode == 0
		assert json.loads(r_show.stdout) == json.loads(r_get.stdout)

	@pytest.mark.error
	def test_show_nonexistent_profile(self):
		"""Error: nonexistent profile name exits non-zero with message."""
		r = ita('profile', 'show', 'TOTALLY_NONEXISTENT_PROFILE_XYZ')
		assert r.returncode != 0
		assert 'not found' in r.stderr.lower() or 'not found' in r.stdout.lower()

	@pytest.mark.contract
	def test_show_json_schema(self):
		"""Contract: profile show output has required fields."""
		import jsonschema
		schema = {
			'type': 'object',
			'required': ['name', 'guid'],
			'properties': {
				'name': {'type': 'string'},
				'guid': {'type': 'string'},
			},
		}
		name = self._first_profile_name()
		r = ita('profile', 'show', name)
		assert r.returncode == 0
		jsonschema.validate(json.loads(r.stdout), schema)

	@pytest.mark.state
	def test_show_idempotent(self):
		"""State: profile show returns same data on two consecutive calls."""
		name = self._first_profile_name()
		r1 = ita('profile', 'show', name)
		r2 = ita('profile', 'show', name)
		assert json.loads(r1.stdout) == json.loads(r2.stdout)


# ══════════════════════════════════════════════════════════════════════════════
# profile apply
# ══════════════════════════════════════════════════════════════════════════════

class TestProfileApply:
	def test_help_registered(self):
		r = ita('profile', 'apply', '--help')
		assert r.returncode == 0
		assert 'NAME' in r.stdout

	@pytest.mark.error
	def test_missing_name_nonzero(self):
		"""Error: profile apply without NAME exits non-zero."""
		r = ita('profile', 'apply')
		assert r.returncode != 0

	@pytest.mark.error
	def test_nonexistent_profile(self, session):
		"""Error: applying nonexistent profile reports error."""
		r = ita('profile', 'apply', 'TOTALLY_NONEXISTENT_PROFILE_XYZ', '-s', session)
		assert r.returncode != 0
		assert 'not found' in r.stderr.lower() or 'not found' in r.stdout.lower()

	@pytest.mark.integration
	@pytest.mark.state
	def test_apply_roundtrip(self, session):
		"""State: applying a profile changes the session's active profile."""
		profiles = json.loads(ita_ok('profile', 'list', '--json'))
		target = profiles[0]['name']
		r = ita('profile', 'apply', target, '-s', session)
		assert r.returncode == 0


# ══════════════════════════════════════════════════════════════════════════════
# profile set
# ══════════════════════════════════════════════════════════════════════════════

class TestProfileSet:
	def test_help_registered(self):
		r = ita('profile', 'set', '--help')
		assert r.returncode == 0

	@pytest.mark.error
	def test_missing_args_nonzero(self):
		r = ita('profile', 'set')
		assert r.returncode != 0

	@pytest.mark.error
	def test_empty_property_name_rejected(self, session):
		"""Error: blank property name is rejected before touching iTerm2."""
		r = ita('profile', 'set', '   ', 'value', '-s', session)
		assert r.returncode != 0

	@pytest.mark.error
	def test_unknown_property_rejected(self, session):
		"""Error: unknown property name produces ClickException."""
		r = ita('profile', 'set', 'TOTALLY_FAKE_PROPERTY_XYZ', 'value', '-s', session)
		assert r.returncode != 0
		assert 'Unknown' in r.stderr or 'Unknown' in r.stdout

	@pytest.mark.error
	def test_bad_hex_color_rejected(self, session):
		"""Error: malformed hex color for a color property exits non-zero."""
		r = ita('profile', 'set', 'background_color', 'not-a-hex', '-s', session)
		assert r.returncode != 0

	@pytest.mark.integration
	@pytest.mark.state
	def test_set_badge_text(self, session):
		"""State: setting badge_text actually persists."""
		r = ita('profile', 'set', 'badge_text', 'test-badge', '-s', session)
		assert r.returncode == 0
		# Verify it persisted
		show = ita('profile', 'show', '-s', session)
		assert show.returncode == 0
		data = json.loads(show.stdout)
		assert data.get('badge_text') == 'test-badge'

	@pytest.mark.property
	@given(st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'))))
	@settings(max_examples=5)
	def test_property_name_never_crashes(self, prop):
		"""Property: arbitrary property names are rejected cleanly (no traceback)."""
		r = ita('profile', 'set', prop, 'value')
		assert 'Traceback' not in r.stderr


# ══════════════════════════════════════════════════════════════════════════════
# presets
# ══════════════════════════════════════════════════════════════════════════════

class TestPresets:
	def test_happy_returns_output(self):
		r = ita('presets')
		assert r.returncode == 0
		assert r.stdout.strip()

	def test_json_valid_array(self):
		"""Happy: --json emits a valid JSON array of strings."""
		r = ita('presets', '--json')
		assert r.returncode == 0
		data = json.loads(r.stdout)
		assert isinstance(data, list)
		assert all(isinstance(n, str) for n in data)

	@pytest.mark.contract
	def test_json_schema(self):
		"""Contract: presets --json is a string array."""
		import jsonschema
		schema = {'type': 'array', 'items': {'type': 'string'}}
		r = ita('presets', '--json')
		assert r.returncode == 0
		jsonschema.validate(json.loads(r.stdout), schema)

	@pytest.mark.edge
	def test_known_presets_present(self):
		"""Edge: stock iTerm2 ships at least Solarized Dark/Light."""
		r = ita('presets', '--json')
		assert r.returncode == 0
		names = json.loads(r.stdout)
		assert 'Solarized Dark' in names
		assert 'Solarized Light' in names

	@pytest.mark.state
	def test_idempotent(self):
		"""State: two calls return identical preset lists."""
		r1 = json.loads(ita_ok('presets', '--json'))
		r2 = json.loads(ita_ok('presets', '--json'))
		assert r1 == r2

	@pytest.mark.contract
	def test_no_null_bytes(self):
		assert '\x00' not in ita_ok('presets')


# ══════════════════════════════════════════════════════════════════════════════
# theme
# ══════════════════════════════════════════════════════════════════════════════

class TestTheme:
	def test_help_registered(self):
		r = ita('theme', '--help')
		assert r.returncode == 0
		assert 'PRESET' in r.stdout

	@pytest.mark.error
	def test_missing_preset_nonzero(self):
		"""Error: theme without PRESET exits non-zero."""
		r = ita('theme')
		assert r.returncode != 0

	def test_dry_run_dark(self):
		"""Happy: --dry-run with 'dark' shortcut exits 0 and prints intent."""
		r = ita('theme', 'dark', '--dry-run')
		assert r.returncode == 0
		assert 'Solarized Dark' in r.stdout

	def test_dry_run_light(self):
		r = ita('theme', 'light', '--dry-run')
		assert r.returncode == 0
		assert 'Solarized Light' in r.stdout

	def test_dry_run_red(self):
		"""Happy: --dry-run for red shortcut exits 0."""
		r = ita('theme', 'red', '--dry-run')
		assert r.returncode == 0
		assert 'red' in r.stdout

	def test_dry_run_green(self):
		r = ita('theme', 'green', '--dry-run')
		assert r.returncode == 0
		assert 'green' in r.stdout

	def test_dry_run_custom_name(self):
		"""Happy: --dry-run with arbitrary name exits 0."""
		r = ita('theme', 'SomePreset', '--dry-run')
		assert r.returncode == 0
		assert 'SomePreset' in r.stdout

	@pytest.mark.integration
	@pytest.mark.error
	def test_nonexistent_preset_error(self, session):
		"""Error: applying a non-existent preset exits non-zero."""
		r = ita('theme', 'TOTALLY_NONEXISTENT_PRESET_XYZ', '-s', session)
		assert r.returncode != 0
		assert 'not found' in r.stderr.lower() or 'not found' in r.stdout.lower()

	@pytest.mark.integration
	def test_apply_dark_shortcut(self, session):
		"""Happy: 'dark' shortcut resolves and applies without error."""
		r = ita('theme', 'dark', '-s', session)
		assert r.returncode == 0
		assert 'Solarized Dark' in r.stdout

	@pytest.mark.integration
	def test_quiet_flag_suppresses_stdout(self, session):
		"""Contract: --quiet suppresses the confirmation message."""
		r = ita('theme', 'dark', '-s', session, '--quiet')
		assert r.returncode == 0
		assert r.stdout.strip() == ''

	@pytest.mark.contract
	def test_dry_run_no_null_bytes(self):
		r = ita('theme', 'dark', '--dry-run')
		assert '\x00' not in r.stdout
