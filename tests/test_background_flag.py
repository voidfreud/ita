"""Unit tests for --background creation flag (#346).

Verifies:
  * Each of the 3 creation commands (`ita new`, `ita tab new`,
	`ita window new`) declares a `--background` flag.
  * The `_core.capture_focus` / `_core.restore_focus` helpers snapshot
	and re-activate the correct target.
  * `restore_focus` handles a missing / closed original target silently
	(CONTRACT §1 non-goal: no interactive UI decisions).

Integration tests for actual focus restoration live in the integration
suite — the iTerm2 API dance is mocked here.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ita._core import FocusSnapshot, capture_focus, restore_focus
from ita._session import new as session_new
from ita._tab import tab_new
from ita._layout import window_new


# ── Flag-parsing smoke: the option exists on every creation command ────────

def _has_background(cmd) -> bool:
	return any(p.name == 'background' for p in cmd.params)


def test_session_new_has_background_flag():
	assert _has_background(session_new)


def test_tab_new_has_background_flag():
	assert _has_background(tab_new)


def test_window_new_has_background_flag():
	assert _has_background(window_new)


# ── capture_focus: reads window/tab/session, tolerates missing layers ──────

def _run(coro):
	return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


def test_capture_focus_reads_full_triple():
	app = MagicMock()
	app.current_terminal_window.window_id = 'w1'
	app.current_terminal_window.current_tab.tab_id = 't1'
	app.current_terminal_window.current_tab.current_session.session_id = 's1'
	# #401: capture also shells out for macOS frontmost; mock it so the test
	# stays host-independent and fast-lane clean.
	with patch('ita._core._capture_macos_frontmost', return_value=None):
		snap = _run(capture_focus(app))
	assert snap.window_id == 'w1'
	assert snap.tab_id == 't1'
	assert snap.session_id == 's1'


def test_capture_focus_no_focused_window():
	app = MagicMock()
	app.current_terminal_window = None
	with patch('ita._core._capture_macos_frontmost', return_value=None):
		snap = _run(capture_focus(app))
	assert snap == FocusSnapshot()


def test_capture_focus_swallows_exceptions():
	app = MagicMock()
	# Raising property access → capture must still return a snapshot.
	type(app).current_terminal_window = property(
		lambda self: (_ for _ in ()).throw(RuntimeError('boom')))
	with patch('ita._core._capture_macos_frontmost', return_value=None):
		snap = _run(capture_focus(app))
	assert snap == FocusSnapshot()


# ── restore_focus: re-activates on the correct object ──────────────────────

def _mk_app_with_session(session_id='s1'):
	"""Build a mock app whose terminal_windows chain exposes `session_id`."""
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


def test_restore_focus_activates_session():
	app, session = _mk_app_with_session('s1')
	_run(restore_focus(app, FocusSnapshot(session_id='s1')))
	session.async_activate.assert_awaited_once_with(
		select_tab=True, order_window_front=True)


def test_restore_focus_falls_back_to_tab_when_session_gone():
	app = MagicMock()
	app.terminal_windows = []  # session lookup miss
	tab = MagicMock()
	tab.async_activate = AsyncMock()
	app.get_tab_by_id.return_value = tab
	_run(restore_focus(app, FocusSnapshot(tab_id='t1')))
	tab.async_activate.assert_awaited_once_with(order_window_front=True)


def test_restore_focus_silent_when_target_missing():
	"""Target vanished between capture and restore — no raise, no warning."""
	app = MagicMock()
	app.terminal_windows = []
	app.get_tab_by_id.return_value = None
	app.get_window_by_id.return_value = None
	# Must not raise.
	_run(restore_focus(app, FocusSnapshot(
		window_id='w-gone', tab_id='t-gone', session_id='s-gone')))


def test_restore_focus_none_snapshot_is_noop():
	app = MagicMock()
	_run(restore_focus(app, None))  # must not raise
