# src/_pane.py
"""Pane commands: split, navigate, move, swap."""
import click
import iterm2
from _core import cli, run_iterm, resolve_session, set_sticky

DIRECTION_MAP = {
	'right': iterm2.NavigationDirection.RIGHT,
	'left': iterm2.NavigationDirection.LEFT,
	'above': iterm2.NavigationDirection.ABOVE,
	'below': iterm2.NavigationDirection.BELOW,
}


@cli.command()
@click.option('-v', '--vertical', 'split_dir', flag_value='vertical', help='Side-by-side split')
@click.option('-h', '--horizontal', 'split_dir', flag_value='horizontal', help='Top-bottom split (default)')
@click.option('--profile', default=None)
@click.option('-s', '--session', 'session_id', default=None)
def split(split_dir, profile, session_id):
	"""Split current pane. New pane becomes sticky target."""
	vertical = split_dir == 'vertical'
	async def _run(connection):
		session = await resolve_session(connection, session_id)
		try:
			new_session = await session.async_split_pane(vertical=vertical, profile=profile)
		except Exception as e:
			if 'INVALID_PROFILE_NAME' in str(e):
				raise click.ClickException(f"Profile not found: {profile!r}") from e
			raise
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
@click.option('-s', '--session', 'session_id', default=None, help='Session to move (default: sticky/focused)')
@click.option('-w', '--window', 'window_id', required=True, help='Destination window ID')
@click.option('--vertical', is_flag=True)
@click.option('--tab', 'tab_id', default=None, help='Target tab in destination window')
@click.option('--pane', 'pane_id', default=None, help='Target pane (session) to split next to')
def move(session_id, window_id, vertical, tab_id, pane_id):
	"""Move a pane to a different window. Use -w WINDOW_ID (required)."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		session = await resolve_session(connection, session_id)
		dest_window = app.get_window_by_id(window_id)
		if not dest_window:
			raise click.ClickException(f"Window {window_id!r} not found")
		cur_window, _ = app.get_window_and_tab_for_session(session)
		if cur_window and cur_window.window_id == window_id:
			raise click.ClickException(f"Session is already in window {window_id}")
		# Resolve destination tab
		if tab_id:
			dest_tab = app.get_tab_by_id(tab_id)
			if not dest_tab:
				raise click.ClickException(f"Tab {tab_id!r} not found")
		else:
			dest_tab = dest_window.current_tab
		if not dest_tab:
			raise click.ClickException("Destination window has no tabs")
		# Resolve destination pane within the tab
		if pane_id:
			dest_session = app.get_session_by_id(pane_id)
			if not dest_session:
				raise click.ClickException(f"Pane session {pane_id!r} not found")
		else:
			dest_session = dest_tab.current_session
			if not dest_session:
				raise click.ClickException("Destination tab has no active session")
		await app.async_move_session(session, dest_session, split_vertically=vertical, before=False)
	run_iterm(_run)


@cli.command()
@click.argument('session_a', metavar='SESSION_A')
@click.argument('session_b', metavar='SESSION_B')
def swap(session_a, session_b):
	"""Swap two panes."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		sess_a = app.get_session_by_id(session_a)
		sess_b = app.get_session_by_id(session_b)
		if not sess_a:
			raise click.ClickException(f"Session {session_a!r} not found")
		if not sess_b:
			raise click.ClickException(f"Session {session_b!r} not found")
		await app.async_swap_sessions(sess_a, sess_b)
	run_iterm(_run)
