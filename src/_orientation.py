# src/_orientation.py
"""Orientation commands: status, focus, version, use."""
import json
import click
import iterm2
from _core import cli, run_iterm, strip, get_sticky, set_sticky, clear_sticky, __version__, \
    add_protected, remove_protected, get_protected, resolve_session


@cli.command()
@click.option('--json', 'use_json', is_flag=True)
@click.option('--ids-only', is_flag=True, help='Print only session IDs (one per line).')
@click.option('--where', 'filter_expr', default=None, help='Filter sessions by property (e.g., session_name=main).')
def status(use_json, ids_only, filter_expr):
	"""List all sessions: id | name | process | path | current*"""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		current = get_sticky()
		sessions = []
		for window in app.windows:
			for tab in window.tabs:
				for session in tab.sessions:
					sessions.append({
						'session_id': session.session_id,
						'session_name': strip(session.name or ''),
						'process': strip(await session.async_get_variable('jobName') or ''),
						'path': strip(await session.async_get_variable('path') or ''),
						'current': session.session_id == current,
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

	# Full UUIDs (36 chars) so agents can copy the ID straight into `-s`.
	for s in sessions:
		marker = '*' if s['current'] else ' '
		sid = s['session_id']
		name = s['session_name'][:20].ljust(20)
		proc = s['process'][:10].ljust(10)
		click.echo(f"{marker} {sid}  {name}  {proc}  {s['path']}")


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
@click.argument('session_id', required=False)
@click.option('--clear', is_flag=True, help='Clear sticky target')
def use(session_id, clear):
	"""Set or clear sticky session target."""
	if clear:
		clear_sticky()
		click.echo("Sticky target cleared.")
		return
	if not session_id:
		current = get_sticky()
		click.echo(f"Current target: {current or '(none)'}")
		return
	# Validate the session exists before pinning it
	async def _verify(connection):
		app = await iterm2.async_get_app(connection)
		s = app.get_session_by_id(session_id)
		if s:
			return s.session_id
		# Try prefix match across all sessions
		sid_lower = session_id.lower()
		matches = []
		for window in app.terminal_windows:
			for tab in window.tabs:
				for sess in tab.sessions:
					if sess.session_id.lower().startswith(sid_lower):
						matches.append(sess.session_id)
		if len(matches) == 1:
			return matches[0]
		if len(matches) > 1:
			raise click.ClickException(
				f"Session prefix {session_id!r} is ambiguous: matches {len(matches)} sessions.")
		raise click.ClickException(
			f"Session {session_id!r} not found. Run 'ita status' to list sessions.")
	resolved = run_iterm(_verify)
	set_sticky(resolved)
	click.echo(f"Target set: {resolved}")


@cli.command()
@click.option('-s', '--session', 'session_id', default=None,
	help='Session to protect (default: sticky or focused).')
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
	help='Session to unprotect (default: sticky or focused).')
def unprotect(session_id):
	"""Remove protection from a session (reverse of `ita protect`)."""
	async def _resolve(connection):
		session = await resolve_session(connection, session_id)
		return session.session_id
	sid = run_iterm(_resolve)
	remove_protected(sid)
	click.echo(f"Unprotected: {sid}")
