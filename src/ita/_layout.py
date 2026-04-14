# src/_layout.py
"""Layout commands: window group."""
import asyncio
import json
import os
import click
import iterm2
from ._core import cli, run_iterm, confirm_or_skip, next_free_name, capture_focus, restore_focus
from ._envelope import ItaError


# ── Windows ────────────────────────────────────────────────────────────────

@cli.group()
def window():
	"""Manage windows."""
	pass


@window.command('new')
@click.option('--name', 'window_name', default=None,
	help='Explicit title. Collision on --name is bad-args; unset → auto w1/w2/... (#342).')
@click.option('--profile', default=None)
@click.option('--background', is_flag=True,
	help='Create without shifting focus; restore previously-focused target after creation (#346).')
def window_new(window_name, profile, background):
	"""Create new window. Returns window ID.

	CONTRACT §2 "Mandatory naming on creation (#342)" — when `--name` is
	absent, the window is titled with the lowest free `w<N>` counter.
	#379: ITA_DEFAULT_BACKGROUND=1 env var is honored as a fallback default."""
	if not background and os.environ.get('ITA_DEFAULT_BACKGROUND') == '1':
		background = True
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		captured = await capture_focus(app) if background else None
		# Parallel title fetch (#301) — replaces serial loop.
		wins = list(app.terminal_windows)
		titles = await asyncio.gather(
			*(w.async_get_variable('title') for w in wins)
		) if wins else []
		existing_titles: set[str] = {
			t.replace('\x00', '').strip() for t in titles if t
		}
		if window_name and window_name in existing_titles:
			raise ItaError("bad-args",
				f"name {window_name!r} already taken; pick another name.")
		final_name = window_name or next_free_name('w', existing_titles)
		try:
			w = await iterm2.Window.async_create(connection, profile=profile)
		except Exception as e:
			if 'INVALID_PROFILE_NAME' in str(e):
				raise ItaError("bad-args", f"Profile not found: {profile!r}") from e
			raise
		await w.async_set_title(final_name)
		if captured is not None:
			await restore_focus(app, captured)
		return w.window_id
	click.echo(run_iterm(_run))


@window.command('close')
@click.argument('window_id', required=True)
@click.option('-q', '--quiet', is_flag=True, help='Suppress confirmation (#139).')
@click.option('--dry-run', is_flag=True, help='Print what would be closed (#143).')
@click.option('--confirm', is_flag=True, help='Require confirmation (#143).')
@click.option('-y', '--yes', is_flag=True, help='Skip confirmation prompt (#143).')
@click.option('--allow-window-close', is_flag=True,
	help='Required to actually close a window (CONTRACT §10, #340).')
def window_close(window_id, quiet, dry_run, confirm, yes, allow_window_close):
	"""Close WINDOW_ID. WINDOW_ID is required — CONTRACT §2 "Focus-fallback is
	forbidden (#342)". Also requires --allow-window-close per CONTRACT §10
	(#340); dry-run exempt."""
	if not allow_window_close and not dry_run:
		raise ItaError("bad-args",
			"`ita window close` requires --allow-window-close "
			"(CONTRACT §10, #340). Closing a window can take down the "
			"Claude Code session driving ita; explicit opt-in required.")
	msg = f"close window {window_id}"
	if dry_run:
		click.echo(f"Would: {msg}")
		return
	if confirm and not confirm_or_skip(msg, dry_run=False, yes=yes):
		return
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		w = app.get_window_by_id(window_id)
		if not w:
			raise ItaError("not-found", f"Window {window_id!r} not found.")
		session_count = sum(len(t.sessions) for t in w.tabs)
		if not quiet:
			click.echo(f"Closing window with {len(w.tabs)} tab(s), {session_count} session(s).", err=True)
		await w.async_close(force=True)
	run_iterm(_run)


@window.command('activate')
@click.argument('window_id', required=True)
def window_activate(window_id):
	"""Activate WINDOW_ID. Required — CONTRACT §2 "Focus-fallback is forbidden
	(#342)". §2 exception: command *about* focus; target still explicit."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		w = app.get_window_by_id(window_id)
		if not w:
			raise ItaError("not-found", f"Window {window_id!r} not found.")
		await w.async_activate()
	run_iterm(_run)


@window.command('title')
@click.argument('title', required=False)
@click.option('--window', 'window_id', required=True,
	help='Window to get/set title on. REQUIRED — no focus fallback (#342).')
def window_title(title, window_id):
	"""Get WINDOW's title, or set it if TITLE provided. --window required —
	CONTRACT §2 "Focus-fallback is forbidden (#342)"."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		w = app.get_window_by_id(window_id)
		if not w:
			raise ItaError("not-found", f"Window {window_id!r} not found.")
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
@click.option('--window', 'window_id', required=True,
	help='Window to toggle. REQUIRED — no focus fallback (#342).')
def window_fullscreen(mode, window_id):
	"""Toggle fullscreen on WINDOW. --window required — CONTRACT §2
	"Focus-fallback is forbidden (#342)"."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		w = app.get_window_by_id(window_id)
		if not w:
			raise ItaError("not-found", f"Window {window_id!r} not found.")
		current = await w.async_get_fullscreen()
		target = {'on': True, 'off': False, 'toggle': not current}[mode]
		await w.async_set_fullscreen(target)
	run_iterm(_run)


@window.command('frame')
@click.option('--x', type=float, default=None)
@click.option('--y', type=float, default=None)
@click.option('--w', 'width', type=float, default=None)
@click.option('--h', 'height', type=float, default=None)
@click.option('--window', 'window_id', required=True,
	help='Window to read/set frame on. REQUIRED — no focus fallback (#342).')
def window_frame(x, y, width, height, window_id):
	"""Get WINDOW position/size. Pass --x/y/w/h to set. --window required —
	CONTRACT §2 "Focus-fallback is forbidden (#342)"."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		win = app.get_window_by_id(window_id)
		if not win:
			raise ItaError("not-found", f"Window {window_id!r} not found.")
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
