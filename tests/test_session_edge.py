"""Edge-case tests for session lifecycle commands."""
import sys
import pytest

sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent))
from conftest import ita

pytestmark = [pytest.mark.integration, pytest.mark.edge]


# ── activate ──────────────────────────────────────────────────────────────────

@pytest.mark.edge
def test_activate_bogus_id_nonzero():
	"""activate with a bogus session ID must exit non-zero."""
	r = ita('activate', '-s', 'no-such-session-xyz')
	assert r.returncode != 0


@pytest.mark.edge
@pytest.mark.error
def test_activate_no_session_arg():
	"""activate with no -s and no positional arg must exit non-zero."""
	r = ita('activate')
	assert r.returncode != 0


# ── close ─────────────────────────────────────────────────────────────────────

@pytest.mark.edge
def test_close_empty_session_arg():
	"""close -s '' (empty string) must exit non-zero with a clear message."""
	r = ita('close', '-s', '')
	assert r.returncode != 0
	assert r.stderr.strip() or r.stdout.strip()


# ── name ──────────────────────────────────────────────────────────────────────

@pytest.mark.edge
def test_name_unicode_title(session):
	"""Renaming a session with a unicode string must succeed."""
	r = ita('name', 'ita-test-\u03b1\u03b2\u03b3', '-y', '-s', session)
	assert r.returncode == 0


@pytest.mark.edge
def test_name_long_title(session):
	"""Very long name (200 chars) must not crash (rc 0 or 1, never 2)."""
	long_name = 'x' * 200
	r = ita('name', long_name, '-y', '-s', session)
	assert r.returncode in (0, 1)


@pytest.mark.edge
@pytest.mark.error
def test_name_whitespace_only_fails(session):
	"""name with whitespace-only string must exit non-zero."""
	r = ita('name', '   ', '-s', session)
	assert r.returncode != 0


# ── restart ───────────────────────────────────────────────────────────────────

@pytest.mark.edge
@pytest.mark.error
def test_restart_bogus_id_nonzero():
	"""restart with a bogus session ID must exit non-zero."""
	r = ita('restart', '-s', 'no-such-session-xyz')
	assert r.returncode != 0


# ── clear ─────────────────────────────────────────────────────────────────────

@pytest.mark.edge
@pytest.mark.error
def test_clear_bogus_id_nonzero():
	"""clear with a bogus session ID must exit non-zero."""
	r = ita('clear', '-s', 'no-such-session-xyz')
	assert r.returncode != 0


@pytest.mark.edge
def test_clear_all_flag(session):
	"""clear --all must complete without error (clears every session)."""
	r = ita('clear', '--all')
	assert r.returncode == 0


# ── capture ───────────────────────────────────────────────────────────────────

@pytest.mark.edge
@pytest.mark.error
def test_capture_bogus_id_nonzero():
	"""capture with a bogus session ID must exit non-zero."""
	r = ita('capture', '-s', 'no-such-session-xyz')
	assert r.returncode != 0


@pytest.mark.edge
def test_capture_lines_1(session):
	"""capture -n 1 must return at most 1 non-empty line."""
	r = ita('capture', '-n', '1', '-s', session)
	assert r.returncode == 0
	lines = [l for l in r.stdout.splitlines() if l.strip()]
	assert len(lines) <= 1
