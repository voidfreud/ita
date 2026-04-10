# src/_config.py
"""Config commands: var group, app group, pref group, broadcast group."""
import json
import click
import iterm2
from _core import cli, run_iterm, resolve_session


# ── Variables ─────────────────────────────────────────────────────────────

@cli.group()
def var():
    """Get, set and list variables at session/tab/window/app scope."""
    pass


@var.command('get')
@click.argument('name')
@click.option('--scope', type=click.Choice(['session', 'tab', 'window', 'app']), default='session')
@click.option('-s', '--session', 'session_id', default=None)
def var_get(name, scope, session_id):
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        if scope == 'app':
            return await app.async_get_variable(name)
        elif scope == 'window':
            w = app.current_terminal_window
            return await w.async_get_variable(name) if w else None
        elif scope == 'tab':
            w = app.current_terminal_window
            t = w.current_tab if w else None
            return await t.async_get_variable(name) if t else None
        else:
            session = await resolve_session(connection, session_id)
            return await session.async_get_variable(name)
    result = run_iterm(_run)
    click.echo(str(result or ''))


@var.command('set')
@click.argument('name')
@click.argument('value')
@click.option('--scope', type=click.Choice(['session', 'tab', 'window', 'app']), default='session')
@click.option('-s', '--session', 'session_id', default=None)
def var_set(name, value, scope, session_id):
    """Set a variable. iTerm2 requires custom variables to use the 'user.' prefix;
    it is added automatically if not present."""
    if not name.startswith('user.'):
        name = f'user.{name}'
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        if scope == 'app':
            await app.async_set_variable(name, value)
        elif scope == 'window':
            w = app.current_terminal_window
            if w: await w.async_set_variable(name, value)
        elif scope == 'tab':
            w = app.current_terminal_window
            t = w.current_tab if w else None
            if t: await t.async_set_variable(name, value)
        else:
            session = await resolve_session(connection, session_id)
            await session.async_set_variable(name, value)
    run_iterm(_run)


# ── App control ───────────────────────────────────────────────────────────

@cli.group('app')
def app_group():
    """Control the iTerm2 application."""
    pass


@app_group.command('activate')
def app_activate():
    """Bring iTerm2 to front."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        await app.async_activate(raise_all_windows=True, ignoring_other_apps=True)
    run_iterm(_run)


@app_group.command('hide')
def app_hide():
    """Hide iTerm2."""
    import subprocess
    subprocess.run(['osascript', '-e',
        'tell application "iTerm2" to set miniaturized of every window to true'])


@app_group.command('quit')
def app_quit():
    """Quit iTerm2."""
    import subprocess
    subprocess.run(['osascript', '-e', 'tell application "iTerm2" to quit'])


@app_group.command('theme')
def app_theme():
    """Show current UI theme (light/dark/auto)."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        return await app.async_get_theme()
    click.echo(run_iterm(_run))


# ── Preferences ───────────────────────────────────────────────────────────

@cli.group()
def pref():
    """Read and write iTerm2 preferences."""
    pass


def _resolve_pref_key(key: str):
    """Resolve a string to PreferenceKey enum, or raise ClickException with a useful hint."""
    try:
        return iterm2.PreferenceKey[key]
    except KeyError:
        raise click.ClickException(
            f"Unknown preference key: {key!r}. Use 'ita pref list' to see valid keys."
        )


@pref.command('get')
@click.argument('key')
def pref_get(key):
    async def _run(connection):
        return await iterm2.async_get_preference(connection, _resolve_pref_key(key))
    result = run_iterm(_run)
    if result is not None:
        click.echo(result)


@pref.command('set')
@click.argument('key')
@click.argument('value')
def pref_set(key, value):
    async def _run(connection):
        pref_key = _resolve_pref_key(key)
        for converter in [int, float, lambda x: True if x == 'true' else (False if x == 'false' else None), str]:
            try:
                typed = converter(value)
                if typed is not None:
                    await iterm2.async_set_preference(connection, pref_key, typed)
                    return
            except (ValueError, TypeError):
                continue
    run_iterm(_run)


@pref.command('list')
@click.option('--filter', 'filter_text', default=None)
def pref_list(filter_text):
    async def _run(connection):
        keys = [k for k in dir(iterm2.PreferenceKey) if not k.startswith('_')]
        if filter_text:
            keys = [k for k in keys if filter_text.lower() in k.lower()]
        return keys
    for k in run_iterm(_run):
        click.echo(k)


@pref.command('theme')
def pref_theme():
    """Show current theme tags and dark/light mode."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        return await app.async_get_theme()
    click.echo(run_iterm(_run))


@pref.command('tmux')
@click.argument('property', required=False)
@click.argument('value', required=False)
def pref_tmux(property, value):
    """Get all tmux prefs, or set a specific one."""
    async def _run(connection):
        if property and value:
            typed = int(value) if value.isdigit() else (
                True if value == 'true' else (False if value == 'false' else value))
            await iterm2.async_set_preference(connection, f'TmuxPref{property}', typed)
        else:
            keys = ['OpenTmuxWindowsIn', 'TmuxDashboardLimit',
                    'AutoHideTmuxClientSession', 'UseTmuxProfile']
            return {k: await iterm2.async_get_preference(connection, k) for k in keys}
    result = run_iterm(_run)
    if isinstance(result, dict):
        click.echo(json.dumps(result, indent=2))


# ── Broadcast ─────────────────────────────────────────────────────────────

@cli.group()
def broadcast():
    """Control input broadcasting across panes."""
    pass


@broadcast.command('on')
@click.option('--window', 'window_id', default=None)
def broadcast_on(window_id):
    """Broadcast input to all panes in window."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        w = app.get_window_by_id(window_id) if window_id else app.current_terminal_window
        if not w:
            return
        domain = iterm2.BroadcastDomain()
        for tab in w.tabs:
            for session in tab.sessions:
                domain.add_session(session)
        await iterm2.async_set_broadcast_domains(connection, [domain])
    run_iterm(_run)


@broadcast.command('off')
def broadcast_off():
    """Stop all broadcasting."""
    async def _run(connection):
        await iterm2.async_set_broadcast_domains(connection, [])
    run_iterm(_run)


@broadcast.command('add')
@click.argument('session_ids', nargs=-1, required=True)
def broadcast_add(session_ids):
    """Group sessions into a broadcast domain."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        domain = iterm2.BroadcastDomain()
        for sid in session_ids:
            s = app.get_session_by_id(sid)
            if s:
                domain.add_session(s)
        await iterm2.async_set_broadcast_domains(connection, [domain])
    run_iterm(_run)


@broadcast.command('list')
def broadcast_list():
    """List active broadcast domains."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        await app.async_refresh_broadcast_domains()
        return [[s.session_id for s in d.sessions] for d in app.broadcast_domains]
    for i, domain in enumerate(run_iterm(_run) or []):
        click.echo(f"Domain {i}: {', '.join(domain)}")
