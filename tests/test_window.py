"""Tests for window commands: new, close, activate, title, fullscreen, frame, list."""
import json
import re
import sys
from pathlib import Path
import pytest
from hypothesis import given, settings
import hypothesis.strategies as st

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ita, ita_ok

pytestmark = pytest.mark.integration


# ── window new ─────────────────────────────────────────────────────────────

def test_window_new_returns_id():
	r = ita('window', 'new')
	assert r.returncode == 0
	wid = r.stdout.strip()
	assert wid, "window new should output a window ID"
	# Clean up by closing the new window
	ita('window', 'close', wid)


def test_window_new_bad_profile():
	r = ita('window', 'new', '--profile', 'NO_SUCH_PROFILE_XYZ_999')
	assert r.returncode == 1
	assert 'not found' in r.stderr.lower() or 'Profile' in r.stderr


# ── window close ───────────────────────────────────────────────────────────

def test_window_close_no_args_rc2():
	r = ita('window', 'close')
	assert r.returncode == 2


@pytest.mark.error
def test_window_close_unknown_id():
	r = ita('window', 'close', 'no-such-window-id-xyz')
	assert r.returncode == 1
	assert 'not found' in r.stderr.lower() or 'Window' in r.stderr


@pytest.mark.state
def test_window_close_actually_removes_window():
	"""Effect test: close really removes the window from window list."""
	r_new = ita('window', 'new')
	assert r_new.returncode == 0
	wid = r_new.stdout.strip()

	r_list_before = ita('window', 'list', '--json')
	assert r_list_before.returncode == 0
	windows_before = json.loads(r_list_before.stdout)
	ids_before = {w['window_id'] for w in windows_before}
	assert wid in ids_before, "new window not found in window list"

	ita('window', 'close', wid)

	r_list_after = ita('window', 'list', '--json')
	assert r_list_after.returncode == 0
	windows_after = json.loads(r_list_after.stdout)
	ids_after = {w['window_id'] for w in windows_after}
	assert wid not in ids_after, "window close did not remove the window"


def test_window_close_dry_run():
	r = ita('window', 'close', '--force', '--dry-run')
	assert r.returncode == 0
	assert 'Would:' in r.stdout


@pytest.mark.edge
def test_window_close_quiet_flag():
	"""--quiet should suppress the informational message on stderr."""
	r_new = ita('window', 'new')
	assert r_new.returncode == 0
	wid = r_new.stdout.strip()
	r = ita('window', 'close', wid, '--quiet')
	assert r.returncode == 0
	assert 'Closing' not in r.stderr


# ── window activate ────────────────────────────────────────────────────────

def test_window_activate_current():
	r = ita('window', 'activate')
	assert r.returncode == 0


def test_window_activate_explicit_id():
	r_list = ita('window', 'list', '--json')
	assert r_list.returncode == 0
	windows = json.loads(r_list.stdout)
	if not windows:
		pytest.skip("No windows available")
	wid = windows[0]['window_id']
	r = ita('window', 'activate', wid)
	assert r.returncode == 0


@pytest.mark.error
def test_window_activate_nonexistent():
	r = ita('window', 'activate', 'no-such-window-id-xyz')
	# activate with nonexistent id silently does nothing (no error per source)
	# this is a candidate bug — document expected vs actual
	assert r.returncode == 0  # source does no error check on nonexistent window


# ── window title ───────────────────────────────────────────────────────────

def test_window_title_get():
	r = ita('window', 'title')
	assert r.returncode == 0


@pytest.mark.state
def test_window_title_set_get_roundtrip():
	"""Priority roundtrip: SET then GET returns the set value."""
	r_set = ita('window', 'title', 'ita-test-window-title')
	assert r_set.returncode == 0
	r_get = ita('window', 'title')
	assert r_get.returncode == 0
	assert 'ita-test-window-title' in r_get.stdout


@pytest.mark.edge
def test_window_title_unicode():
	r = ita('window', 'title', '窓タイトル-ΩΩ')
	assert r.returncode == 0


@pytest.mark.edge
def test_window_title_empty_string():
	"""Setting empty title should not crash."""
	r = ita('window', 'title', '')
	assert r.returncode in (0, 1)


@pytest.mark.property
@settings(max_examples=20)
@given(title=st.text(min_size=1, max_size=80, alphabet=st.characters(blacklist_categories=('Cs',))))
def test_window_title_property_no_crash(title):
	"""Property: setting any printable title should not crash."""
	r = ita('window', 'title', title)
	assert r.returncode in (0, 1)


# ── window fullscreen ──────────────────────────────────────────────────────

def test_window_fullscreen_toggle():
	r = ita('window', 'fullscreen', 'toggle')
	assert r.returncode == 0
	# toggle back to original state
	ita('window', 'fullscreen', 'toggle')


@pytest.mark.state
def test_window_fullscreen_on_off_idempotent():
	"""State: setting fullscreen off twice is idempotent."""
	r1 = ita('window', 'fullscreen', 'off')
	assert r1.returncode == 0
	r2 = ita('window', 'fullscreen', 'off')
	assert r2.returncode == 0


@pytest.mark.error
def test_window_fullscreen_invalid_mode():
	r = ita('window', 'fullscreen', 'invalid_mode')
	assert r.returncode == 2


# ── window frame ───────────────────────────────────────────────────────────

_FRAME_PATTERN = re.compile(r'x=[\d.]+ y=[\d.]+ w=[\d.]+ h=[\d.]+')


def test_window_frame_get():
	r = ita('window', 'frame')
	assert r.returncode == 0
	assert _FRAME_PATTERN.search(r.stdout), f"Unexpected frame output: {r.stdout!r}"


@pytest.mark.state
def test_window_frame_set_get_roundtrip():
	"""Priority roundtrip: SET width/height then GET confirms values."""
	# Read current frame first
	r_before = ita('window', 'frame')
	assert r_before.returncode == 0

	# Set a specific size
	r_set = ita('window', 'frame', '--w', '900', '--h', '600')
	assert r_set.returncode == 0

	r_get = ita('window', 'frame')
	assert r_get.returncode == 0
	assert 'w=900' in r_get.stdout or 'w=900.0' in r_get.stdout, \
		f"frame SET did not persist: got {r_get.stdout!r}"
	assert 'h=600' in r_get.stdout or 'h=600.0' in r_get.stdout, \
		f"frame SET did not persist: got {r_get.stdout!r}"


@pytest.mark.edge
def test_window_frame_partial_set_preserves_other_dims():
	"""Edge: setting only --w should leave x, y, h unchanged."""
	r_before = ita('window', 'frame')
	assert r_before.returncode == 0
	m = _FRAME_PATTERN.search(r_before.stdout)
	assert m
	# parse original values
	orig = dict(item.split('=') for item in r_before.stdout.strip().split())

	ita('window', 'frame', '--w', '850')
	r_after = ita('window', 'frame')
	assert r_after.returncode == 0
	after = dict(item.split('=') for item in r_after.stdout.strip().split())

	assert after['x'] == orig['x'], "partial set changed x unexpectedly"
	assert after['y'] == orig['y'], "partial set changed y unexpectedly"
	assert after['h'] == orig['h'], "partial set changed h unexpectedly"


@pytest.mark.property
@settings(max_examples=15)
@given(
	w=st.floats(min_value=200, max_value=2000, allow_nan=False, allow_infinity=False),
	h=st.floats(min_value=150, max_value=1500, allow_nan=False, allow_infinity=False),
)
def test_window_frame_property_set_get(w, h):
	"""Property: frame SET with arbitrary valid dimensions should not crash."""
	r = ita('window', 'frame', '--w', str(w), '--h', str(h))
	assert r.returncode in (0, 1)


# ── window list ────────────────────────────────────────────────────────────

def test_window_list_plain():
	r = ita('window', 'list')
	assert r.returncode == 0


def test_window_list_json_valid():
	r = ita('window', 'list', '--json')
	assert r.returncode == 0
	data = json.loads(r.stdout)
	assert isinstance(data, list)
	if data:
		assert 'window_id' in data[0]
		assert 'tabs' in data[0]


@pytest.mark.contract
def test_window_list_json_schema():
	"""Contract: --json output matches expected schema."""
	from jsonschema import validate
	schema = {
		'type': 'array',
		'items': {
			'type': 'object',
			'required': ['window_id', 'tabs'],
			'properties': {
				'window_id': {'type': 'string'},
				'tabs': {'type': 'integer', 'minimum': 0},
			},
		},
	}
	r = ita('window', 'list', '--json')
	assert r.returncode == 0
	validate(json.loads(r.stdout), schema)


@pytest.mark.contract
def test_window_list_no_ansi_leakage():
	"""Contract: plain output contains no ANSI escape sequences."""
	r = ita('window', 'list')
	assert r.returncode == 0
	assert '\x1b[' not in r.stdout, "ANSI escape found in window list output"
	assert '\x00' not in r.stdout, "NUL byte found in window list output"
