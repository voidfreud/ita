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
	sid = r.stdout.strip().split('\t')[-1]
	assert sid, "new returned empty session ID"
	ita('close', '-s', sid)


def test_new_window_flag():
	r = ita('new', '--window')
	assert r.returncode == 0
	sid = r.stdout.strip().split('\t')[-1]
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
	lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
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


# ── Session identity (v0.2.0) ────────────────────────────────────────────────

def test_resolve_no_session_error():
	"""Commands without -s must give a clear error about missing session."""
	r = ita('read')
	assert r.returncode == 1, f"Expected rc=1 without -s; got {r.returncode}"
	assert 'no session specified' in r.stderr.lower(), \
		f"Expected 'no session specified' in error; got: {r.stderr}"


def test_new_auto_names():
	"""ita new without --name assigns s1, s2, s3 sequentially."""
	sids = []
	try:
		for expected_num in range(1, 4):
			r = ita('new')
			assert r.returncode == 0, f"new failed: {r.stderr}"
			parts = r.stdout.strip().split('\t')
			assert len(parts) == 2, f"Expected name\\tUUID output; got: {r.stdout!r}"
			name, sid = parts
			sids.append(sid)
			# Name should be s<N> (though N depends on existing sessions)
			assert name.startswith('s'), f"Auto-name should start with 's'; got: {name!r}"
			assert name[1:].isdigit(), f"Auto-name suffix should be numeric; got: {name!r}"
	finally:
		for sid in sids:
			ita('close', '-s', sid)


def test_new_name_uniqueness():
	"""ita new --name X twice must error on the second call."""
	unique_name = 'ita-test-unique-name-check'
	r1 = ita('new', '--name', unique_name)
	assert r1.returncode == 0, f"First new --name failed: {r1.stderr}"
	sid1 = r1.stdout.strip().split('\t')[-1]
	try:
		r2 = ita('new', '--name', unique_name)
		assert r2.returncode == 1, f"Second new --name should fail; got rc={r2.returncode}"
		assert 'already exists' in r2.stderr.lower(), \
			f"Expected 'already exists' error; got: {r2.stderr}"
	finally:
		ita('close', '-s', sid1)


def test_new_reuse():
	"""ita new --name X --reuse when X exists returns existing session."""
	unique_name = 'ita-test-reuse-check'
	r1 = ita('new', '--name', unique_name)
	assert r1.returncode == 0, f"First new --name failed: {r1.stderr}"
	sid1 = r1.stdout.strip().split('\t')[-1]
	try:
		r2 = ita('new', '--name', unique_name, '--reuse')
		assert r2.returncode == 0, f"--reuse should succeed; got rc={r2.returncode}"
		sid2 = r2.stdout.strip().split('\t')[-1]
		assert sid1 == sid2, f"--reuse should return same session; got {sid1} vs {sid2}"
	finally:
		ita('close', '-s', sid1)
