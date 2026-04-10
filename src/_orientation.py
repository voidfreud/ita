# src/_orientation.py
"""Orientation commands: status, focus, version, use."""
import json
import click
import iterm2
from _core import cli, run_iterm, strip, get_sticky, set_sticky, clear_sticky


@cli.command()
@click.option('--json', 'use_json', is_flag=True)
def status(use_json):
    """List all sessions: id | name | process | path | current*"""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        current = get_sticky()
        sessions = []
        for window in app.windows:
            for tab in window.tabs:
                for session in tab.sessions:
                    sessions.append({
                        'id': session.session_id,
                        'name': strip(session.name or ''),
                        'process': strip(await session.async_get_variable('jobName') or ''),
                        'path': strip(await session.async_get_variable('path') or ''),
                        'current': session.session_id == current,
                        'window_id': window.window_id,
                        'tab_id': tab.tab_id,
                    })
        return sessions

    sessions = run_iterm(_run)

    if use_json:
        click.echo(json.dumps(sessions, indent=2))
        return

    for s in sessions:
        marker = '*' if s['current'] else ' '
        sid = s['id'][:8]
        name = s['name'][:20].ljust(20)
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
        click.echo("No focused window")
        return
    if use_json:
        click.echo(json.dumps(result, indent=2))
    else:
        click.echo(f"window:  {result['window_id']}")
        click.echo(f"tab:     {result['tab_id']}")
        click.echo(f"session: {result['session_id']}  ({result['session_name']})")


@cli.command()
def version():
    """Show iTerm2 app version."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        return await app.async_get_variable('iterm2.version')
    click.echo(run_iterm(_run) or 'unknown')


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
    set_sticky(session_id)
    click.echo(f"Target set: {session_id}")
