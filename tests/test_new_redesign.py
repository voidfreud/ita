"""Unit tests for the `ita new` redesign (issue #132).

Stubs out `run_iterm` and the async iTerm2 calls so click wiring, flag
combinations, output format, and --cwd / --run / --replace / --json semantics
can be verified without a live iTerm2 connection.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import _session  # noqa: E402
from _core import cli  # noqa: E402


def _fake_session(sid='SID-1', name='', tab_id='TAB-1', window_id='WIN-1'):
	tab = SimpleNamespace(tab_id=tab_id, window=SimpleNamespace(window_id=window_id))
	s = MagicMock()
	s.session_id = sid
	s.name = name
	s.tab = tab
	s.async_set_name = AsyncMock()
	s.async_send_text = AsyncMock()
	s.async_close = AsyncMock()
	s.async_get_variable = AsyncMock(return_value=name)
	return s


def _patch_run_iterm(monkeypatch, fake_app, created_session):
	async def _fake_get_app(connection):
		return fake_app

	async def _fake_window_create(connection, profile=None):
		return SimpleNamespace(
			current_tab=SimpleNamespace(current_session=created_session),
			window_id='WIN-NEW',
		)

	monkeypatch.setattr(_session.iterm2, 'async_get_app', _fake_get_app)
	monkeypatch.setattr(_session.iterm2.Window, 'async_create', _fake_window_create)

	def _fake_run_iterm(coro):
		import asyncio
		return asyncio.run(coro(connection=None))

	monkeypatch.setattr(_session, 'run_iterm', _fake_run_iterm)


def _fake_app_with(existing=()):
	tab = SimpleNamespace(sessions=list(existing))
	window = MagicMock()
	window.tabs = [tab]
	window.current_tab = tab
	window.window_id = 'WIN-EXIST'
	created_session = _fake_session(sid='SID-NEW')
	new_tab = SimpleNamespace(tab_id='TAB-NEW', current_session=created_session, window=window)
	created_session.tab = new_tab
	window.async_create_tab = AsyncMock(return_value=new_tab)
	window._created = created_session
	app = SimpleNamespace(
		terminal_windows=[window],
		current_terminal_window=window,
		windows=[window],
	)
	return app, window


def _make_all_sessions_patch(monkeypatch, sessions):
	monkeypatch.setattr(_session, '_all_sessions', lambda app: list(sessions))


def _invoke(args):
	runner = CliRunner()
	return runner.invoke(cli, ['new'] + args)


def test_auto_name_basic(monkeypatch):
	app, window = _fake_app_with(existing=[])
	_make_all_sessions_patch(monkeypatch, [])
	_patch_run_iterm(monkeypatch, app, window._created)
	r = _invoke([])
	assert r.exit_code == 0, r.output
	name, sid = r.output.strip().split('\t')
	assert name == 's1'
	assert sid == 'SID-NEW'


def test_auto_name_skips_taken(monkeypatch):
	s1 = _fake_session(sid='S1', name='s1')
	s2 = _fake_session(sid='S2', name='s2')
	app, window = _fake_app_with(existing=[s1, s2])
	_make_all_sessions_patch(monkeypatch, [s1, s2])
	_patch_run_iterm(monkeypatch, app, window._created)
	r = _invoke([])
	assert r.exit_code == 0, r.output
	assert r.output.strip().split('\t')[0] == 's3'


def test_name_conflict_errors(monkeypatch):
	existing = _fake_session(sid='OLD', name='build')
	app, window = _fake_app_with(existing=[existing])
	_make_all_sessions_patch(monkeypatch, [existing])
	_patch_run_iterm(monkeypatch, app, window._created)
	r = _invoke(['--name', 'build'])
	assert r.exit_code != 0
	assert 'already exists' in r.output


def test_reuse_returns_existing(monkeypatch):
	existing = _fake_session(sid='OLD', name='build')
	app, window = _fake_app_with(existing=[existing])
	_make_all_sessions_patch(monkeypatch, [existing])
	_patch_run_iterm(monkeypatch, app, window._created)
	r = _invoke(['--name', 'build', '--reuse'])
	assert r.exit_code == 0, r.output
	name, sid = r.output.strip().split('\t')
	assert name == 'build'
	assert sid == 'OLD'
	window.async_create_tab.assert_not_awaited()


def test_replace_closes_then_creates(monkeypatch):
	existing = _fake_session(sid='OLD', name='build')
	app, window = _fake_app_with(existing=[existing])
	_make_all_sessions_patch(monkeypatch, [existing])
	_patch_run_iterm(monkeypatch, app, window._created)
	r = _invoke(['--name', 'build', '--replace'])
	assert r.exit_code == 0, r.output
	name, sid = r.output.strip().split('\t')
	assert name == 'build'
	assert sid == 'SID-NEW'
	existing.async_close.assert_awaited_once()
	window.async_create_tab.assert_awaited_once()


def test_reuse_and_replace_mutually_exclusive(monkeypatch):
	app, window = _fake_app_with(existing=[])
	_make_all_sessions_patch(monkeypatch, [])
	_patch_run_iterm(monkeypatch, app, window._created)
	r = _invoke(['--name', 'x', '--reuse', '--replace'])
	assert r.exit_code != 0
	assert 'mutually exclusive' in r.output


def test_cwd_sends_cd(monkeypatch):
	app, window = _fake_app_with(existing=[])
	_make_all_sessions_patch(monkeypatch, [])
	_patch_run_iterm(monkeypatch, app, window._created)
	r = _invoke(['--name', 'build', '--cwd', '/tmp/my proj'])
	assert r.exit_code == 0, r.output
	calls = [c.args[0] for c in window._created.async_send_text.await_args_list]
	assert any(c.startswith("cd '/tmp/my proj'") and c.endswith('\n') for c in calls)


def test_cwd_quotes_single_quotes(monkeypatch):
	app, window = _fake_app_with(existing=[])
	_make_all_sessions_patch(monkeypatch, [])
	_patch_run_iterm(monkeypatch, app, window._created)
	r = _invoke(['--name', 'b', '--cwd', "/tmp/a'b"])
	assert r.exit_code == 0, r.output
	calls = [c.args[0] for c in window._created.async_send_text.await_args_list]
	assert any('\'"\'"\'' in c for c in calls)


def test_run_command(monkeypatch):
	app, window = _fake_app_with(existing=[])
	_make_all_sessions_patch(monkeypatch, [])
	_patch_run_iterm(monkeypatch, app, window._created)
	r = _invoke(['--name', 'srv', '--run', 'npm run dev'])
	assert r.exit_code == 0, r.output
	calls = [c.args[0] for c in window._created.async_send_text.await_args_list]
	assert 'npm run dev\n' in calls


def test_cwd_then_run_order(monkeypatch):
	app, window = _fake_app_with(existing=[])
	_make_all_sessions_patch(monkeypatch, [])
	_patch_run_iterm(monkeypatch, app, window._created)
	r = _invoke(['--name', 'srv', '--cwd', '/tmp/x', '--run', 'echo hi'])
	assert r.exit_code == 0, r.output
	calls = [c.args[0] for c in window._created.async_send_text.await_args_list]
	cd_idx = next(i for i, c in enumerate(calls) if c.startswith("cd '/tmp/x'"))
	run_idx = calls.index('echo hi\n')
	assert cd_idx < run_idx


def test_json_output(monkeypatch):
	app, window = _fake_app_with(existing=[])
	_make_all_sessions_patch(monkeypatch, [])
	_patch_run_iterm(monkeypatch, app, window._created)
	r = _invoke(['--name', 'build', '--json'])
	assert r.exit_code == 0, r.output
	payload = json.loads(r.output.strip())
	assert payload['name'] == 'build'
	assert payload['session_id'] == 'SID-NEW'
	assert 'tab_id' in payload and 'window_id' in payload


def test_json_reuse(monkeypatch):
	existing = _fake_session(sid='OLD', name='build', tab_id='T-OLD', window_id='W-OLD')
	app, window = _fake_app_with(existing=[existing])
	_make_all_sessions_patch(monkeypatch, [existing])
	_patch_run_iterm(monkeypatch, app, window._created)
	r = _invoke(['--name', 'build', '--reuse', '--json'])
	assert r.exit_code == 0, r.output
	payload = json.loads(r.output.strip())
	assert payload['session_id'] == 'OLD'
	assert payload['tab_id'] == 'T-OLD'
	assert payload['window_id'] == 'W-OLD'
