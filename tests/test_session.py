"""Integration tests for session lifecycle: new, close, activate, name, restart, resize, clear, capture."""
import os
import sys
import time
import pytest

sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent))
from conftest import ita, ita_ok

pytestmark = pytest.mark.integration


def test_new_creates_session():
	r = ita('new')
	assert r.returncode == 0
	sid = r.stdout.strip()
	assert sid, "new returned empty session ID"
	ita('close', '-s', sid)


def test_new_window_flag():
	r = ita('new', '--window')
	assert r.returncode == 0
	sid = r.stdout.strip()
	assert sid
	ita('close', '-s', sid)


def test_new_bad_profile():
	r = ita('new', '--profile', 'NO_SUCH_PROFILE_XYZ_123')
	assert r.returncode == 1
	assert 'not found' in r.stderr.lower() or 'Profile' in r.stderr


def test_close_explicit(session):
	r = ita('close', '-s', session)
	assert r.returncode == 0


def test_activate(session):
	r = ita('activate', '-s', session)
	assert r.returncode == 0


def test_name_set(session):
	r = ita('name', 'my-test-tab', '-s', session)
	assert r.returncode == 0


def test_name_whitespace_fails(session):
	r = ita('name', '   ', '-s', session)
	assert r.returncode == 1
	assert 'empty' in r.stderr.lower() or 'empty' in r.stdout.lower()


def test_clear(session):
	r = ita('clear', '-s', session)
	assert r.returncode == 0


def test_capture_stdout(session):
	r = ita('capture', '-s', session)
	assert r.returncode == 0


def test_capture_lines_cap(session):
	ita_ok('send', 'seq 1 20', '-s', session)
	time.sleep(1)
	r = ita('capture', '-n', '5', '-s', session)
	assert r.returncode == 0
	lines = [l for l in r.stdout.splitlines() if l.strip()]
	assert len(lines) <= 5


def test_capture_to_file(session, tmp_path):
	out_file = str(tmp_path / 'capture.txt')
	r = ita('capture', out_file, '-s', session)
	assert r.returncode == 0
	assert 'Saved' in r.stdout
	assert os.path.exists(out_file)


def test_restart_returns_session_id(session):
	r = ita('restart', '-s', session)
	assert r.returncode == 0
	new_sid = r.stdout.strip()
	assert new_sid, "restart returned empty session ID"


@pytest.mark.parametrize('cols,rows', [
	(80, 24), (120, 40), (200, 50),
])
def test_resize(session, cols, rows):
	r = ita('resize', '--cols', str(cols), '--rows', str(rows), '-s', session)
	assert r.returncode == 0
