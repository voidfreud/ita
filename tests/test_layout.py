"""Integration tests for layout commands: split, tab, window, save/restore/layouts, move."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ita, ita_ok

pytestmark = pytest.mark.integration


def test_split_vertical(session):
	r = ita('split', '--vertical', '-s', session)
	assert r.returncode == 0
	new_sid = r.stdout.strip()
	if new_sid:
		ita('close', '-s', new_sid)


def test_split_horizontal(session):
	# No --horizontal flag; omitting --vertical defaults to horizontal split.
	r = ita('split', '-s', session)
	assert r.returncode == 0
	new_sid = r.stdout.strip()
	if new_sid:
		ita('close', '-s', new_sid)


def test_tab_new():
	r = ita('tab', 'new')
	assert r.returncode == 0
	sid = r.stdout.strip()
	if sid:
		ita('close', '-s', sid)


def test_tab_close_no_args_rc2():
	r = ita('tab', 'close')
	assert r.returncode == 2


def test_tab_close_current():
	r_new = ita('tab', 'new')
	assert r_new.returncode == 0
	r = ita('tab', 'close', '--current')
	assert r.returncode == 0


def test_window_new():
	r = ita('window', 'new')
	assert r.returncode == 0
	sid = r.stdout.strip()
	if sid:
		ita('close', '-s', sid)


def test_window_close_no_args_rc2():
	r = ita('window', 'close')
	assert r.returncode == 2


def test_layouts_list():
	r = ita('layouts')
	assert r.returncode == 0


def test_save_restore_roundtrip():
	name = 'ita-test-arrangement'
	r_save = ita('save', '--force', name)
	assert r_save.returncode == 0
	r_restore = ita('restore', name)
	assert r_restore.returncode == 0


def test_move_missing_args_rc2():
	# move requires SESSION_ID and DEST_WINDOW_ID positional args
	r = ita('move')
	assert r.returncode == 2
