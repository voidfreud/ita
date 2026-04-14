"""`ita coprocess` group — attach a subprocess to session I/O.

Split out of `_events.py` (#372). Pure CLI wiring around iTerm2's
async_run_coprocess / async_get_coprocess / async_stop_coprocess.
"""
import click
import iterm2
from ._core import cli, run_iterm, resolve_session


@cli.group()
def coprocess():
	"""Attach a subprocess to session I/O."""
	pass


@coprocess.command('start')
@click.argument('cmd')
@click.option('-s', '--session', 'session_id', default=None)
def coprocess_start(cmd, session_id):
	"""Start coprocess connected to session stdin/stdout."""
	async def _run(connection):
		session = await resolve_session(connection, session_id)
		existing = await session.async_get_coprocess()
		if existing:
			raise click.ClickException("A coprocess is already attached to this session. Stop it first with 'ita coprocess stop'.")
		await session.async_run_coprocess(cmd)
		coprocess = await session.async_get_coprocess()
		if coprocess and hasattr(coprocess, 'pid'):
			return f"PID {coprocess.pid}"
		return "Coprocess started"
	result = run_iterm(_run)
	click.echo(result)


@coprocess.command('stop')
@click.option('-s', '--session', 'session_id', default=None)
def coprocess_stop(session_id):
	"""Stop running coprocess."""
	async def _run(connection):
		session = await resolve_session(connection, session_id)
		existing = await session.async_get_coprocess()
		if not existing:
			raise click.ClickException("No coprocess is attached to this session.")
		await session.async_stop_coprocess()
	run_iterm(_run)


@coprocess.command('list')
def coprocess_list():
	"""List running coprocesses across all sessions."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		found = []
		for window in app.terminal_windows:
			for tab in window.tabs:
				for session in tab.sessions:
					cp = await session.async_get_coprocess()
					if cp:
						pid_str = str(cp.pid) if hasattr(cp, 'pid') else "unknown"
						cmd_str = str(cp.command) if hasattr(cp, 'command') else "unknown"
						found.append(f"{session.session_id} (PID {pid_str}): {cmd_str}")
		if not found:
			return "No running coprocesses"
		return "\n".join(found)
	result = run_iterm(_run)
	click.echo(result)
