# src/_orientation.py
"""Orientation commands: status, focus, version."""
import json
import click
import iterm2
from _core import cli, run_iterm, strip, __version__, \
	add_protected, remove_protected, get_protected, resolve_session


@cli.command()
@click.option('--json', 'use_json', is_flag=True)
@click.option('--ids-only', is_flag=True, help='Print only session IDs (one per line).')
@click.option('--fast', is_flag=True, help='Skip variable queries (process, path); faster on many sessions (#130).')
@click.option('--where', 'filter_expr', default=None, help='Filter sessions by property (e.g., session_name=main).')
def status(use_json, ids_only, fast, filter_expr):
	"""List all sessions: name | short-id | process | path"""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		sessions = []
		for window in app.windows:
			for tab in window.tabs:
				for session in tab.sessions:
					# --fast skips the two async_get_variable round-trips per
					# session — on a 40-session app that's ~80 IPC calls saved.
					if fast:
						proc = ''
						path = ''
					else:
						proc = strip(await session.async_get_variable('jobName') or '')
						path = strip(await session.async_get_variable('path') or '')
					sessions.append({
						'session_id': session.session_id,
						'session_name': strip(session.name or ''),
						'process': proc,
						'path': path,
						'window_id': window.window_id,
						'tab_id': tab.tab_id,
					})
		return sessions

	sessions = run_iterm(_run) or []

	if filter_expr:
		parts = filter_expr.split('=', 1)
		if len(parts) != 2:
			raise click.ClickException(f"Invalid filter format: {filter_expr!r}. Use KEY=VALUE")
		key, value = parts
		sessions = [s for s in sessions if str(s.get(key, '')).strip() == value.strip()]

	if ids_only:
		for s in sessions:
			click.echo(s['session_id'])
		return

	if use_json:
		click.echo(json.dumps(sessions, indent=2, ensure_ascii=False))
		return

	# Name-first format: NAME  SHORT-ID  PROCESS  PATH
	header = f"{'NAME':<15} {'SESSION-ID':<10} {'PROCESS':<9} PATH"
	click.echo(header)
	for s in sessions:
		name = (s['session_name'] or '')[:15].ljust(15)
		short_id = s['session_id'][:8]
		proc = (s['process'] or '')[:9].ljust(9)
		click.echo(f"{name} {short_id:<10} {proc} {s['path']}")


@cli.command()
@click.option('--json', 'use_json', is_flag=True)
def focus(use_json):
	"""Show which element has keyboard focus."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		window = app.current_terminal_window
		if not window:
			return None
		tab = window.current_tab
		session = tab.current_session if tab else None
		return {
			'window_id': window.window_id,
			'tab_id': tab.tab_id if tab else None,
			'session_id': session.session_id if session else None,
			'session_name': strip(session.name or '') if session else None,
		}
	result = run_iterm(_run)
	if not result:
		if use_json:
			click.echo(json.dumps({'window_id': None, 'tab_id': None, 'session_id': None}, ensure_ascii=False))
		else:
			click.echo("No focused window")
		return
	if use_json:
		click.echo(json.dumps(result, indent=2, ensure_ascii=False))
	else:
		click.echo(f"window:  {result['window_id']}")
		click.echo(f"tab:     {result['tab_id']}")
		click.echo(f"session: {result['session_id']}  ({result['session_name']})")


@cli.command()
def version():
	"""Show ita + iTerm2 app version."""
	import subprocess
	try:
		r = subprocess.run(
			['osascript', '-e', 'tell application "iTerm2" to get version'],
			capture_output=True, text=True, timeout=5)
		iterm_ver = r.stdout.strip() or 'unknown'
	except Exception:
		iterm_ver = 'unknown'
	click.echo(f"ita {__version__} (iTerm2 {iterm_ver})")


@cli.command()
@click.option('-s', '--session', 'session_id', default=None,
	help='Session to protect.')
@click.option('--list', 'list_only', is_flag=True, help='List all protected sessions.')
def protect(session_id, list_only):
	"""Mark a session as protected — write commands (run, send, key, inject, close)
	will refuse to target it without --force.  Use this to guard the Claude Code
	terminal or any session you don't want accidentally modified."""
	if list_only:
		ids = get_protected()
		if ids:
			for sid in sorted(ids):
				click.echo(sid)
		else:
			click.echo("No protected sessions.")
		return
	async def _resolve(connection):
		session = await resolve_session(connection, session_id)
		return session.session_id
	sid = run_iterm(_resolve)
	add_protected(sid)
	click.echo(f"Protected: {sid}")


@cli.command()
@click.option('-s', '--session', 'session_id', default=None,
	help='Session to unprotect.')
def unprotect(session_id):
	"""Remove protection from a session (reverse of `ita protect`)."""
	async def _resolve(connection):
		session = await resolve_session(connection, session_id)
		return session.session_id
	sid = run_iterm(_resolve)
	remove_protected(sid)
	click.echo(f"Unprotected: {sid}")
