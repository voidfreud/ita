# src/_session.py
"""Session lifecycle commands: new, close, activate, name, restart, resize, clear, capture."""
from pathlib import Path
import re
import click
import iterm2
from _core import cli, run_iterm, resolve_session, strip, read_session_lines, check_protected, _all_sessions

_SENTINEL_RE = re.compile(r'^: ita-[0-9a-f]+;')


@cli.command()
@click.option('--window', 'new_window', is_flag=True, help='Create new window instead of tab')
@click.option('--profile', default=None, help='Profile name')
@click.option('--name', 'session_name', default=None, help='Name for the new session')
@click.option('--reuse', is_flag=True, help='If --name exists, return existing session instead of error')
def new(new_window, profile, session_name, reuse):
	"""Create new tab (or window). Returns name and session ID."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		all_sess = _all_sessions(app)
		existing_names = {s.name for s in all_sess if s.name}
		# If --name given, check uniqueness / reuse
		if session_name:
			for s in all_sess:
				if s.name == session_name:
					if reuse:
						return s.name, s.session_id
					raise click.ClickException(
						f"session name {session_name!r} already exists. "
						f"Use --reuse to return the existing session.")
		try:
			if new_window:
				window = await iterm2.Window.async_create(connection, profile=profile)
				session = window.current_tab.current_session
			else:
				window = app.current_terminal_window
				if not window:
					window = await iterm2.Window.async_create(connection, profile=profile)
					session = window.current_tab.current_session
				else:
					tab = await window.async_create_tab(profile=profile)
					session = tab.current_session
		except Exception as e:
			if 'INVALID_PROFILE_NAME' in str(e):
				raise click.ClickException(f"Profile not found: {profile!r}") from e
			raise
		# Set session name
		name = session_name
		if not name:
			# Auto-name: s1, s2, s3, ...
			i = 1
			while f's{i}' in existing_names:
				i += 1
			name = f's{i}'
		await session.async_set_name(name)
		return name, session.session_id

	name, sid = run_iterm(_run)
	click.echo(f"{name}\t{sid}")


@cli.command()
@click.option('-s', '--session', 'session_id', default=None)
@click.option('-q', '--quiet', is_flag=True, help='Suppress confirmation message')
@click.option('--dry-run', is_flag=True, help='Print what would be closed without doing it')
@click.option('--force', is_flag=True, help='Override protected-session guard.')
def close(session_id, quiet, dry_run, force):
    """Close session."""
    if session_id is not None and not session_id.strip():
        raise click.ClickException("--session cannot be empty")

    closed_id = None
    async def _run(connection):
        nonlocal closed_id
        session = await resolve_session(connection, session_id)
        check_protected(session.session_id, force=force)
        closed_id = session.session_id
        if not dry_run:
            await session.async_close(force=True)

    run_iterm(_run)
    if closed_id:
        if dry_run:
            click.echo(f"Would close: {closed_id}")
        elif not quiet:
            click.echo(f"Closed: {closed_id}", err=True)
        else:
            click.echo(closed_id)


@cli.command()
@click.argument('session_id_pos', metavar='SESSION_ID', required=False, default=None)
@click.option('-s', '--session', 'session_id_opt', default=None, help='Session to activate')
def activate(session_id_pos, session_id_opt):
    """Focus/bring a session to front."""
    # Flag takes precedence; positional kept for backwards compat
    session_id = session_id_opt or session_id_pos
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        await session.async_activate(select_tab=True, order_window_front=True)
    run_iterm(_run)


@cli.command()
@click.argument('title')
@click.option('-s', '--session', 'session_id', default=None)
@click.option('-q', '--quiet', is_flag=True, help='Suppress confirmation message')
def name(title, session_id, quiet):
    """Rename session."""
    if not title.strip():
        raise click.ClickException("Name cannot be empty")
    renamed_id = None
    async def _run(connection):
        nonlocal renamed_id
        session = await resolve_session(connection, session_id)
        renamed_id = session.session_id
        await session.async_set_name(title)
    run_iterm(_run)
    # SS10: print acted-on session ID
    if not quiet:
        click.echo(f"Named: {renamed_id}")
    else:
        click.echo(renamed_id)


@cli.command()
@click.option('-s', '--session', 'session_id', default=None)
@click.option('-q', '--quiet', is_flag=True, help='Suppress confirmation message')
def restart(session_id, quiet):
    """Restart session. Prints new session ID (may differ after restart)."""
    old_id = None
    async def _run(connection):
        nonlocal old_id
        import asyncio
        app = await iterm2.async_get_app(connection)
        session = await resolve_session(connection, session_id)
        old_id = session.session_id
        tab_id = session.tab.tab_id if session.tab else None
        await session.async_restart(only_if_exited=False)
        # Wait briefly for iTerm2 to register the new session object
        await asyncio.sleep(0.5)
        # Re-fetch app state and find the replacement session in the same tab
        app2 = await iterm2.async_get_app(connection)
        if tab_id:
            for w in app2.windows:
                for t in w.tabs:
                    if t.tab_id == tab_id and t.current_session:
                        return t.current_session.session_id
        return old_id

    new_sid = run_iterm(_run)
    if new_sid:
        if not quiet:
            click.echo(f"Restarted: {new_sid}")
        else:
            click.echo(new_sid)


@cli.command()
@click.option('--cols', type=click.IntRange(min=1), required=True)
@click.option('--rows', type=click.IntRange(min=1), required=True)
@click.option('-s', '--session', 'session_id', default=None)
@click.option('-q', '--quiet', is_flag=True, help='Suppress confirmation message')
def resize(cols, rows, session_id, quiet):
    """Resize session pane."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        size = iterm2.util.Size(cols, rows)
        # async_set_grid_size works for single-pane tabs but returns IMPOSSIBLE
        # when split panes are present. Fall back to the tab-layout path, which
        # honours each session's preferred_size and recalculates the whole tab.
        try:
            await session.async_set_grid_size(size)
        except Exception as e:
            if 'IMPOSSIBLE' not in str(e):
                raise
            try:
                session.preferred_size = size
                tab = session.tab
                if tab is None:
                    raise click.ClickException(
                        "Cannot resize: session has no containing tab (buried?).")
                await tab.async_update_layout()
            except click.ClickException:
                raise
            except Exception as e:
                raise click.ClickException(
                    f"Cannot resize: {e} (fullscreen or tmux-CC windows cannot be resized via API)"
                ) from e
        import asyncio
        await asyncio.sleep(0.1)
        actual_cols = session.grid_size.width
        actual_rows = session.grid_size.height
        if actual_cols != cols or actual_rows != rows:
            if not quiet:
                click.echo(
                    f"warning: requested {cols}x{rows} but got {actual_cols}x{actual_rows}",
                    err=True)
        elif not quiet:
            click.echo(f"Resized: {cols}x{rows}")
        return session.session_id
    resized_id = run_iterm(_run)
    if resized_id and quiet:
        click.echo(resized_id)


@cli.command('clear')
@click.option('-s', '--session', 'session_id', default=None)
@click.option('-q', '--quiet', is_flag=True, help='Suppress confirmation message')
def clear_screen(session_id, quiet):
    """Clear session screen (Ctrl+L)."""
    cleared_id = None
    async def _run(connection):
        nonlocal cleared_id
        session = await resolve_session(connection, session_id)
        cleared_id = session.session_id
        await session.async_send_text('\x0c')
    run_iterm(_run)
    if not quiet:
        click.echo(cleared_id)


@cli.command()
@click.argument('file', required=False)
@click.option('-n', '--lines', 'lines', default=None, type=click.IntRange(min=1),
              help='Limit output to last N lines (after filtering).')
@click.option('--scrollback', 'scrollback', is_flag=True, default=False,
              help='Include scrollback history (full session output), not just the visible grid.')
@click.option('-s', '--session', 'session_id', default=None)
def capture(file, lines, scrollback, session_id):
    """Save screen contents to file (or stdout if no file given).

    By default only the currently visible grid is captured. Pass --scrollback
    to include the full scrollback buffer — required when a command produced
    more output than fits on screen."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        result = await read_session_lines(session, include_scrollback=scrollback)
        result = [l for l in result if not _SENTINEL_RE.match(l)]
        return result

    result = run_iterm(_run)
    if lines is not None:
        result = result[-lines:]
    output = '\n'.join(result)
    if not output:
        output = '\n'
    if file:
        try:
            Path(file).expanduser().write_text(output)
        except (FileNotFoundError, PermissionError, IsADirectoryError) as e:
            raise click.ClickException(f"Cannot write {file}: {e}") from e
        click.echo(f"Saved to {file}")
    else:
        click.echo(output)
