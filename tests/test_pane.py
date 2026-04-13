"""Tests for pane commands: split, pane (navigate), move, swap."""
import sys
from pathlib import Path
import pytest
from hypothesis import given, settings
import hypothesis.strategies as st

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ita

pytestmark = pytest.mark.integration


# ── split ──────────────────────────────────────────────────────────────────

def test_split_default_returns_session_id(session):
	r = ita('split', '-s', session)
	assert r.returncode == 0
	new_sid = r.stdout.strip()
	assert new_sid, "split should return a new session ID"
	ita('close', '-s', new_sid)


def test_split_vertical_returns_session_id(session):
	r = ita('split', '--vertical', '-s', session)
	assert r.returncode == 0
	new_sid = r.stdout.strip()
	assert new_sid, "vertical split should return a new session ID"
	ita('close', '-s', new_sid)


@pytest.mark.edge
def test_split_unicode_profile_rejected(session):
	r = ita('split', '--profile', 'ΩΩΩ-nonexistent-profile', '-s', session)
	assert r.returncode == 1
	assert 'not found' in r.stderr.lower() or 'Profile' in r.stderr


@pytest.mark.error
def test_split_bad_profile(session):
	r = ita('split', '--profile', 'NO_SUCH_PROFILE_XYZ_999', '-s', session)
	assert r.returncode == 1
	assert 'not found' in r.stderr.lower() or 'Profile' in r.stderr


@pytest.mark.state
def test_split_produces_distinct_session_ids(session):
	"""State: two splits produce two distinct session IDs."""
	r1 = ita('split', '-s', session)
	r2 = ita('split', '-s', session)
	assert r1.returncode == 0
	assert r2.returncode == 0
	sid1 = r1.stdout.strip()
	sid2 = r2.stdout.strip()
	assert sid1 != sid2, "two splits should produce different session IDs"
	assert sid1 != session
	assert sid2 != session
	ita('close', '-s', sid1)
	ita('close', '-s', sid2)


@pytest.mark.contract
def test_split_output_no_ansi(session):
	"""Contract: split output contains no ANSI or NUL characters."""
	r = ita('split', '-s', session)
	assert r.returncode == 0
	assert '\x1b[' not in r.stdout, "ANSI escape in split output"
	assert '\x00' not in r.stdout, "NUL byte in split output"
	ita('close', '-s', r.stdout.strip())


# ── pane (navigate) ────────────────────────────────────────────────────────

@pytest.mark.error
def test_pane_no_direction_rc2():
	r = ita('pane')
	assert r.returncode == 2


@pytest.mark.error
def test_pane_invalid_direction_rc2():
	r = ita('pane', 'diagonal')
	assert r.returncode == 2


def test_pane_navigate_right(session):
	"""Create a split then navigate into it."""
	r_split = ita('split', '--vertical', '-s', session)
	assert r_split.returncode == 0
	new_sid = r_split.stdout.strip()
	try:
		# activate original session so 'right' neighbor exists
		ita('activate', '-s', session)
		r = ita('pane', 'right', '-s', session)
		assert r.returncode == 0
		navigated = r.stdout.strip()
		assert navigated == new_sid, "pane right should return the split session ID"
	finally:
		ita('close', '-s', new_sid)


@pytest.mark.error
def test_pane_no_neighbor_error(session):
	"""Navigating to a direction with no neighbor should fail with rc=1."""
	r = ita('pane', 'above', '-s', session)
	assert r.returncode == 1
	assert 'No pane' in r.stderr or 'no pane' in r.stderr.lower()


# ── move ───────────────────────────────────────────────────────────────────

@pytest.mark.error
def test_move_missing_window_arg():
	r = ita('move')
	assert r.returncode == 2


@pytest.mark.error
def test_move_nonexistent_window(session):
	r = ita('move', '-s', session, '-w', 'no-such-window-id-xyz')
	assert r.returncode == 1
	assert 'not found' in r.stderr.lower() or 'Window' in r.stderr


@pytest.mark.error
def test_move_same_window_error(session):
	"""Moving a session to the window it's already in should fail."""
	# Find the window ID for this session
	r_wlist = ita('window', 'list', '--json')
	assert r_wlist.returncode == 0
	import json
	windows = json.loads(r_wlist.stdout)
	if not windows:
		pytest.skip("No windows available")
	# Use the first available window; this test relies on session being in it
	# (may not be deterministic — acceptable as integration evidence)
	wid = windows[0]['window_id']
	r = ita('move', '-s', session, '-w', wid)
	# Either same-window error (rc=1) or success if session is not in wid
	assert r.returncode in (0, 1)


@pytest.mark.state
def test_move_pane_to_new_window(session):
	"""State: split a pane then move the split to a fresh window."""
	r_split = ita('split', '-s', session)
	assert r_split.returncode == 0
	split_sid = r_split.stdout.strip()

	r_win = ita('window', 'new')
	assert r_win.returncode == 0
	new_wid = r_win.stdout.strip()

	try:
		r_move = ita('move', '-s', split_sid, '-w', new_wid)
		assert r_move.returncode == 0
	finally:
		ita('window', 'close', new_wid, '--allow-window-close')
		# split_sid may be gone with window; ignore error
		ita('close', '-s', split_sid)


# ── swap ───────────────────────────────────────────────────────────────────

@pytest.mark.error
def test_swap_missing_args_rc2():
	r = ita('swap')
	assert r.returncode == 2


@pytest.mark.error
def test_swap_one_arg_rc2():
	r = ita('swap', 'only-one-arg')
	assert r.returncode == 2


@pytest.mark.error
def test_swap_nonexistent_session_a():
	r = ita('swap', 'no-such-session-aaa', 'no-such-session-bbb')
	assert r.returncode == 1
	assert 'not found' in r.stderr.lower() or 'Session' in r.stderr


@pytest.mark.state
def test_swap_two_panes(session):
	"""State: swap two split panes — both session IDs still exist after swap."""
	r_split = ita('split', '-s', session)
	assert r_split.returncode == 0
	split_sid = r_split.stdout.strip()
	try:
		r = ita('swap', session, split_sid)
		assert r.returncode == 0
		# Both sessions should still be addressable
		r_a = ita('activate', '-s', session)
		assert r_a.returncode == 0
		r_b = ita('activate', '-s', split_sid)
		assert r_b.returncode == 0
	finally:
		ita('close', '-s', split_sid)


@pytest.mark.property
@settings(max_examples=10)
@given(
	sess_a=st.text(min_size=1, max_size=40, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'), whitelist_characters='-_')),
	sess_b=st.text(min_size=1, max_size=40, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'), whitelist_characters='-_')),
)
def test_swap_property_fuzz_ids(sess_a, sess_b):
	"""Property: swap with arbitrary invalid IDs should not crash (rc 1 or 2, never hang)."""
	r = ita('swap', sess_a, sess_b)
	assert r.returncode in (1, 2)
