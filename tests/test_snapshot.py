"""Unit tests for the shared `_core.snapshot` helper (#300, #301, #302).

Verifies one-sweep semantics and parallel-name fetch without a live iTerm2.
Subprocess-style integration coverage lives in test_overview.py / test_orientation.py.
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from ita import _core  # noqa: E402


def _fake_session(sid, name):
	s = SimpleNamespace()
	s.session_id = sid
	s.name = name
	# _fresh_name reads `session.name` variable then `name` then `session.name`
	# attr fallback. Wire async_get_variable to return the fresh name.
	s.async_get_variable = AsyncMock(return_value=name)
	return s


def _fake_app(sessions_per_tab):
	"""Build a minimal app with one window, one tab per group, sessions_per_tab
	is a list of session lists. current_terminal_window unset to exercise the
	defensive AttributeError guard."""
	tabs = [SimpleNamespace(tab_id=f'T{i}', sessions=ss)
		for i, ss in enumerate(sessions_per_tab)]
	window = SimpleNamespace(window_id='W0', tabs=tabs, current_tab=None)
	app = SimpleNamespace(
		terminal_windows=[window],
		current_terminal_window=None,  # snapshot must tolerate
	)
	return app


def test_snapshot_collects_all_sessions(monkeypatch):
	a = _fake_session('S-1', 'alpha')
	b = _fake_session('S-2', 'beta')
	app = _fake_app([[a, b]])

	async def _fake_get_app(connection):
		return app

	monkeypatch.setattr(_core.iterm2, 'async_get_app', _fake_get_app)

	snap = asyncio.run(_core.snapshot(connection=None))
	assert len(snap.sessions) == 2
	assert snap.fresh_names == {'S-1': 'alpha', 'S-2': 'beta'}
	assert snap.names() == {'alpha', 'beta'}
	assert snap.tab_of['S-1'].tab_id == 'T0'
	assert snap.window_of['S-1'].window_id == 'W0'
	assert snap.current_session_id is None


def test_snapshot_empty_app(monkeypatch):
	app = _fake_app([])

	async def _fake_get_app(connection):
		return app

	monkeypatch.setattr(_core.iterm2, 'async_get_app', _fake_get_app)
	snap = asyncio.run(_core.snapshot(connection=None))
	assert snap.sessions == []
	assert snap.fresh_names == {}
	assert snap.names() == set()


def test_snapshot_fresh_names_run_in_parallel(monkeypatch):
	"""All async_get_variable calls should be awaited concurrently — verified
	by giving each session a small sleep and asserting wall-time stays under
	the serial sum (#301)."""
	import time

	def _slow_session(sid, name):
		s = SimpleNamespace()
		s.session_id = sid
		s.name = name

		async def _slow(_var):
			await asyncio.sleep(0.05)
			return name

		s.async_get_variable = _slow
		return s

	sess = [_slow_session(f'S-{i}', f'n{i}') for i in range(8)]
	app = _fake_app([sess])

	async def _fake_get_app(connection):
		return app

	monkeypatch.setattr(_core.iterm2, 'async_get_app', _fake_get_app)

	t0 = time.monotonic()
	asyncio.run(_core.snapshot(connection=None))
	elapsed = time.monotonic() - t0
	# Serial would be 8 * 0.05 = 0.4s. Parallel should be ~0.05s + scheduler.
	# Generous bound (0.2s) keeps the test stable on slow CI.
	assert elapsed < 0.20, f"snapshot fan-out not parallel: {elapsed:.3f}s"


def test_next_free_name_is_pure():
	"""next_free_name signature stays `(prefix, taken)` — callers feed the
	snapshot's names() set in (#302)."""
	assert _core.next_free_name('s', set()) == 's1'
	assert _core.next_free_name('s', {'s1', 's2', 's3'}) == 's4'
	assert _core.next_free_name('s', {'s1', 's3'}) == 's2'
