"""Integration tests for management commands: status, profile, theme, presets, menu, dialogs, repl."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ita, ita_ok

pytestmark = pytest.mark.integration


def test_status_runs():
	r = ita('status')
	assert r.returncode == 0
	assert r.stdout.strip()


def test_status_json():
	import json
	r = ita('status', '--json')
	assert r.returncode == 0
	data = json.loads(r.stdout)
	assert isinstance(data, (list, dict))


def test_profile_list():
	r = ita('profile', 'list')
	assert r.returncode == 0
	assert r.stdout.strip()  # at least one profile exists


def test_theme_help():
	"""theme takes a PRESET arg directly — verify it's registered and --help works."""
	r = ita('theme', '--help')
	assert r.returncode == 0
	assert 'Usage:' in r.stdout


def test_presets():
	r = ita('presets')
	assert r.returncode == 0


# Dialogs require user interaction — just verify they're registered and --help works
@pytest.mark.parametrize('cmd', ['alert', 'ask', 'pick', 'save-dialog', 'menu', 'repl'])
def test_dialog_help(cmd):
	r = ita(cmd, '--help')
	assert r.returncode == 0
	assert 'Usage:' in r.stdout
