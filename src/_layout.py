# src/_layout.py
"""Layout commands: split, pane, tab group, window group."""
import json
import click
import iterm2
from _core import cli, run_iterm, resolve_session, set_sticky

DIRECTION_MAP = {
	'right': iterm2.NavigationDirection.RIGHT,
	'left': iterm2.NavigationDirection.LEFT,
	'above': iterm2.NavigationDirection.ABOVE,
	'below': iterm2.NavigationDirection.BELOW,
}


# ── Panes ──────────────────────────────────────────────────────────────────

@cli.command()
@click.option('-v', '--vertical', is_flag=True, help='Side-by-side split')
@click.option('--profile', default=None)
@click.option('-s', '--session', 'session_id', default=None)
def split(vertical, profile, session_id):
	"""Split current pane. New pane becomes sticky target."""
	async def _run(connection):
		session = await resolve_session(connection, session_id)
		new_session = await session.async_split_pane(vertical=vertical, profile=profile)
		return new_session.session_id
	sid = run_iterm(_run)
	set_sticky(sid)
	click.echo(sid)


@cli.command()
@click.argument('direction', type=click.Choice(['right', 'left', 'above', 'below']))
@click.option('-s', '--session', 'session_id', default=None)
def pane(direction, session_id):
	"""Navigate to adjacent split pane. Updates sticky target."""
	async def _run(connection):
		session = await resolve_session(connection, session_id)
		original_id = session.session_id
		app = await iterm2.async_get_app(connection)
		_, tab = app.get_window_and_tab_for_session(session)
		await tab.async_select_pane_in_direction(DIRECTION_MAP[direction])
		new_session = tab.current_session
		if not new_session or new_session.session_id == original_id:
			raise click.ClickException(f"No pane to the {direction} of current session")
		set_sticky(new_session.session_id)
		return new_session.session_id
	sid = run_iterm(_run)
	click.echo(sid)


@cli.command()
@click.argument('session_id_arg', metavar='SESSION_ID')
@click.argument('dest_window_id', metavar='DEST_WINDOW_ID')
@click.option('--vertical', is_flag=True)
def move(session_id_arg, dest_window_id, vertical):
	"""Move a pane to a different window."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		session = app.get_session_by_id(session_id_arg)
		if not session:
			raise click.ClickException(f"Session {session_id_arg!r} not found")
		dest_window = app.get_window_by_id(dest_window_id)
		if not dest_window:
			raise click.ClickException(f"Window {dest_window_id!r} not found")
		dest_session = dest_window.current_tab.current_session
		await app.async_move_session(session, dest_session, split_vertically=vertical, before=False)
	run_iterm(_run)


# ── Tabs ───────────────────────────────────────────────────────────────────

@cli.group()
def tab():
	"""Manage tabs."""
	pass


@tab.command('new')
@click.option('--window', 'window_id', default=None)
@click.option('--profile', default=None)
def tab_new(window_id, profile):
	"""Create new tab. Sets sticky target."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		window = app.get_window_by_id(window_id) if window_id else app.current_terminal_window
		if not window:
			raise click.ClickException("No window available. Run 'ita window new' first.")
		new_tab = await window.async_create_tab(profile=profile)
		session = new_tab.current_session
		set_sticky(session.session_id)
		return session.session_id
	click.echo(run_iterm(_run))


@tab.command('close')
@click.argument('tab_id', required=False)
def tab_close(tab_id):
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		t = app.get_tab_by_id(tab_id) if tab_id else (
			app.current_terminal_window.current_tab if app.current_terminal_window else None)
		if not t:
			raise click.ClickException("Tab not found")
		await t.async_close(force=True)
	run_iterm(_run)


@tab.command('activate')
@click.argument('tab_id')
def tab_activate(tab_id):
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		t = app.get_tab_by_id(tab_id)
		if not t:
			raise click.ClickException(f"Tab {tab_id!r} not found")
		await t.async_activate(order_window_front=True)
	run_iterm(_run)


@tab.command('next')
def tab_next():
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		w = app.current_terminal_window
		if w:
			tabs = w.tabs
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
def tab_list(use_json):
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		return [{'tab_id': t.tab_id, 'window_id': w.window_id, 'panes': len(t.sessions)}
				for w in app.windows for t in w.tabs]
	tabs = run_iterm(_run)
	if use_json:
		click.echo(json.dumps(tabs))
	else:
		for t in tabs:
			click.echo(f"{t['tab_id']}  window={t['window_id']}  panes={t['panes']}")


@tab.command('info')
@click.argument('tab_id', required=False)
def tab_info(tab_id):
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		t = app.get_tab_by_id(tab_id) if tab_id else (
			app.current_terminal_window.current_tab if app.current_terminal_window else None)
		if not t:
			raise click.ClickException("Tab not found")
		return {'tab_id': t.tab_id,
				'sessions': [s.session_id for s in t.sessions],
				'current_session': t.current_session.session_id if t.current_session else None,
				'tmux_window_id': t.tmux_window_id}
	click.echo(json.dumps(run_iterm(_run), indent=2))


@tab.command('move')
def tab_move():
	"""Detach current tab into its own window."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		w = app.current_terminal_window
		if w and w.current_tab:
			await w.current_tab.async_move_to_window()
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
			# Read the tab title via the variable
			val = await t.async_get_variable('titleOverride') or await t.async_get_variable('title')
			return val or ''
		await t.async_set_title(title)
		return None
	result = run_iterm(_run)
	if result is not None:
		click.echo(result)


# ── Windows ────────────────────────────────────────────────────────────────

@cli.group()
def window():
	"""Manage windows."""
	pass


@window.command('new')
@click.option('--profile', default=None)
def window_new(profile):
	async def _run(connection):
		w = await iterm2.Window.async_create(connection, profile=profile)
		return w.window_id
	click.echo(run_iterm(_run))


@window.command('close')
@click.argument('window_id', required=False)
@click.option('--force', is_flag=True, help='Close current window without requiring WINDOW_ID')
def window_close(window_id, force):
	"""Close a window. WINDOW_ID is required unless --force is passed."""
	if not window_id and not force:
		raise click.ClickException(
			"WINDOW_ID required (or pass --force to close the current window)")
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		w = app.get_window_by_id(window_id) if window_id else app.current_terminal_window
		if not w:
			raise click.ClickException(
				f"Window {window_id!r} not found" if window_id else "No current window")
		session_count = sum(len(t.sessions) for t in w.tabs)
		click.echo(f"Closing window with {len(w.tabs)} tab(s), {session_count} session(s).", err=True)
		await w.async_close(force=True)
	run_iterm(_run)


@window.command('activate')
@click.argument('window_id', required=False)
def window_activate(window_id):
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		w = app.get_window_by_id(window_id) if window_id else app.current_terminal_window
		if w:
			await w.async_activate()
	run_iterm(_run)


@window.command('title')
@click.argument('title', required=False)
def window_title(title):
	"""Get current window title, or set it if TITLE provided."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		w = app.current_terminal_window
		if not w:
			raise click.ClickException("No active window")
		if title is None:
			val = await w.async_get_variable('titleOverride') or await w.async_get_variable('title')
			return val or ''
		await w.async_set_title(title)
		return None
	result = run_iterm(_run)
	if result is not None:
		click.echo(result)


@window.command('fullscreen')
@click.argument('mode', type=click.Choice(['on', 'off', 'toggle']), default='toggle', required=False)
def window_fullscreen(mode):
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		w = app.current_terminal_window
		if not w:
			return
		current = await w.async_get_fullscreen()
		target = {'on': True, 'off': False, 'toggle': not current}[mode]
		await w.async_set_fullscreen(target)
	run_iterm(_run)


@window.command('frame')
@click.option('--x', type=float, default=None)
@click.option('--y', type=float, default=None)
@click.option('--w', 'width', type=float, default=None)
@click.option('--h', 'height', type=float, default=None)
def window_frame(x, y, width, height):
	"""Get window position/size. Pass --x/y/w/h to set."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		win = app.current_terminal_window
		if not win:
			raise click.ClickException("No window")
		if any(v is not None for v in [x, y, width, height]):
			cur = await win.async_get_frame()
			frame = iterm2.util.Frame(
				iterm2.util.Point(x if x is not None else cur.origin.x,
								   y if y is not None else cur.origin.y),
				iterm2.util.Size(width if width is not None else cur.size.width,
								  height if height is not None else cur.size.height))
			await win.async_set_frame(frame)
		else:
			f = await win.async_get_frame()
			return f"x={f.origin.x} y={f.origin.y} w={f.size.width} h={f.size.height}"
	result = run_iterm(_run)
	if result:
		click.echo(result)


@window.command('list')
@click.option('--json', 'use_json', is_flag=True)
def window_list(use_json):
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		return [{'window_id': w.window_id, 'tabs': len(w.tabs)} for w in app.windows]
	windows = run_iterm(_run)
	if use_json:
		click.echo(json.dumps(windows))
	else:
		for w in windows:
			click.echo(f"{w['window_id']}  tabs={w['tabs']}")
