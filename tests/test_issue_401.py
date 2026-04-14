"""Regression tests for #401: preserve macOS frontmost app across focus
capture/restore.

The pre-#401 implementation restored iTerm2's *internal* focused session
but ignored the OS-level foreground — so `ita new` / `tab new` / `layout`
still stole focus from whatever app the user was actually in (editor,
browser, etc.) when iTerm2 raised itself to create the new object.

These tests pin the new behaviour:
  1. `capture_focus` records the macOS frontmost app (subprocess mocked).
  2. `restore_focus` re-activates that app after iTerm2's internal restore.
  3. `restore_focus` skips the OS-level step when the captured app is None
	 or iTerm2 itself (no point bouncing focus back to the app we're in).

Unit-only: subprocess is mocked, no AppleScript executes, no iTerm2 spawn.
"""
import asyncio
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ita._core import FocusSnapshot, capture_focus, restore_focus


pytestmark = pytest.mark.regression


def _run(coro):
	return asyncio.run(coro)


def _mk_app_with_session(session_id='s1'):
	session = MagicMock()
	session.session_id = session_id
	session.async_activate = AsyncMock()
	tab = MagicMock()
	tab.sessions = [session]
	window = MagicMock()
	window.tabs = [tab]
	app = MagicMock()
	app.terminal_windows = [window]
	return app, session


# ── capture_focus records the macOS frontmost app ──────────────────────────

def test_capture_focus_records_macos_app():
	app = MagicMock()
	app.current_terminal_window.window_id = 'w1'
	app.current_terminal_window.current_tab.tab_id = 't1'
	app.current_terminal_window.current_tab.current_session.session_id = 's1'
	fake_proc = MagicMock(returncode=0, stdout='Ghostty\n')
	with patch('ita._core.subprocess.run', return_value=fake_proc) as m:
		snap = _run(capture_focus(app))
	assert snap.macos_app_name == 'Ghostty'
	# Sanity: we actually shelled out to osascript.
	assert m.call_args.args[0][0] == 'osascript'


def test_capture_focus_macos_app_none_on_subprocess_failure():
	"""Timeout / missing binary / nonzero exit → macos_app_name is None, not
	an exception. Capture must remain best-effort."""
	app = MagicMock()
	app.current_terminal_window = None
	with patch('ita._core.subprocess.run',
			   side_effect=subprocess.TimeoutExpired(cmd='osascript', timeout=2.0)):
		snap = _run(capture_focus(app))
	assert snap.macos_app_name is None


# ── restore_focus re-activates the captured macOS app ──────────────────────

def test_restore_focus_reactivates_macos_app():
	app, session = _mk_app_with_session('s1')
	snap = FocusSnapshot(session_id='s1', macos_app_name='Ghostty')
	with patch('ita._core.subprocess.run') as m:
		_run(restore_focus(app, snap))
	session.async_activate.assert_awaited_once()
	# Final subprocess call is the `activate` AppleScript for the captured app.
	assert m.called
	cmd = m.call_args.args[0]
	assert cmd[0] == 'osascript'
	assert 'tell application "Ghostty" to activate' in cmd[2]


def test_restore_focus_skips_macos_when_app_is_iterm2():
	"""If the user was already in iTerm2 at capture time, the OS-level
	restore is a no-op — skip the subprocess call entirely."""
	app, session = _mk_app_with_session('s1')
	snap = FocusSnapshot(session_id='s1', macos_app_name='iTerm2')
	with patch('ita._core.subprocess.run') as m:
		_run(restore_focus(app, snap))
	session.async_activate.assert_awaited_once()
	m.assert_not_called()


def test_restore_focus_skips_macos_when_app_name_is_none():
	app, session = _mk_app_with_session('s1')
	snap = FocusSnapshot(session_id='s1', macos_app_name=None)
	with patch('ita._core.subprocess.run') as m:
		_run(restore_focus(app, snap))
	m.assert_not_called()
