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
	r = ita('app', 'version')
	assert r.returncode == 0
	assert r.stdout.strip()


def test_app_theme():
	r = ita('app', 'theme')
	assert r.returncode == 0


# ── broadcast ─────────────────────────────────────────────────────────────────

def test_broadcast_list():
	r = ita('broadcast', 'list')
	assert r.returncode == 0


def test_broadcast_on_session_flag(session):
	"""broadcast on should accept -s/--session flag (#50)."""
	r = ita('broadcast', 'on', '-s', session)
	assert r.returncode == 0
	ita('broadcast', 'off')


def test_broadcast_on_off_roundtrip(session):
	ita_ok('broadcast', 'on', '-s', session)
	r = ita('broadcast', 'off')
	assert r.returncode == 0
