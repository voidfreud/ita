# src/_session.py
"""Session lifecycle commands: new, close, activate, name, restart, resize, clear, capture."""
from pathlib import Path
import click
import iterm2
from _core import cli, run_iterm, resolve_session, strip, set_sticky, clear_sticky, get_sticky


@cli.command()
@click.option('--window', 'new_window', is_flag=True, help='Create new window instead of tab')
@click.option('--profile', default=None, help='Profile name')
def new(new_window, profile):
    """Create new tab (or window). Sets sticky target. Returns session ID."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
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
        return session.session_id

    sid = run_iterm(_run)
    set_sticky(sid)
    click.echo(sid)


@cli.command()
@click.option('-s', '--session', 'session_id', default=None)
def close(session_id):
    """Close session. Clears sticky if it was the target."""
    if session_id is not None and not session_id.strip():
        raise click.ClickException("--session cannot be empty")
    was_sticky = session_id == get_sticky() or (not session_id and get_sticky())

    async def _run(connection):
        session = await resolve_session(connection, session_id)
        await session.async_close(force=True)

    run_iterm(_run)
    if was_sticky:
        clear_sticky()


@cli.command()
@click.argument('session_id_arg', metavar='SESSION_ID', required=False)
def activate(session_id_arg):
    """Focus/bring a session to front."""
    async def _run(connection):
        session = await resolve_session(connection, session_id_arg)
        await session.async_activate(select_tab=True, order_window_front=True)
    run_iterm(_run)


@cli.command()
@click.argument('title')
@click.option('-s', '--session', 'session_id', default=None)
def name(title, session_id):
    """Rename session."""
    if not title.strip():
        raise click.ClickException("Name cannot be empty")
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        await session.async_set_name(title)
    run_iterm(_run)


@cli.command()
@click.option('-s', '--session', 'session_id', default=None)
def restart(session_id):
    """Restart session."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        await session.async_restart(only_if_exited=False)
    run_iterm(_run)


@cli.command()
@click.option('--cols', type=int, required=True)
@click.option('--rows', type=int, required=True)
@click.option('-s', '--session', 'session_id', default=None)
def resize(cols, rows, session_id):
    """Resize session pane."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        await session.async_set_grid_size(iterm2.util.Size(cols, rows))
    run_iterm(_run)


@cli.command('clear')
@click.option('-s', '--session', 'session_id', default=None)
def clear_screen(session_id):
    """Clear session screen (Ctrl+L)."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        await session.async_send_text('\x0c')
    run_iterm(_run)


@cli.command()
@click.argument('file', required=False)
@click.option('-s', '--session', 'session_id', default=None)
def capture(file, session_id):
    """Save screen contents to file (or stdout if no file given)."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        contents = await session.async_get_screen_contents()
        lines = []
        for i in range(contents.number_of_lines):
            lines.append(strip(contents.line(i).string))
        while lines and not lines[-1].strip():
            lines.pop()
        return '\n'.join(lines)

    output = run_iterm(_run)
    if file:
        try:
            Path(file).expanduser().write_text(output)
        except (FileNotFoundError, PermissionError, IsADirectoryError) as e:
            raise click.ClickException(f"Cannot write {file}: {e}") from e
        click.echo(f"Saved to {file}")
    else:
        click.echo(output)
