"""Integration tests for config commands: var, pref, app, broadcast."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ita, ita_ok

pytestmark = pytest.mark.integration


# ── var ───────────────────────────────────────────────────────────────────────

def test_var_set_get_roundtrip(session):
	ita_ok('var', 'set', 'testkey', 'testvalue', '-s', session)
	r = ita('var', 'get', 'testkey', '-s', session)
	assert r.returncode == 0
	assert 'testvalue' in r.stdout


def test_var_auto_user_prefix(session):
	"""var set/get auto-prepend user. prefix."""
	ita_ok('var', 'set', 'noprefix', 'val123', '-s', session)
	r = ita('var', 'get', 'noprefix', '-s', session)
	assert r.returncode == 0
	assert 'val123' in r.stdout


@pytest.mark.parametrize('scope', ['session', 'tab', 'window', 'app'])
def test_var_all_scopes(scope, session):
	r = ita('var', 'set', 'scope_test', 'v', '--scope', scope, '-s', session)
	assert r.returncode == 0


def test_var_set_empty_name(session):
	r = ita('var', 'set', '   ', 'value', '-s', session)
	assert r.returncode == 1


# ── pref ──────────────────────────────────────────────────────────────────────

def test_pref_list():
	r = ita('pref', 'list')
	assert r.returncode == 0
	assert len(r.stdout.splitlines()) > 10


def test_pref_list_filter():
	r = ita('pref', 'list', '--filter', 'TMUX')
	assert r.returncode == 0
	for line in r.stdout.splitlines():
		assert 'TMUX' in line.upper()


def test_pref_get_bool_output():
	"""pref get should return 'true' or 'false', not '1' or '0'."""
	r = ita('pref', 'get', 'DIM_BACKGROUND_WINDOWS')
	assert r.returncode == 0
	assert r.stdout.strip() in ('true', 'false'), f"Got {r.stdout.strip()!r}"


def test_pref_set_get_roundtrip():
	key = 'DIM_BACKGROUND_WINDOWS'
	original = ita('pref', 'get', key).stdout.strip()
	try:
		ita_ok('pref', 'set', key, 'false')
		assert ita('pref', 'get', key).stdout.strip() == 'false'
		ita_ok('pref', 'set', key, 'true')
		assert ita('pref', 'get', key).stdout.strip() == 'true'
	finally:
		ita('pref', 'set', key, original)


def test_pref_invalid_key():
	r = ita('pref', 'get', 'NOT_A_REAL_PREF_XYZ_999')
	assert r.returncode == 1
	assert 'Unknown' in r.stderr or 'unknown' in r.stderr.lower()


def test_pref_tmux():
	r = ita('pref', 'tmux')
	assert r.returncode == 0
	import json
	data = json.loads(r.stdout)
	assert isinstance(data, dict)


# ── app ───────────────────────────────────────────────────────────────────────

def test_app_version():
	"""Upgrade smoke → assert version looks like a real version string."""
	import re
	r = ita('app', 'version')
	assert r.returncode == 0
	assert re.search(r'\d+\.\d+', r.stdout), f"Unexpected version output: {r.stdout!r}"


def test_app_activate():
	"""app activate should bring iTerm2 to foreground without error."""
	r = ita('app', 'activate')
	assert r.returncode == 0
	assert not r.stderr.strip(), f"Unexpected stderr: {r.stderr!r}"


def test_app_hide():
	"""app hide should complete successfully (visual effect not assertable)."""
	r = ita('app', 'hide')
	assert r.returncode == 0
	# Restore focus so subsequent tests aren't disrupted
	ita('app', 'activate')


# app quit is intentionally skipped: running it would quit iTerm2 and kill all
# parallel worktrees sharing the same process. Test only via mock if needed.


def test_app_theme():
	"""app theme output should contain a known theme word."""
	r = ita('app', 'theme')
	assert r.returncode == 0
	out = r.stdout.strip().lower()
	assert out, "app theme returned empty output"
	assert any(w in out for w in ('light', 'dark', 'auto', 'minimal', 'highcontrast')), (
		f"Unexpected theme output: {r.stdout!r}"
	)


# ── broadcast ─────────────────────────────────────────────────────────────────

# ── var list ─────────────────────────────────────────────────────────────────

def test_var_list_happy(shared_session):
	r = ita('var', 'list', '--scope', 'session', '-s', shared_session)
	assert r.returncode == 0
	assert r.stdout.strip(), "var list --scope session returned no output"


def test_var_list_all_scopes():
	r = ita('var', 'list')
	assert r.returncode == 0


@pytest.mark.contract
def test_var_list_json_schema():
	"""--json output must be an object keyed by scope, each value a dict."""
	import json
	import jsonschema
	r = ita('var', 'list', '--json', '--scope', 'session')
	assert r.returncode == 0
	data = json.loads(r.stdout)
	schema = {
		'type': 'object',
		'properties': {
			'session': {'type': 'object'},
			'tab': {'type': 'object'},
			'window': {'type': 'object'},
			'app': {'type': 'object'},
		},
	}
	jsonschema.validate(data, schema)


# ── pref theme / pref tmux ────────────────────────────────────────────────────

def test_pref_theme_happy():
	"""pref theme returns non-empty output containing a known theme word."""
	r = ita('pref', 'theme')
	assert r.returncode == 0
	out = r.stdout.strip().lower()
	assert out, "pref theme returned empty output"
	assert any(w in out for w in ('light', 'dark', 'auto', 'minimal', 'highcontrast')), (
		f"Unexpected pref theme output: {r.stdout!r}"
	)


def test_pref_tmux_known_keys():
	"""pref tmux output must include the four known tmux preference keys."""
	import json
	r = ita('pref', 'tmux')
	assert r.returncode == 0
	data = json.loads(r.stdout)
	for key in ('OPEN_TMUX_WINDOWS_IN', 'TMUX_DASHBOARD_LIMIT',
				'AUTO_HIDE_TMUX_CLIENT_SESSION', 'USE_TMUX_PROFILE'):
		assert key in data, f"Missing expected tmux pref key: {key}"


@pytest.mark.error
def test_pref_tmux_bad_key():
	"""pref tmux with an unknown key should fail with a useful error."""
	r = ita('pref', 'tmux', 'NOT_A_REAL_TMUX_PREF_ZZZ', 'true')
	assert r.returncode != 0
	assert 'unknown' in r.stderr.lower() or 'Unknown' in r.stderr


@pytest.mark.contract
def test_pref_set_json_output():
	"""pref set --json must emit {ok: true, key: <key>}."""
	import json
	key = 'DIM_BACKGROUND_WINDOWS'
	original = ita('pref', 'get', key).stdout.strip()
	try:
		r = ita('pref', 'set', key, original, '--json')
		assert r.returncode == 0
		data = json.loads(r.stdout)
		assert data.get('ok') is True
		assert data.get('key') == key
	finally:
		ita('pref', 'set', key, original)

