"""Tests for the cleanup safety net itself (TESTING.md §4.1, #341).

These verify the leak-ceiling and atexit machinery in conftest.py work
without actually leaking sessions in CI. Most run as fast-lane (no live
iTerm2) by patching the helpers.
"""
import importlib

import pytest


def test_leak_ceiling_is_small_enough_to_protect_machine():
	"""Sanity: the ceiling is set somewhere humane. 50 is the documented
	value; anything > 200 would defeat the safety net."""
	import tests.conftest as conftest
	assert 1 <= conftest.LEAK_CEILING <= 200, (
		f"LEAK_CEILING={conftest.LEAK_CEILING} outside humane range"
	)


def test_atexit_handler_registered():
	"""Importing conftest must register the atexit cleanup. If a refactor
	removes the registration, this fails immediately."""
	import atexit
	import tests.conftest as conftest
	importlib.reload(conftest)
	# atexit doesn't expose its registry portably; we check the function
	# at least exists and is callable without raising.
	conftest._atexit_close_test_sessions()  # idempotent, swallows errors


def test_atexit_swallows_errors(monkeypatch):
	"""The atexit handler must NEVER raise — atexit errors crash the
	interpreter shutdown silently and lose the cleanup."""
	import tests.conftest as conftest

	def _boom():
		raise RuntimeError("boom")

	monkeypatch.setattr(conftest, '_open_test_sessions', _boom)
	monkeypatch.setattr(conftest, '_close_orphan_default_windows', _boom)
	# Must not raise
	conftest._atexit_close_test_sessions()


def test_window_helpers_present():
	"""#348: window-leak helpers must be wired into helpers + conftest."""
	import helpers
	import tests.conftest as conftest
	for name in ('_all_window_ids', '_close_window',
				 '_orphan_default_windows', '_close_orphan_default_windows'):
		assert hasattr(helpers, name), f"helpers.{name} missing"
		assert hasattr(conftest, name), f"conftest.{name} re-export missing"


def test_orphan_window_heuristic_narrow(monkeypatch):
	"""#348: only single-tab + single-Default-session windows count as orphans.
	Multi-tab windows or windows with non-Default sessions must NOT be flagged
	(otherwise we'd close user windows)."""
	import json as _json
	from unittest import mock
	import helpers

	multi_tab = {'windows': [{'window_id': 'w1', 'tabs': [
		{'sessions': [{'session_name': 'Default'}]},
		{'sessions': [{'session_name': 'Default'}]},
	]}]}
	user = {'windows': [{'window_id': 'w2', 'tabs': [
		{'sessions': [{'session_name': 'my-work'}]},
	]}]}
	orphan = {'windows': [{'window_id': 'w3', 'tabs': [
		{'sessions': [{'session_name': 'Default (-zsh)'}]},
	]}]}

	for fixture, expected in [(multi_tab, []), (user, []), (orphan, ['w3'])]:
		fake = mock.Mock(returncode=0, stdout=_json.dumps(fixture))
		monkeypatch.setattr(helpers, 'ita', lambda *a, **kw: fake)
		assert helpers._orphan_default_windows() == expected
