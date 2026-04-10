# src/_tmux.py
"""tmux -CC integration commands."""
import asyncio
import click
import iterm2
from _core import cli, run_iterm, resolve_session


@cli.group()
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
		session = await resolve_session(connection, session_id)
		await session.async_send_text(cmd + '\n')
		await asyncio.sleep(2)  # allow connection to establish
		conns = await iterm2.async_list_tmux_connections(connection)
		return [c.connection_id for c in conns]

	for cid in run_iterm(_run):
		click.echo(cid)


@tmux.command('connections')
def tmux_connections():
	"""List active tmux -CC connections."""
	async def _run(connection):
		conns = await iterm2.async_list_tmux_connections(connection)
		return [{'id': c.connection_id, 'session': c.owning_session_id} for c in conns]
	for c in run_iterm(_run):
		click.echo(f"{c['id']}  session={c['session']}")


@tmux.command('windows')
def tmux_windows():
	"""List tmux windows mapped to iTerm2 tab IDs."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		return [
			{'tmux_window_id': tab.tmux_window_id,
			 'tab_id': tab.tab_id,
			 'connection_id': tab.tmux_connection_id}
			for window in app.windows
			for tab in window.tabs
			if tab.tmux_window_id
		]
	for w in run_iterm(_run):
		click.echo(f"@{w['tmux_window_id']}  tab={w['tab_id']}  conn={w['connection_id']}")


@tmux.command('cmd')
@click.argument('command')
def tmux_cmd(command):
	"""Send tmux protocol command. Returns output."""
	async def _run(connection):
		conns = await iterm2.async_list_tmux_connections(connection)
		if not conns:
			raise click.ClickException("No tmux connection. Run 'ita tmux start' first.")
		return await iterm2.async_send_tmux_command(
			connection, conns[0].connection_id, command)
	result = run_iterm(_run)
	if result:
		click.echo(result)


@tmux.command('visible')
@click.argument('window_ref')
@click.argument('state', type=click.Choice(['on', 'off']))
def tmux_visible(window_ref, state):
	"""Show (on) or hide (off) a tmux window's iTerm2 tab. Use @1, @2, etc."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		wid = window_ref.lstrip('@')
		for window in app.windows:
			for tab in window.tabs:
				if tab.tmux_window_id == wid:
					if state == 'off':
						await tab.async_close(force=True)
					return
	run_iterm(_run)
