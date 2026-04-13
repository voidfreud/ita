# src/_layout.py
"""Layout commands: window group."""
import json
import click
import iterm2
from ._core import cli, run_iterm, confirm_or_skip


# ── Windows ────────────────────────────────────────────────────────────────

@cli.group()
def window():
	"""Manage windows."""
	pass


@window.command('new')
@click.option('--profile', default=None)
def window_new(profile):
	async def _run(connection):
		try:
			w = await iterm2.Window.async_create(connection, profile=profile)
		except Exception as e:
			if 'INVALID_PROFILE_NAME' in str(e):
				raise click.ClickException(f"Profile not found: {profile!r}") from e
			raise
		return w.window_id
	click.echo(run_iterm(_run))


@window.command('close')
@click.argument('window_id', required=False)
@click.option('--force', is_flag=True, help='Close current window without requiring WINDOW_ID')
@click.option('-q', '--quiet', is_flag=True, help='Suppress confirmation (#139).')
@click.option('--dry-run', is_flag=True, help='Print what would be closed (#143).')
@click.option('--confirm', is_flag=True, help='Require confirmation (#143).')
@click.option('-y', '--yes', is_flag=True, help='Skip confirmation prompt (#143).')
def window_close(window_id, force, quiet, dry_run, confirm, yes):
	"""Close a window. WINDOW_ID is required unless --force is passed."""
	if not window_id and not force:
		raise click.UsageError(
			"WINDOW_ID required (or pass --force to close the current window)")
	target = window_id or 'current window'
	msg = f"close window {target}"
	if dry_run:
		click.echo(f"Would: {msg}")
		return
	if confirm and not confirm_or_skip(msg, dry_run=False, yes=yes):
		return
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		w = app.get_window_by_id(window_id) if window_id else app.current_terminal_window
		if not w:
			raise click.ClickException(
				f"Window {window_id!r} not found" if window_id else "No current window")
		session_count = sum(len(t.sessions) for t in w.tabs)
		if not quiet:
			click.echo(f"Closing window with {len(w.tabs)} tab(s), {session_count} session(s).", err=True)
		await w.async_close(force=True)
	run_iterm(_run)


@window.command('activate')
@click.argument('window_id', required=False)
def window_activate(window_id):
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		w = app.get_window_by_id(window_id) if window_id else app.current_terminal_window
		if not w:
			raise click.ClickException(
				f"Window {window_id!r} not found" if window_id else "No current window")
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
		return [{'window_id': w.window_id, 'tabs': len(w.tabs)} for w in app.terminal_windows]
	windows = run_iterm(_run)
	if use_json:
		click.echo(json.dumps(windows))
	else:
		for w in windows:
			click.echo(f"{w['window_id']}  tabs={w['tabs']}")
