"""Tests for tab commands: new, close, activate, next, prev, goto, list, info, detach, move, profile, title."""
import json
import sys
from pathlib import Path
import pytest
from hypothesis import given, settings
import hypothesis.strategies as st

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ita

pytestmark = pytest.mark.integration


# ── tab new ────────────────────────────────────────────────────────────────

def test_tab_new_returns_session_id():
	r = ita('tab', 'new')
	assert r.returncode == 0
	sid = r.stdout.strip()
	assert sid, "tab new should return a session ID"
	ita('close', '-s', sid)


def test_tab_new_bad_profile():
	r = ita('tab', 'new', '--profile', 'NO_SUCH_PROFILE_XYZ_999')
	assert r.returncode == 1
	assert 'not found' in r.stderr.lower() or 'Profile' in r.stderr


@pytest.mark.edge
def test_tab_new_unicode_profile_name_rejected():
	r = ita('tab', 'new', '--profile', '✨émoji-profile-ΩΩ')
	assert r.returncode == 1


# ── tab close ──────────────────────────────────────────────────────────────

def test_tab_close_no_args_rc2():
	r = ita('tab', 'close')
	assert r.returncode == 2


@pytest.mark.error
def test_tab_close_unknown_id():
	r = ita('tab', 'close', 'no-such-tab-id-xyz')
	assert r.returncode == 1
	assert 'not found' in r.stderr.lower() or 'Tab' in r.stderr


@pytest.mark.state
def test_tab_close_actually_removes_tab():
	"""Effect test: close really removes the tab from tab list."""
	r_new = ita('tab', 'new')
	assert r_new.returncode == 0
	# Get tab ID via tab list (the new session should be in a tab)
	_new_sid = r_new.stdout.strip()  # noqa: F841 — retained for debugging
	# find the tab that has this session via tab list --json
	r_list_before = ita('tab', 'list', '--json')
	assert r_list_before.returncode == 0
	tabs_before = json.loads(r_list_before.stdout)
	count_before = len(tabs_before)
	# close current tab (just opened)
	ita('tab', 'close', '--current')
	r_list_after = ita('tab', 'list', '--json')
	assert r_list_after.returncode == 0
	tabs_after = json.loads(r_list_after.stdout)
	assert len(tabs_after) < count_before, "tab close did not reduce tab count"


# ── tab activate ───────────────────────────────────────────────────────────

@pytest.mark.error
def test_tab_activate_missing_flag():
	r = ita('tab', 'activate')
	assert r.returncode == 2


@pytest.mark.error
def test_tab_activate_nonexistent():
	r = ita('tab', 'activate', '-t', 'no-such-tab-uuid-xyz')
	assert r.returncode == 1


# ── tab next / prev ────────────────────────────────────────────────────────

@pytest.mark.state
def test_tab_next_moves_focus():
	"""Effect test: tab next actually advances the active tab index."""
	# Create two tabs so next has somewhere to go
	r1 = ita('tab', 'new')
	assert r1.returncode == 0
	r2 = ita('tab', 'new')
	assert r2.returncode == 0
	sid1 = r1.stdout.strip()
	sid2 = r2.stdout.strip()
	try:
		r_info_before = ita('tab', 'info', '--json')
		assert r_info_before.returncode == 0
		info_before = json.loads(r_info_before.stdout)
		tab_before = info_before['tab_id']

		r_next = ita('tab', 'next')
		assert r_next.returncode == 0

		r_info_after = ita('tab', 'info', '--json')
		assert r_info_after.returncode == 0
		info_after = json.loads(r_info_after.stdout)
		tab_after = info_after['tab_id']

		assert tab_before != tab_after, "tab next did not change the active tab"
	finally:
		ita('close', '-s', sid1)
		ita('close', '-s', sid2)


def test_tab_prev_rc0():
	r = ita('tab', 'prev')
	assert r.returncode == 0


# ── tab goto ───────────────────────────────────────────────────────────────

def test_tab_goto_index_0():
	r = ita('tab', 'goto', '0')
	assert r.returncode == 0


@pytest.mark.error
def test_tab_goto_out_of_range():
	r = ita('tab', 'goto', '99999')
	assert r.returncode == 1
	assert 'No tab' in r.stderr or 'tab' in r.stderr.lower()


@pytest.mark.edge
def test_tab_goto_negative():
	r = ita('tab', 'goto', '-1')
	assert r.returncode == 1


# ── tab list ───────────────────────────────────────────────────────────────

def test_tab_list_plain():
	r = ita('tab', 'list')
	assert r.returncode == 0


def test_tab_list_json_valid():
	r = ita('tab', 'list', '--json')
	assert r.returncode == 0
	data = json.loads(r.stdout)
	assert isinstance(data, list)
	if data:
		assert 'tab_id' in data[0]
		assert 'window_id' in data[0]
		assert 'panes' in data[0]


@pytest.mark.contract
def test_tab_list_json_schema():
	"""Contract: --json output matches expected schema."""
	from jsonschema import validate
	schema = {
		'type': 'array',
		'items': {
			'type': 'object',
			'required': ['tab_id', 'window_id', 'panes'],
			'properties': {
				'tab_id': {'type': 'string'},
				'window_id': {'type': 'string'},
				'panes': {'type': 'integer', 'minimum': 0},
			},
		},
	}
	r = ita('tab', 'list', '--json')
	assert r.returncode == 0
	validate(json.loads(r.stdout), schema)


def test_tab_list_ids_only():
	r = ita('tab', 'list', '--ids-only')
	assert r.returncode == 0
	for line in r.stdout.splitlines():
		assert line.strip(), "ids-only output should not include empty lines"


# ── tab info ───────────────────────────────────────────────────────────────

def test_tab_info_plain():
	r = ita('tab', 'info')
	assert r.returncode == 0
	assert 'Tab:' in r.stdout


def test_tab_info_json_valid():
	r = ita('tab', 'info', '--json')
	assert r.returncode == 0
	data = json.loads(r.stdout)
	assert 'tab_id' in data
	assert 'sessions' in data
	assert isinstance(data['sessions'], list)


@pytest.mark.contract
def test_tab_info_json_schema():
	from jsonschema import validate
	schema = {
		'type': 'object',
		'required': ['tab_id', 'sessions', 'current_session', 'tmux_window_id'],
		'properties': {
			'tab_id': {'type': 'string'},
			'sessions': {'type': 'array', 'items': {'type': 'string'}},
			'current_session': {'type': ['string', 'null']},
			'tmux_window_id': {'type': ['string', 'null']},
		},
	}
	r = ita('tab', 'info', '--json')
	assert r.returncode == 0
	validate(json.loads(r.stdout), schema)


@pytest.mark.error
def test_tab_info_nonexistent_id():
	r = ita('tab', 'info', 'no-such-tab-uuid-xyz')
	assert r.returncode == 1
	assert 'not found' in r.stderr.lower() or 'Tab' in r.stderr


# ── tab detach ─────────────────────────────────────────────────────────────

def test_tab_detach_rc0():
	# Create a second tab so we have something to detach
	r_new = ita('tab', 'new')
	assert r_new.returncode == 0
	new_sid = r_new.stdout.strip()
	try:
		r = ita('tab', 'detach')
		assert r.returncode == 0
	finally:
		ita('close', '-s', new_sid)


@pytest.mark.error
def test_tab_detach_out_of_range_index():
	r = ita('tab', 'detach', '--to', '99999')
	assert r.returncode == 1


# ── tab title ──────────────────────────────────────────────────────────────

def test_tab_title_get():
	r = ita('tab', 'title')
	assert r.returncode == 0


@pytest.mark.state
def test_tab_title_set_get_roundtrip():
	"""Roundtrip: set a title then get it back."""
	r_set = ita('tab', 'title', 'ita-test-title-roundtrip')
	assert r_set.returncode == 0
	r_get = ita('tab', 'title')
	assert r_get.returncode == 0
	assert 'ita-test-title-roundtrip' in r_get.stdout


@pytest.mark.edge
def test_tab_title_unicode():
	r = ita('tab', 'title', '日本語タイトル')
	assert r.returncode == 0


@pytest.mark.property
@settings(max_examples=20)
@given(title=st.text(min_size=1, max_size=60, alphabet=st.characters(blacklist_categories=('Cs',))))
def test_tab_title_property_no_crash(title):
	"""Property: setting any printable title should not crash (rc 0 or 1, never 2+)."""
	r = ita('tab', 'title', title)
	assert r.returncode in (0, 1)


# ── tab profile ────────────────────────────────────────────────────────────

@pytest.mark.error
def test_tab_profile_bad_profile():
	r = ita('tab', 'profile', 'NO_SUCH_PROFILE_ZZZ_999')
	assert r.returncode == 1
	assert 'not found' in r.stderr.lower() or 'Profile' in r.stderr
