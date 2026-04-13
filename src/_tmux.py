# src/_tmux.py
"""tmux -CC integration commands."""
import asyncio
import click
import iterm2
from _core import cli, run_iterm, resolve_session


class TmuxGroup(click.Group):
	def invoke(self, ctx):
		if ctx.protected_args and ctx.protected_args[0] not in self.list_commands(ctx):
			ctx.protected_args = ['cmd'] + ctx.protected_args
		return super().invoke(ctx)


@cli.group(cls=TmuxGroup)
def tmux():
	"""tmux -CC integration — render tmux windows as native iTerm2 tabs."""
	pass


@tmux.command('start')
@click.option('--attach', is_flag=True, help='Attach to existing tmux session')
@click.option('-s', '--session', 'session_id', default=None)
def tmux_start(attach, session_id):
	"""Bootstrap tmux -CC connection. Returns connection IDs."""
	cmd = 'tmux -CC attach' if attach else 'tmux -CC'

	async def _run(connection):
		# Detect-and-reuse: if a tmux-CC connection already exists, surface it
		# instead of stacking a duplicate (see #177).
		existing = await iterm2.tmux.async_get_tmux_connections(connection)
		if existing:
			click.echo("Reusing existing tmux connection. Run 'ita tmux stop' first to start fresh.", err=True)
			return [c.connection_id for c in existing]
		session = await resolve_session(connection, session_id)
		await session.async_send_text(cmd + '\n')
		# Poll up to 5s for connection to appear (check every 0.5s)
		conns = []
		for _ in range(10):
			await asyncio.sleep(0.5)
			conns = await iterm2.tmux.async_get_tmux_connections(connection)
			if conns:
				break
		if not conns:
			raise click.ClickException("tmux session failed to establish. Verify tmux is installed and the session is accessible.")
		return [c.connection_id for c in conns]

	for cid in (run_iterm(_run) or []):
		click.echo(cid)


@tmux.command('stop')
def tmux_stop():
	"""Cleanly detach all active tmux -CC connections (#177)."""
	async def _run(connection):
		conns = await iterm2.tmux.async_get_tmux_connections(connection)
		if not conns:
			raise click.ClickException("No active tmux connection.")
		closed = []
		for c in conns:
			try:
				await c.async_send_command('detach-client')
				closed.append(c.connection_id)
			except Exception as e:
				click.echo(f"Failed to detach {c.connection_id}: {e}", err=True)
		return closed

	for cid in (run_iterm(_run) or []):
		click.echo(cid)


@tmux.command('connections')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSON array')
def tmux_connections(output_json):
	"""List active tmux -CC connections."""
	async def _run(connection):
		conns = await iterm2.tmux.async_get_tmux_connections(connection)
		return [c.connection_id for c in conns]
	results = run_iterm(_run)
	if not results:
		if output_json:
			click.echo('[]')
		else:
			click.echo("No active tmux connections.")
		return
	if output_json:
		import json
		click.echo(json.dumps([{'id': c} for c in results]))
	else:
		for c in results:
			click.echo(c)


@tmux.command('windows')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSON array')
def tmux_windows(output_json):
	"""List tmux windows mapped to iTerm2 tab IDs."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		rows = []
		for window in app.windows:
			for tab in window.tabs:
				wid = tab.tmux_window_id
				if not wid:
					continue
				# Filter phantom rows: @-1 or any negative window ID
				try:
					if int(wid.lstrip('@')) < 0:
						continue
				except (ValueError, AttributeError):
					continue
				rows.append({'tmux_window_id': wid,
							 'tab_id': tab.tab_id,
							 'connection_id': tab.tmux_connection_id})
		return rows
	rows = run_iterm(_run)
	if output_json:
		import json
		click.echo(json.dumps(rows or []))
	else:
		for w in rows:
			click.echo(f"{w['tmux_window_id']}  tab={w['tab_id']}  conn={w['connection_id']}")


@tmux.command('cmd')
@click.argument('command')
def tmux_cmd(command):
	"""Send tmux protocol command. Returns output."""
	async def _run(connection):
		conns = await iterm2.tmux.async_get_tmux_connections(connection)
		if not conns:
			raise click.ClickException("No active tmux connection. Run 'ita tmux start' first.")
		return await conns[0].async_send_command(command)
	result = run_iterm(_run)
	if result:
		click.echo(result)


@tmux.command('visible')
@click.argument('window_ref')
@click.argument('state', type=click.Choice(['on', 'off']))
def tmux_visible(window_ref, state):
	"""Show (on) or hide (off) a tmux window's iTerm2 tab. Use @1, @2, etc."""
	async def _run(connection):
		# Normalise: tmux_window_id includes '@', so match with prefix
		wid = window_ref if window_ref.startswith('@') else f'@{window_ref}'
		conns = await iterm2.tmux.async_get_tmux_connections(connection)
		if not conns:
			raise click.ClickException("No active tmux connection. Run 'ita tmux start' first.")
		visible = state == 'on'
		await conns[0].async_set_tmux_window_visible(wid, visible)
	run_iterm(_run)


@tmux.command('detach')
@click.argument('session_id', required=False)
def tmux_detach(session_id):
	"""Detach tmux client from session."""
	async def _run(connection):
		conns = await iterm2.tmux.async_get_tmux_connections(connection)
		if not conns:
			raise click.ClickException("No active tmux connection.")
		await conns[0].async_send_command('detach-client')
	run_iterm(_run)


@tmux.command('kill-session')
@click.argument('session_id', required=False)
def tmux_kill_session(session_id):
	"""Kill a tmux session."""
	async def _run(connection):
		conns = await iterm2.tmux.async_get_tmux_connections(connection)
		if not conns:
			raise click.ClickException("No active tmux connection.")
		cmd = f'kill-session -t {session_id}' if session_id else 'kill-session'
		await conns[0].async_send_command(cmd)
	run_iterm(_run)
