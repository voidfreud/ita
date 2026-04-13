# src/_orientation.py
"""Orientation commands: status, focus, version."""
import asyncio
import json
import click
import iterm2
from ._core import cli, run_iterm, strip, __version__, \
	add_protected, remove_protected, get_protected, resolve_session, \
	parse_filter, match_filter, snapshot
from ._envelope import ita_command
from ._state import derive_state


@cli.command()
@click.option('--json', 'use_json', is_flag=True)
@click.option('--ids-only', is_flag=True, help='Print only session IDs (one per line).')
@click.option('--fast', is_flag=True, help='Skip variable queries (process, path); faster on many sessions (#130).')
@click.option('--where', 'filter_expr', default=None, help='Filter sessions by property (e.g., session_name=main).')
def status(use_json, ids_only, fast, filter_expr):
	"""List all sessions: name | short-id | process | path"""
	async def _run(connection):
		# Single full sweep + parallel per-session fetches (#300/#301).
		snap = await snapshot(connection)
		app = snap.app

		async def _per_session(session):
			if fast:
				proc = path = ''
				state = await derive_state(app, session)
			else:
				proc, path, state = await asyncio.gather(
					session.async_get_variable('jobName'),
					session.async_get_variable('path'),
					derive_state(app, session),
				)
				proc = strip(proc or '')
				path = strip(path or '')
			return proc, path, state

		results = (await asyncio.gather(*(_per_session(s) for s in snap.sessions))
			if snap.sessions else [])

		sessions = []
		for s, (proc, path, state) in zip(snap.sessions, results):
			sessions.append({
				'session_id': s.session_id,
				'session_name': snap.fresh_names.get(s.session_id, '')
					or strip(s.name or ''),
				'process': proc,
				'path': path,
				'window_id': snap.window_of[s.session_id].window_id,
				'tab_id': snap.tab_of[s.session_id].tab_id,
				'state': state,
			})
		return sessions

	sessions = run_iterm(_run) or []

	if filter_expr:
		key, op, value = parse_filter(filter_expr)
		sessions = [s for s in sessions if match_filter(s, key, op, value)]

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
			click.echo(json.dumps({'window_id': None, 'tab_id': None, 'session_id': None, 'session_name': None}, ensure_ascii=False))
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
@click.option('--json', 'use_json', is_flag=True,
	help='Emit CONTRACT §4 envelope on stdout.')
@ita_command(op='protect')
def protect(session_id, list_only, use_json):
	"""Mark a session as protected — write commands (run, send, key, inject, close)
	will refuse to target it without --force.  Use this to guard the Claude Code
	terminal or any session you don't want accidentally modified.

	Emits a CONTRACT §4 envelope on --json. Plain mode keeps the classic
	stderr 'Protected: <id>' confirmation via the decorator's success line
	(envelope.error=null, no body stdout)."""
	if list_only:
		ids = sorted(get_protected())
		if not use_json:
			if ids:
				for sid in ids:
					click.echo(sid)
			else:
				click.echo("No protected sessions.")
		# Read-only sub-path: the envelope will still fire, but state_*
		# stays None (decorator honours mutator=True default; protect --list
		# simply doesn't mutate, so state fields are legitimately null).
		return {"data": {"protected": ids}, "target": None}
	async def _resolve(connection):
		session = await resolve_session(connection, session_id)
		return session.session_id
	sid = run_iterm(_resolve)
	was_protected = sid in get_protected()
	add_protected(sid)
	if not use_json:
		click.echo(f"Protected: {sid}")
	return {
		"target": {"session": sid},
		"state_before": "protected" if was_protected else "unprotected",
		"state_after": "protected",
		"data": {"session_id": sid},
	}


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


@cli.group()
def session():
	"""Single-session operations (info, ...)."""
	pass


@session.command('info')
@click.option('-s', '--session', 'session_id', default=None,
	help='Session to inspect (name, UUID, or 8+ char UUID prefix).')
@click.option('--json', 'use_json', is_flag=True)
def session_info(session_id, use_json):
	"""Dump full metadata for a single session (#148).

	Cheaper than `ita status --json | jq select(...)` — one session, no scan."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		target = await resolve_session(connection, session_id)
		# Locate containing window/tab (Session doesn't expose a back-ref reliably)
		window_id = None
		tab_id = None
		for w in app.terminal_windows:
			for t in w.tabs:
				for s in t.sessions:
					if s.session_id == target.session_id:
						window_id = w.window_id
						tab_id = t.tab_id
						break
		# Current focused session, for is_current
		current_sid = None
		cw = app.current_terminal_window
		if cw and cw.current_tab and cw.current_tab.current_session:
			current_sid = cw.current_tab.current_session.session_id
		# Variables
		proc = strip(await target.async_get_variable('jobName') or '')
		path = strip(await target.async_get_variable('path') or '')
		profile = strip(await target.async_get_variable('profileName') or '')
		shell_int_ver = await target.async_get_variable('user.iterm2_shell_integration_version')
		# Grid size
		try:
			cols = target.grid_size.width
			rows = target.grid_size.height
		except Exception:
			cols = rows = None
		# Broadcast-domain membership: list of member session_ids per domain
		# the target participates in.
		await app.async_refresh_broadcast_domains()
		broadcast_domains = []
		for d in app.broadcast_domains:
			member_ids = [s.session_id for s in d.sessions]
			if target.session_id in member_ids:
				broadcast_domains.append(member_ids)
		# tmux linkage (via containing tab)
		tmux_window_id = None
		if tab_id:
			t = app.get_tab_by_id(tab_id)
			if t is not None:
				tmux_window_id = t.tmux_window_id
		state = await derive_state(app, target)
		return {
			'session_id': target.session_id,
			'name': strip(target.name or ''),
			'process': proc,
			'path': path,
			'profile': profile,
			'window_id': window_id,
			'tab_id': tab_id,
			'cols': cols,
			'rows': rows,
			'protected': target.session_id in get_protected(),
			'shell_integration': bool(shell_int_ver),
			'tmux_window_id': tmux_window_id,
			'is_current': target.session_id == current_sid,
			'broadcast_domains': broadcast_domains,
			'state': state,
		}

	info = run_iterm(_run)
	if use_json:
		click.echo(json.dumps(info, indent=2, ensure_ascii=False))
		return
	# Plain text: aligned key: value pairs
	order = [
		'session_id', 'name', 'process', 'path', 'profile',
		'window_id', 'tab_id', 'cols', 'rows',
		'protected', 'shell_integration', 'tmux_window_id',
		'is_current', 'broadcast_domains',
	]
	width = max(len(k) for k in order)
	for k in order:
		v = info.get(k)
		if k == 'broadcast_domains':
			v = 'none' if not v else '; '.join(','.join(ids) for ids in v)
		click.echo(f"{k.ljust(width)} : {v}")
