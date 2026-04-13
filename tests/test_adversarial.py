"""Adversarial tests — boundary values, error paths, state-after-failure, concurrency.
Goal: find bugs, not confirm working behavior. A passing test here found nothing useful."""
import json
import sys
import threading
import time
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ita

pytestmark = [pytest.mark.integration]


# ── A. Boundary values ────────────────────────────────────────────────────────

def test_resize_zero(session):
	"""resize 0x0 should error cleanly, not crash."""
	r = ita('resize', '--cols', '0', '--rows', '0', '-s', session)
	assert r.returncode in (1, 2), f"resize 0x0 should error; got rc={r.returncode}\nstdout:{r.stdout}\nstderr:{r.stderr}"


def test_resize_negative(session):
	"""resize with negative dimensions should error cleanly."""
	r = ita('resize', '--cols', '-1', '--rows', '-1', '-s', session)
	assert r.returncode in (1, 2), f"resize -1x-1 should error; got rc={r.returncode}"


def test_read_zero_lines(session):
	"""read 0 should succeed with empty output (or defined error)."""
	r = ita('read', '0', '-s', session)
	assert r.returncode in (0, 1, 2), f"read 0 crashed: rc={r.returncode}"


def test_capture_zero_lines(session):
	"""capture -n 0 should succeed without crashing."""
	r = ita('capture', '-n', '0', '-s', session)
	assert r.returncode in (0, 1, 2), f"capture -n 0 crashed: rc={r.returncode}"


def test_capture_to_file(session, tmp_path):
	"""capture FILE should write to disk and rc=0."""
	outfile = str(tmp_path / 'cap.txt')
	r = ita('capture', outfile, '-s', session)
	assert r.returncode == 0, f"capture to file failed: {r.stderr}"
	assert Path(outfile).exists(), "capture wrote no file"


def test_send_empty(session):
	"""send '' should be rc=0 (fire and forget, even empty)."""
	r = ita('send', '', '-s', session)
	assert r.returncode == 0, f"send '' failed: rc={r.returncode} {r.stderr}"


def test_inject_empty_without_hex(session):
	"""inject '' without --hex should be rc=0 no-op."""
	r = ita('inject', '', '-s', session)
	assert r.returncode == 0, f"inject '' failed: rc={r.returncode} {r.stderr}"


def test_name_empty(session):
	"""name '' should error or silently succeed — never crash."""
	r = ita('name', '', '-s', session)
	assert r.returncode in (0, 1, 2), f"name '' crashed unexpectedly: rc={r.returncode}"


def test_name_very_long(session):
	"""name with 500-char string should not crash."""
	long_name = 'x' * 500
	r = ita('name', long_name, '-s', session)
	assert r.returncode in (0, 1), f"name 500 chars crashed: rc={r.returncode}"


def test_send_unicode(session):
	"""send with multibyte unicode + emoji should be rc=0."""
	r = ita('send', '--raw', '你好世界 🎉 αβγδ', '-s', session)
	assert r.returncode == 0, f"send unicode failed: {r.stderr}"


def test_run_very_long_output(session):
	"""run 'seq 1 10000' -n 10000 should capture all lines without truncating line 10000."""
	time.sleep(1)
	r = ita('run', 'seq 1 10000', '-n', '10000', '-s', session, timeout=60)
	assert r.returncode == 0, f"run seq 1 10000 failed: {r.stderr}"
	assert '10000' in r.stdout, f"Last line missing from output; got tail: {r.stdout[-200:]!r}"


def test_tab_goto_out_of_range():
	"""tab goto 9999 should rc=1, not crash."""
	r = ita('tab', 'goto', '9999')
	assert r.returncode in (1, 2), f"tab goto 9999 should error; got rc={r.returncode}"


def test_run_empty_command(session):
	"""run '' should raise ClickException (rc=1) since the code rejects empty commands."""
	r = ita('run', '', '-s', session, timeout=10)
	assert r.returncode in (1, 2), f"run '' should error; got rc={r.returncode}\nstdout:{r.stdout}"


# ── B. Bad references — should fail loudly ───────────────────────────────────

def test_close_fake_session():
	"""close with a fake session ID should rc=1 with an error message."""
	r = ita('close', '-s', 'FAKE_SESSION_ID_DOES_NOT_EXIST')
	assert r.returncode == 1, f"close fake session should rc=1; got {r.returncode}"
	assert r.stderr.strip(), "close fake session produced no error message"


def test_activate_fake_session():
	"""activate with a fake session ID should rc=1 with a message."""
	r = ita('activate', 'FAKE_SESSION_ID_DOES_NOT_EXIST')
	assert r.returncode == 1, f"activate fake session should rc=1; got {r.returncode}"
	assert r.stderr.strip(), "activate fake session produced no error message"


def test_pane_at_boundary(session):
	"""pane right on a single-pane session should rc=1 with message."""
	r = ita('pane', 'right', '-s', session)
	assert r.returncode == 1, f"pane right (single pane) should rc=1; got {r.returncode}\nstdout:{r.stdout}\nstderr:{r.stderr}"
	assert r.stderr.strip(), "pane right (single pane) produced no error message"


def test_pane_all_directions_single_pane(session):
	"""All pane directions on a single-pane session should rc=1 (no adjacent pane)."""
	for direction in ('left', 'above', 'below'):
		r = ita('pane', direction, '-s', session)
		assert r.returncode == 1, f"pane {direction} (single pane) should rc=1; got {r.returncode}"


def test_restore_nonexistent_layout():
	"""restore of nonexistent layout name should rc=1."""
	r = ita('restore', 'LAYOUT_THAT_DOES_NOT_EXIST_EVER_XYZ')
	assert r.returncode == 1, f"restore nonexistent layout should rc=1; got {r.returncode}"


def test_profile_apply_nonexistent(session):
	"""profile apply nonexistent name should rc=1."""
	r = ita('profile', 'apply', 'NONEXISTENT_PROFILE_NAME_XYZ_42', '-s', session)
	assert r.returncode == 1, f"profile apply nonexistent should rc=1; got {r.returncode}"


def test_var_get_nonexistent(session):
	"""var get nonexistent variable should rc=0 with empty output, or rc=1 — not crash."""
	r = ita('var', 'get', 'user.does_not_exist_ever_xyz_42', '-s', session)
	assert r.returncode in (0, 1), f"var get nonexistent crashed: rc={r.returncode}"


def test_on_output_timeout_exits_cleanly(session):
	"""on output with non-matching pattern should time out and exit within timeout+3s."""
	start = time.time()
	r = ita('on', 'output', 'PATTERN_WILL_NEVER_APPEAR_XYZ42', '-t', '3', '-s', session)
	elapsed = time.time() - start
	assert elapsed < 8, f"on output took {elapsed:.1f}s, expected < 8"
	assert r.returncode in (0, 1), f"on output unexpected rc={r.returncode}"
	assert not r.stdout.startswith('Error:'), f"Error prefix in stdout: {r.stdout!r}"


def test_inject_hex_invalid_chars(session):
	"""inject --hex with invalid hex chars should rc=1 with a message."""
	r = ita('inject', '--hex', 'ZZ', '-s', session)
	assert r.returncode == 1, f"inject --hex ZZ should rc=1; got {r.returncode}"
	assert r.stderr.strip(), "inject --hex ZZ produced no error message"


def test_read_nonexistent_session():
	"""ita read -s FAKE_ID should fail cleanly."""
	r = ita('read', '-s', 'FAKE_SESSION_ID_DOES_NOT_EXIST')
	assert r.returncode == 1, f"read on fake session should rc=1; got {r.returncode}"


# ── C. State after error ──────────────────────────────────────────────────────

def test_session_usable_after_timeout(session):
	"""After a run timeout, the session should still accept new commands."""
	time.sleep(1)
	ita('run', 'sleep 60', '--timeout', '2', '-s', session, timeout=10)
	ita('key', 'ctrl+c', '-s', session)
	time.sleep(1)
	r = ita('run', 'echo alive_after_timeout', '-s', session, timeout=15)
	assert r.returncode == 0, f"session not usable after timeout: rc={r.returncode}\nstdout:{r.stdout}\nstderr:{r.stderr}"
	assert 'alive_after_timeout' in r.stdout, f"expected output missing: {r.stdout!r}"


def test_session_usable_after_failed_cmd(session):
	"""After a failing command, the session should still work."""
	time.sleep(1)
	ita('run', 'false', '-s', session, timeout=10)
	r = ita('run', 'echo still_alive', '-s', session, timeout=10)
	assert r.returncode == 0, f"session broken after failing cmd: rc={r.returncode}\nstdout:{r.stdout}"
	assert 'still_alive' in r.stdout, f"expected output missing: {r.stdout!r}"


def test_read_closed_session_fails():
	"""After closing a session, targeting it explicitly should fail cleanly."""
	r_new = ita('new')
	assert r_new.returncode == 0
	sid = r_new.stdout.strip().split('\t')[-1]
	ita('close', '-s', sid)
	time.sleep(0.5)
	# Now targeting the dead session explicitly should fail
	r = ita('read', '-s', sid)
	assert r.returncode == 1, f"read on closed session should rc=1; got {r.returncode}"
	assert r.stderr.strip(), "no error message for read on closed session"


# ── D. Idempotency and double-operation safety ───────────────────────────────

def test_broadcast_on_twice(session):
	"""broadcast on twice should not crash on either call."""
	r1 = ita('broadcast', 'on', '-s', session)
	assert r1.returncode == 0, f"broadcast on (1st) failed: {r1.stderr}"
	r2 = ita('broadcast', 'on', '-s', session)
	assert r2.returncode == 0, f"broadcast on (2nd) failed: {r2.stderr}"
	ita('broadcast', 'off')


def test_broadcast_off_when_none_active():
	"""broadcast off with no active broadcasts should rc=0."""
	ita('broadcast', 'off')  # clear any existing
	r = ita('broadcast', 'off')
	assert r.returncode == 0, f"broadcast off (no broadcasts) should rc=0; got {r.returncode}"


def test_close_already_closed():
	"""Closing an already-closed session should rc=1 with message."""
	r_new = ita('new')
	assert r_new.returncode == 0
	sid = r_new.stdout.strip().split('\t')[-1]
	r1 = ita('close', '-s', sid)
	assert r1.returncode == 0, f"first close failed: {r1.stderr}"
	r2 = ita('close', '-s', sid)
	assert r2.returncode == 1, f"second close should rc=1; got {r2.returncode}"
	assert r2.stderr.strip(), "second close produced no error message"


def test_split_multiple_times(session):
	"""Split 5 times — all should succeed or fail cleanly. All created panes closed."""
	created = []
	try:
		for i in range(5):
			r = ita('split', '-s', session)
			if r.returncode == 0:
				new_sid = r.stdout.strip()
				if new_sid:
					created.append(new_sid)
			else:
				assert r.returncode in (1, 2), f"split #{i} crashed: rc={r.returncode}"
	finally:
		for sid in created:
			ita('close', '-s', sid)


def test_no_session_gives_clear_error():
	"""Commands without -s should give a clear error message."""
	r = ita('read')
	assert r.returncode == 1, f"read without -s should rc=1; got {r.returncode}"
	assert 'no session specified' in r.stderr.lower() or 'session' in r.stderr.lower(), \
		f"Expected clear error about missing session; got: {r.stderr}"


# ── E. Concurrent operations ─────────────────────────────────────────────────

def test_concurrent_run_different_sessions():
	"""Concurrent run commands on separate sessions must both complete without deadlock."""
	r1 = ita('new')
	r2 = ita('new')
	assert r1.returncode == 0 and r2.returncode == 0
	s1 = r1.stdout.strip().split('\t')[-1]
	s2 = r2.stdout.strip().split('\t')[-1]
	results = {}
	try:
		time.sleep(1)

		def do_run(sid, key):
			results[key] = ita('run', 'echo concurrent_ok', '-s', sid, timeout=20)

		t1 = threading.Thread(target=do_run, args=(s1, 'a'))
		t2 = threading.Thread(target=do_run, args=(s2, 'b'))
		t1.start(); t2.start()
		t1.join(timeout=25); t2.join(timeout=25)

		assert 'a' in results, "Thread A never completed"
		assert 'b' in results, "Thread B never completed"
		assert results['a'].returncode == 0, f"Thread A: rc={results['a'].returncode}\n{results['a'].stdout}"
		assert results['b'].returncode == 0, f"Thread B: rc={results['b'].returncode}\n{results['b'].stdout}"
	finally:
		ita('close', '-s', s1)
		ita('close', '-s', s2)


def test_rapid_fire_run(session):
	"""10 sequential run calls to same session must all succeed."""
	time.sleep(1)
	for i in range(10):
		r = ita('run', f'echo rapid_{i}', '-s', session, timeout=15)
		assert r.returncode == 0, f"rapid run #{i} failed: rc={r.returncode}\nstdout:{r.stdout}\nstderr:{r.stderr}"
		assert f'rapid_{i}' in r.stdout, f"rapid run #{i}: output missing: {r.stdout!r}"


# ── F. --json output correctness ─────────────────────────────────────────────

def test_run_json_schema(session):
	"""run --json must produce valid JSON with required fields and correct types."""
	time.sleep(1)
	r = ita('run', 'echo json_schema_test', '--json', '-s', session, timeout=15)
	assert r.returncode == 0, f"run --json failed: {r.stderr}"
	try:
		data = json.loads(r.stdout)
	except json.JSONDecodeError as e:
		pytest.fail(f"run --json produced invalid JSON: {r.stdout!r}\nError: {e}")
	assert 'output' in data, f"Missing 'output' key: {data}"
	assert 'exit_code' in data, f"Missing 'exit_code' key: {data}"
	assert 'elapsed_ms' in data, f"Missing 'elapsed_ms' key: {data}"
	assert isinstance(data['exit_code'], int), f"exit_code must be int, got {type(data['exit_code'])}: {data['exit_code']}"
	assert isinstance(data['elapsed_ms'], int), f"elapsed_ms must be int, got {type(data['elapsed_ms'])}"
	assert 'json_schema_test' in data['output'], f"Expected output content missing: {data['output']!r}"


def test_run_json_nonzero_exit(session):
	"""run --json with exit 7: JSON exit_code must be 7, not 0."""
	time.sleep(1)
	r = ita('run', 'exit 7', '--json', '-s', session, timeout=10)
	assert r.returncode == 7, f"run 'exit 7' should propagate rc=7; got {r.returncode}"
	try:
		data = json.loads(r.stdout)
	except json.JSONDecodeError as e:
		pytest.fail(f"run --json produced invalid JSON: {r.stdout!r}\nError: {e}")
	assert data.get('exit_code') == 7, f"JSON exit_code should be 7, got: {data.get('exit_code')}"


def test_status_json_schema():
	"""status --json must be a JSON array; each item must have 'session_id' and 'session_name'."""
	r = ita('status', '--json')
	assert r.returncode == 0, f"status --json failed: {r.stderr}"
	try:
		data = json.loads(r.stdout)
	except json.JSONDecodeError as e:
		pytest.fail(f"status --json invalid JSON: {r.stdout!r}\nError: {e}")
	assert isinstance(data, list), f"status --json must return list, got {type(data)}"
	for item in data:
		assert 'session_id' in item, f"Session missing 'session_id': {item}"
		assert 'session_name' in item, f"Session missing 'session_name': {item}"


def test_selection_json_when_empty(session):
	"""selection --json with nothing selected must return valid JSON at rc=0."""
	r = ita('selection', '--json', '-s', session)
	assert r.returncode == 0, f"selection --json (no selection) should rc=0; got {r.returncode}\nstderr:{r.stderr}"
	try:
		json.loads(r.stdout)
	except json.JSONDecodeError as e:
		pytest.fail(f"selection --json invalid JSON: {r.stdout!r}\nError: {e}")


def test_get_prompt_json_returns_dict(session):
	"""get-prompt --json must return a valid JSON dict."""
	r = ita('get-prompt', '--json', '-s', session)
	assert r.returncode == 0, f"get-prompt --json failed: rc={r.returncode}\nstderr:{r.stderr}"
	try:
		data = json.loads(r.stdout)
	except json.JSONDecodeError as e:
		pytest.fail(f"get-prompt --json invalid JSON: {r.stdout!r}\nError: {e}")
	assert isinstance(data, dict), f"get-prompt --json must return dict, got {type(data)}: {data}"


# ── G. Split directions ───────────────────────────────────────────────────────

def test_split_horizontal_returns_sid(session):
	"""split -h must return a new session ID."""
	r = ita('split', '-h', '-s', session)
	assert r.returncode == 0, f"split -h failed: {r.stderr}"
	new_sid = r.stdout.strip()
	assert new_sid, "split -h returned no session ID"
	ita('close', '-s', new_sid)


def test_split_vertical_returns_sid(session):
	"""split -v must return a new session ID."""
	r = ita('split', '-v', '-s', session)
	assert r.returncode == 0, f"split -v failed: {r.stderr}"
	new_sid = r.stdout.strip()
	assert new_sid, "split -v returned no session ID"
	ita('close', '-s', new_sid)


def test_split_default_returns_sid(session):
	"""split with no direction flag must return a new session ID."""
	r = ita('split', '-s', session)
	assert r.returncode == 0, f"split (default) failed: {r.stderr}"
	new_sid = r.stdout.strip()
	assert new_sid, "split (default) returned no session ID"
	ita('close', '-s', new_sid)


# ── H. Tab/window lifecycle edge cases ───────────────────────────────────────

def test_tab_list_returns_json():
	"""tab list --json must return a valid JSON array."""
	r = ita('tab', 'list', '--json')
	assert r.returncode == 0, f"tab list --json failed: {r.stderr}"
	try:
		data = json.loads(r.stdout)
	except json.JSONDecodeError as e:
		pytest.fail(f"tab list --json invalid JSON: {r.stdout!r}\nError: {e}")
	assert isinstance(data, list), f"tab list --json must return list, got {type(data)}"


def test_window_list_returns_json():
	"""window list --json must return a valid JSON array."""
	r = ita('window', 'list', '--json')
	assert r.returncode == 0, f"window list --json failed: {r.stderr}"
	try:
		data = json.loads(r.stdout)
	except json.JSONDecodeError as e:
		pytest.fail(f"window list --json invalid JSON: {r.stdout!r}\nError: {e}")
	assert isinstance(data, list), f"window list --json must return list, got {type(data)}"


def test_window_frame_get():
	"""window frame (no args) should return position/size info."""
	r = ita('window', 'frame')
	assert r.returncode == 0, f"window frame failed: {r.stderr}"
	out = r.stdout.strip()
	assert out, "window frame returned empty output"


def test_tab_title_get():
	"""tab title with no arg should return current title."""
	r = ita('tab', 'title')
	assert r.returncode == 0, f"tab title (get) failed: {r.stderr}"


def test_window_title_get():
	"""window title with no arg should return current title."""
	r = ita('window', 'title')
	assert r.returncode == 0, f"window title (get) failed: {r.stderr}"


# ── I. Capture / read content correctness ────────────────────────────────────

def test_run_then_capture_contains_output(session):
	"""After run, capture should include that command's output."""
	time.sleep(1)
	ita('run', 'echo capture_marker_xyz', '-s', session, timeout=15)
	r = ita('capture', '-s', session)
	assert r.returncode == 0, f"capture failed: {r.stderr}"
	assert 'capture_marker_xyz' in r.stdout, f"capture missing run output: {r.stdout[-300:]!r}"


def test_capture_n_limits_lines(session):
	"""capture -n N should return at most N lines."""
	time.sleep(1)
	ita('run', 'seq 1 100', '-s', session, timeout=15)
	r = ita('capture', '-n', '5', '-s', session)
	assert r.returncode == 0, f"capture -n 5 failed: {r.stderr}"
	lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
	assert len(lines) <= 5, f"capture -n 5 returned {len(lines)} lines"


def test_read_returns_recent_lines(session):
	"""After running echo, read should include that output."""
	time.sleep(1)
	ita('run', 'echo read_marker_xyz', '-s', session, timeout=15)
	r = ita('read', '-s', session)
	assert r.returncode == 0, f"read failed: {r.stderr}"
	assert 'read_marker_xyz' in r.stdout, f"read missing recent output: {r.stdout!r}"


# ── J. Miscellaneous ─────────────────────────────────────────────────────────

def test_focus_returns_something():
	"""focus should return some output describing current focus."""
	r = ita('focus')
	assert r.returncode == 0, f"focus failed: {r.stderr}"
	assert r.stdout.strip(), "focus returned empty output"


def test_app_version_returns_something():
	"""app version should return a non-empty version string."""
	r = ita('app', 'version')
	assert r.returncode == 0, f"app version failed: {r.stderr}"
	assert r.stdout.strip(), "app version returned empty output"


def test_pref_list_nonempty():
	"""pref list should return a non-empty list of preference keys."""
	r = ita('pref', 'list')
	assert r.returncode == 0, f"pref list failed: {r.stderr}"
	assert r.stdout.strip(), "pref list returned empty output"


def test_presets_returns_list():
	"""presets should return a non-empty list of color presets."""
	r = ita('presets')
	assert r.returncode == 0, f"presets failed: {r.stderr}"
	assert r.stdout.strip(), "presets returned empty output"


def test_layouts_command():
	"""layouts should rc=0, even if no saved arrangements."""
	r = ita('layouts')
	assert r.returncode == 0, f"layouts failed: {r.stderr}"


def test_broadcast_list_when_empty():
	"""broadcast list should rc=0 even when no broadcast domains active."""
	ita('broadcast', 'off')  # ensure clean state
	r = ita('broadcast', 'list')
	assert r.returncode == 0, f"broadcast list failed: {r.stderr}"


def test_profile_list_returns_profiles():
	"""profile list should return at least one profile."""
	r = ita('profile', 'list')
	assert r.returncode == 0, f"profile list failed: {r.stderr}"
	assert r.stdout.strip(), "profile list returned empty output"


def test_menu_list_returns_items():
	"""menu list should return a non-empty list of menu items."""
	r = ita('menu', 'list')
	assert r.returncode == 0, f"menu list failed: {r.stderr}"
	assert r.stdout.strip(), "menu list returned empty output"
