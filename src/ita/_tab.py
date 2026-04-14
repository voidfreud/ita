# src/_tab.py
"""Tab commands: new, close, activate, navigate, list, info, detach, move, profile, title."""
import asyncio
import json
import os
import click
import iterm2
from ._core import cli, run_iterm, next_free_name, _fresh_name, capture_focus, restore_focus
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
@click.option('--background', is_flag=True,
	help='Create without shifting focus; restore previously-focused target after creation (#346).')
def tab_new(window_id, tab_name, profile, background):
	"""Create new tab. Returns session ID.

	CONTRACT §2 "Focus-fallback is forbidden, end of (#342)" — `--window`
	is required; there is no implicit 'current window' fallback.
	CONTRACT §2 "Mandatory naming on creation (#342)" — when `--name` is
	absent, the tab is titled with the lowest free `t<N>` counter."""
	# #379: env-var fallback so fixtures can opt into background suite-wide.
	if not background and os.environ.get('ITA_DEFAULT_BACKGROUND') == '1':
		background = True
	if not window_id:
		raise ItaError("bad-args",
			"no window specified. Use --window NAME or --window UUID-PREFIX. "
			"Focus-fallback is forbidden (CONTRACT §2, #342).")
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		window = app.get_window_by_id(window_id)
		if not window:
			raise ItaError("not-found", f"Window {window_id!r} not found.")
		captured = await capture_focus(app) if background else None
		# Collect existing tab titles for naming decisions. Parallel fetch
		# (#301) — the prior serial loop paid one RPC per tab.
		all_tabs = [t for w in app.terminal_windows for t in w.tabs]
		titles = await asyncio.gather(
			*(t.async_get_variable('title') for t in all_tabs)
		) if all_tabs else []
		existing_titles: set[str] = {strip_or(t) for t in titles if t}
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
		if captured is not None:
			await restore_focus(app, captured)
		return session.session_id
	click.echo(run_iterm(_run))


def strip_or(s: str) -> str:
	"""Normalise a title to a plain str (mirrors _core.strip's NUL strip)."""
	return (s or '').replace('\x00', '').strip()


@tab.command('close')
@click.argument('tab_id', required=False)
@click.option('--allow-window-close', is_flag=True,
	help='Permit close that would cascade-close the window (CONTRACT §10, #340).')
def tab_close(tab_id, allow_window_close):
	"""Close a tab by ID. `--current` was removed per CONTRACT §2 "Focus-
	fallback is forbidden, end of (#342)"; tab_id is required."""
	if not tab_id:
		raise ItaError("bad-args",
			"no tab specified. Use TAB_ID (tab_id, title, or 8+ char prefix). "
			"Focus-fallback is forbidden (CONTRACT §2, #342).")
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		t = app.get_tab_by_id(tab_id)
		if not t:
			raise ItaError("not-found", f"Tab {tab_id!r} not found.")
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
	exact tab_id → exact title → 8+ char tab_id prefix. Ambiguity is rc=6
	(bad-args); nothing-found is rc=2 (not-found). No fuzzy substring
	matching (#224). Integer-index resolution removed (#342: was a focus
	fallback); use `ita tab goto <idx> --window <W>`."""
	resolved_id = tab_id_opt
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		# 1. Exact tab_id match wins.
		t = app.get_tab_by_id(resolved_id)
		if t:
			await t.async_activate(order_window_front=True)
			return
		# CONTRACT §2 "Focus-fallback is forbidden, end of (#342)": the
		# legacy integer-index branch resolved against
		# `app.current_terminal_window`, a focus fallback. Removed; use
		# `ita tab goto <idx> --window <W>` for explicit index navigation.
		# 2. Exact title match (#224: previously did substring matching on
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
		# 3. 8+ char tab_id prefix, case-insensitive. Below the floor is
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
			f"Tab {resolved_id!r} not found (tried tab_id, title, prefix).")
	run_iterm(_run)


@tab.command('next')
@click.option('--window', 'window_id', required=True,
	help='Window to cycle within. REQUIRED — no focus fallback (#342).')
def tab_next(window_id):
	"""Activate the tab after the current tab within --window."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		w = app.get_window_by_id(window_id)
		if not w:
			raise ItaError("not-found", f"Window {window_id!r} not found.")
		tabs = w.tabs
		# §2 exception: the command is *about* focus within an explicitly-
		# named window — target window is explicit, cycling is the point.
		if not w.current_tab or w.current_tab not in tabs:
			raise ItaError("not-found", "No current tab in window.")
		idx = tabs.index(w.current_tab)
		await tabs[(idx + 1) % len(tabs)].async_activate()
	run_iterm(_run)


@tab.command('prev')
@click.option('--window', 'window_id', required=True,
	help='Window to cycle within. REQUIRED — no focus fallback (#342).')
def tab_prev(window_id):
	"""Activate the tab before the current tab within --window."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		w = app.get_window_by_id(window_id)
		if not w:
			raise ItaError("not-found", f"Window {window_id!r} not found.")
		tabs = w.tabs
		# §2 exception: command is *about* focus within an explicit window.
		if not w.current_tab or w.current_tab not in tabs:
			raise ItaError("not-found", "No current tab in window.")
		idx = tabs.index(w.current_tab)
		await tabs[(idx - 1) % len(tabs)].async_activate()
	run_iterm(_run)


@tab.command('goto')
@click.argument('index', type=int)
@click.option('--window', 'window_id', required=True,
	help='Window to index into. REQUIRED — no focus fallback (#342).')
def tab_goto(index, window_id):
	"""Activate tab at INDEX within --window."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		w = app.get_window_by_id(window_id)
		if not w:
			raise ItaError("not-found", f"Window {window_id!r} not found.")
		if not (0 <= index < len(w.tabs)):
			raise ItaError("not-found", f"No tab at index {index}")
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
@click.argument('tab_id', required=True)
@click.option('--json', 'use_json', is_flag=True)
def tab_info(tab_id, use_json):
	"""TAB_ID is required — CONTRACT §2 "Focus-fallback is forbidden (#342)"."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		t = app.get_tab_by_id(tab_id)
		if not t:
			raise ItaError("not-found", f"Tab {tab_id!r} not found.")
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
@click.argument('tab_id', required=True)
@click.option('--to', 'index', type=int, default=None, help='Reorder to index within window')
def tab_detach(tab_id, index):
	"""Detach TAB_ID into its own window, or reorder with --to. TAB_ID is
	required — CONTRACT §2 "Focus-fallback is forbidden (#342)"."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		t = app.get_tab_by_id(tab_id)
		if not t:
			raise ItaError("not-found", f"Tab {tab_id!r} not found.")
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
@click.argument('tab_id', required=True)
@click.option('--to', 'index', type=int, required=True, help='Reorder to index within window')
def tab_move(tab_id, index):
	"""Reorder TAB_ID to position INDEX within its current window. TAB_ID is
	required — CONTRACT §2 "Focus-fallback is forbidden (#342)"."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		t = app.get_tab_by_id(tab_id)
		if not t:
			raise ItaError("not-found", f"Tab {tab_id!r} not found.")
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
@click.argument('tab_id', required=True)
def tab_profile(profile_name, tab_id):
	"""Set profile for all panes in TAB_ID. TAB_ID is required — CONTRACT §2
	"Focus-fallback is forbidden (#342)"."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		t = app.get_tab_by_id(tab_id)
		if not t:
			raise ItaError("not-found", f"Tab {tab_id!r} not found.")
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
@click.option('--tab', 'tab_id', required=True,
	help='Tab to get/set title on. REQUIRED — no focus fallback (#342).')
def tab_title(title, tab_id):
	"""Get TAB's title, or set it if TITLE provided. --tab required — CONTRACT
	§2 "Focus-fallback is forbidden (#342)"."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		t = app.get_tab_by_id(tab_id)
		if not t:
			raise ItaError("not-found", f"Tab {tab_id!r} not found.")
		if title is None:
			val = await t.async_get_variable('titleOverride') or await t.async_get_variable('title')
			return val or ''
		await t.async_set_title(title)
		return None
	result = run_iterm(_run)
	if result is not None:
		click.echo(result)
