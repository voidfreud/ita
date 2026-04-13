# src/_tab.py
"""Tab commands: new, close, activate, navigate, list, info, detach, move, profile, title."""
import json
import click
import iterm2
from ._core import cli, run_iterm, next_free_name, _fresh_name
from ._envelope import ItaError


@cli.group()
def tab():
	"""Manage tabs."""
	pass


@tab.command('new')
@click.option('--window', 'window_id', default=None,
	help='Window to create the tab in. REQUIRED — no focus fallback (#342).')
@click.option('--name', 'tab_name', default=None,
	help='Explicit title. Collision on --name is bad-args; unset → auto t1/t2/... (#342).')
@click.option('--profile', default=None)
def tab_new(window_id, tab_name, profile):
	"""Create new tab. Returns session ID.

	CONTRACT §2 "Focus-fallback is forbidden, end of (#342)" — `--window`
	is required; there is no implicit 'current window' fallback.
	CONTRACT §2 "Mandatory naming on creation (#342)" — when `--name` is
	absent, the tab is titled with the lowest free `t<N>` counter."""
	if not window_id:
		raise ItaError("bad-args",
			"no window specified. Use --window NAME or --window UUID-PREFIX. "
			"Focus-fallback is forbidden (CONTRACT §2, #342).")
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		window = app.get_window_by_id(window_id)
		if not window:
			raise ItaError("not-found", f"Window {window_id!r} not found.")
		# Collect existing tab titles for naming decisions. Use async_get_variable
		# on 'title' per the resolver's fresh-read discipline.
		existing_titles: set[str] = set()
		for w in app.terminal_windows:
			for t in w.tabs:
				title = await t.async_get_variable('title') or ''
				if title:
					existing_titles.add(strip_or(title))
		# §2: explicit name collision → bad-args (never silent rename).
		if tab_name and tab_name in existing_titles:
			raise ItaError("bad-args",
				f"name {tab_name!r} already taken; pick another name.")
		final_name = tab_name or next_free_name('t', existing_titles)
		try:
			new_tab = await window.async_create_tab(profile=profile)
		except iterm2.CreateTabException as e:
			# #322: structured check against the CreateTabResponse status name,
			# not a substring of arbitrary output.
			if str(e) == 'INVALID_PROFILE_NAME':
				raise ItaError("bad-args", f"Profile not found: {profile!r}") from e
			raise ItaError("bad-args", f"Could not create tab: {e}") from e
		await new_tab.async_set_title(final_name)
		session = new_tab.current_session
		return session.session_id
	click.echo(run_iterm(_run))


def strip_or(s: str) -> str:
	"""Normalise a title to a plain str (mirrors _core.strip's NUL strip)."""
	return (s or '').replace('\x00', '').strip()


@tab.command('close')
@click.argument('tab_id', required=False)
@click.option('--current', '-c', is_flag=True, help='Close the currently active tab')
@click.option('--allow-window-close', is_flag=True,
	help='Permit close that would cascade-close the window (CONTRACT §10, #340).')
def tab_close(tab_id, current, allow_window_close):
	"""Close a tab by ID, or use --current to close the active tab."""
	if not tab_id and not current:
		raise click.UsageError(
			"Specify a tab ID or use --current to close the current tab")
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		t = app.get_tab_by_id(tab_id) if tab_id else (
			app.current_terminal_window.current_tab if app.current_terminal_window else None)
		if not t:
			raise click.ClickException("Tab not found")
		# CONTRACT §10 "Last-tab cascade is refused (#340)": never silently
		# take the window down with the tab.
		from ._cascade import tab_close_would_cascade_window
		if not allow_window_close and tab_close_would_cascade_window(t):
			raise ItaError("bad-args",
				f"Closing tab {t.tab_id} would also close its window "
				f"(last tab in window). Pass --allow-window-close to proceed "
				f"(CONTRACT §10, #340).")
		await t.async_close(force=True)
	run_iterm(_run)


@tab.command('activate')
@click.option('-t', '--tab', 'tab_id_opt', required=True, help='Tab UUID, index, title, or 8+ char tab-id prefix.')
def tab_activate(tab_id_opt):
	"""Activate a tab. Resolution mirrors CONTRACT §2 session resolver:
	exact tab_id → integer index (within the current window) → exact title
	→ 8+ char tab_id prefix. Ambiguity is rc=6 (bad-args); nothing-found is
	rc=2 (not-found). No fuzzy substring matching (#224)."""
	resolved_id = tab_id_opt
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		# 1. Exact tab_id match wins.
		t = app.get_tab_by_id(resolved_id)
		if t:
			await t.async_activate(order_window_front=True)
			return
		# 2. Integer index (within the focused terminal window). Unambiguous
		# by construction; kept separate from the name/prefix path.
		try:
			idx = int(resolved_id)
			w = app.current_terminal_window
			if not w or not (0 <= idx < len(w.tabs)):
				raise ItaError("not-found", f"No tab at index {idx}")
			await w.tabs[idx].async_activate(order_window_front=True)
			return
		except ValueError:
			pass
		# 3. Exact title match (#224: previously did substring matching on
		# tab_id despite the help text saying 'name'). Titles are fetched
		# via async_get_variable; missing titles resolve to empty string.
		import asyncio
		all_tabs = [t for w in app.terminal_windows for t in w.tabs]
		async def _get_title(tab):
			return (await tab.async_get_variable('title')) or ''
		titles = await asyncio.gather(*[_get_title(t) for t in all_tabs])
		title_matches = [t for t, title in zip(all_tabs, titles) if title == resolved_id]
		if len(title_matches) == 1:
			await title_matches[0].async_activate(order_window_front=True)
			return
		if len(title_matches) > 1:
			ids = ', '.join((t.tab_id or '')[:8] for t in title_matches)
			raise ItaError("bad-args",
				f"tab title {resolved_id!r} is ambiguous — matches: {ids}. "
				f"Use the exact tab_id or an 8+ char prefix.")
		# 4. 8+ char tab_id prefix, case-insensitive. Below the floor is
		# treated as not-found, matching the session resolver.
		if len(resolved_id) >= 8:
			needle = resolved_id.lower()
			prefix_matches = [t for t in all_tabs if (t.tab_id or '').lower().startswith(needle)]
			if len(prefix_matches) == 1:
				await prefix_matches[0].async_activate(order_window_front=True)
				return
			if len(prefix_matches) > 1:
				ids = ', '.join((t.tab_id or '')[:8] for t in prefix_matches)
				raise ItaError("bad-args",
					f"tab prefix {resolved_id!r} is ambiguous — matches: {ids}.")
		raise ItaError("not-found",
			f"Tab {resolved_id!r} not found (tried tab_id, index, title, prefix).")
	run_iterm(_run)


@tab.command('next')
def tab_next():
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		w = app.current_terminal_window
		if w:
			tabs = w.tabs
			if not w.current_tab or w.current_tab not in tabs:
				raise click.ClickException("No current tab")
			idx = tabs.index(w.current_tab)
			await tabs[(idx + 1) % len(tabs)].async_activate()
	run_iterm(_run)


@tab.command('prev')
def tab_prev():
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		w = app.current_terminal_window
		if w:
			tabs = w.tabs
			if not w.current_tab or w.current_tab not in tabs:
				raise click.ClickException("No current tab")
			idx = tabs.index(w.current_tab)
			await tabs[(idx - 1) % len(tabs)].async_activate()
	run_iterm(_run)


@tab.command('goto')
@click.argument('index', type=int)
def tab_goto(index):
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		w = app.current_terminal_window
		if not w or not (0 <= index < len(w.tabs)):
			raise click.ClickException(f"No tab at index {index}")
		await w.tabs[index].async_activate()
	run_iterm(_run)


@tab.command('list')
@click.option('--json', 'use_json', is_flag=True)
@click.option('--ids-only', is_flag=True, help='Print only tab IDs (one per line).')
def tab_list(use_json, ids_only):
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		return [{'tab_id': t.tab_id, 'window_id': w.window_id, 'panes': len(t.sessions)}
				for w in app.terminal_windows for t in w.tabs]
	tabs = run_iterm(_run)
	if ids_only:
		for t in tabs:
			click.echo(t['tab_id'])
	elif use_json:
		click.echo(json.dumps(tabs))
	else:
		for t in tabs:
			click.echo(f"{t['tab_id']}  window={t['window_id']}  panes={t['panes']}")


@tab.command('info')
@click.argument('tab_id', required=False)
@click.option('--json', 'use_json', is_flag=True)
def tab_info(tab_id, use_json):
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		if tab_id:
			t = app.get_tab_by_id(tab_id)
		else:
			t = app.current_terminal_window.current_tab if app.current_terminal_window else None
		if not t:
			raise click.ClickException("Tab not found")
		return {'tab_id': t.tab_id,
				'sessions': [s.session_id for s in t.sessions],
				'current_session': t.current_session.session_id if t.current_session else None,
				'tmux_window_id': t.tmux_window_id}
	info = run_iterm(_run)
	if use_json:
		click.echo(json.dumps(info, indent=2))
	else:
		click.echo(f"Tab: {info['tab_id']}")
		click.echo(f"  Panes: {len(info['sessions'])}")
		click.echo(f"  Current: {info['current_session']}")
		if info['tmux_window_id']:
			click.echo(f"  Tmux: {info['tmux_window_id']}")


@tab.command('detach')
@click.argument('tab_id', required=False)
@click.option('--to', 'index', type=int, default=None, help='Reorder to index within window')
def tab_detach(tab_id, index):
	"""Detach current tab into its own window, or reorder with --to."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		t = app.get_tab_by_id(tab_id) if tab_id else (
			app.current_terminal_window.current_tab if app.current_terminal_window else None)
		if not t:
			raise click.ClickException("Tab not found")
		# #284: explicit (window, tab) destructure — matches the iTerm2 API
		# signature `get_window_and_tab_for_session` returns (Window, Tab).
		# `_pane.py` uses `_, tab`; we want the window here to range-check
		# the --to index. The prior `w, _` was correct by coincidence but
		# unclear; this form documents intent and prevents regression.
		window, _found_tab = (
			app.get_window_and_tab_for_session(t.current_session)
			if t.current_session else (None, None)
		)
		if index is not None:
			if not window:
				raise click.ClickException("Cannot find window for tab")
			if not (0 <= index < len(window.tabs)):
				raise click.ClickException(f"Index {index} out of range [0, {len(window.tabs) - 1}]")
			await t.async_move_to_position(index)
		else:
			await t.async_move_to_window()
	run_iterm(_run)


@tab.command('move')
@click.argument('tab_id', required=False)
@click.option('--to', 'index', type=int, required=True, help='Reorder to index within window')
def tab_move(tab_id, index):
	"""Reorder tab to position INDEX within its current window. Use 'tab detach' to move to a new window."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		t = app.get_tab_by_id(tab_id) if tab_id else (
			app.current_terminal_window.current_tab if app.current_terminal_window else None)
		if not t:
			raise click.ClickException("Tab not found")
		# #284: explicit (window, tab) destructure.
		window, _found_tab = (
			app.get_window_and_tab_for_session(t.current_session)
			if t.current_session else (None, None)
		)
		if not window:
			raise click.ClickException("Cannot find window for tab")
		if not (0 <= index < len(window.tabs)):
			raise click.ClickException(f"Index {index} out of range [0, {len(window.tabs) - 1}]")
		await t.async_move_to_position(index)
	run_iterm(_run)


@tab.command('profile')
@click.argument('profile_name')
@click.argument('tab_id', required=False)
def tab_profile(profile_name, tab_id):
	"""Set profile for all panes in a tab."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		t = app.get_tab_by_id(tab_id) if tab_id else (
			app.current_terminal_window.current_tab if app.current_terminal_window else None)
		if not t:
			raise click.ClickException("Tab not found")
		for session in t.sessions:
			try:
				await session.async_set_profile(profile_name)
			except iterm2.rpc.RPCException as e:
				# #322: session.async_set_profile surfaces invalid profile via
				# RPCException whose message is the protobuf status-enum name.
				# Check equality on that structured value, never `in` on an
				# opaque message (which would mis-catch any unrelated RPC).
				if str(e) == 'INVALID_PROFILE_NAME':
					raise ItaError("bad-args",
						f"Profile not found: {profile_name!r}") from e
				raise
	run_iterm(_run)


@tab.command('title')
@click.argument('title', required=False)
def tab_title(title):
	"""Get current tab title, or set it if TITLE provided."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		w = app.current_terminal_window
		if not (w and w.current_tab):
			raise click.ClickException("No active tab")
		t = w.current_tab
		if title is None:
			val = await t.async_get_variable('titleOverride') or await t.async_get_variable('title')
			return val or ''
		await t.async_set_title(title)
		return None
	result = run_iterm(_run)
	if result is not None:
		click.echo(result)
