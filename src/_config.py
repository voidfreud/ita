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


# Flat set of all known iTerm2 built-in variable names (unqualified) so that
# var get/set can skip the automatic 'user.' prefix for built-ins.
_BUILTIN_VAR_NAMES = frozenset(
	name
	for names in (
		# Session-scope builtins
		['autoLogId', 'autoName', 'badge', 'bundleId', 'columns', 'rows',
		 'creationTimeString', 'hostname', 'id', 'jobName', 'jobPid',
		 'lastCommand', 'name', 'path', 'presentationName', 'pwd',
		 'processTitle', 'sessionId', 'terminalIconName', 'tty',
		 'tmuxPaneTitle', 'tmuxRole', 'tmuxWindowTitle', 'username'],
		# Tab-scope builtins
		['title', 'tabTitle'],
		# Window-scope builtins
		['frame', 'style', 'number'],
		# App-scope builtins
		['effectiveTheme', 'localhostName', 'pid', 'termid', 'profileName'],
	)
	for name in names
)


@var.command('get')
@click.argument('name')
@click.option('--scope', type=click.Choice(['session', 'tab', 'window', 'app']), default='session')
@click.option('-s', '--session', 'session_id', default=None)
def var_get(name, scope, session_id):
    if not name.startswith('user.') and '.' not in name and name not in _BUILTIN_VAR_NAMES:
        name = f'user.{name}'
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
    if not name.strip():
        raise click.ClickException("Variable name is required")
    if not name.startswith('user.') and '.' not in name and name not in _BUILTIN_VAR_NAMES:
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


# Well-known iTerm2 built-in variable names per scope. iTerm2's Python API has no
# "list all variables" call, so we probe a known set and print the non-empty ones.
# Custom variables (user.*) cannot be enumerated via the API — only those set in
# the current ita invocation are observable, which is why this lists built-ins only.
_KNOWN_VARS = {
    'session': [
        'autoLogId', 'autoName', 'badge', 'bundleId', 'columns', 'rows',
        'creationTimeString', 'hostname', 'id', 'jobName', 'jobPid',
        'lastCommand', 'name', 'path', 'presentationName', 'pwd',
        'processTitle', 'sessionId', 'terminalIconName', 'tty',
        'tmuxPaneTitle', 'tmuxRole', 'tmuxWindowTitle', 'username',
    ],
    'tab': ['id', 'tmuxWindowTitle', 'title', 'tabTitle'],
    'window': [
        'id', 'frame', 'currentTab.tmuxWindowTitle', 'style', 'number',
    ],
    'app': [
        'effectiveTheme', 'localhostName', 'pid', 'currentTab.currentSession.name',
    ],
}


@var.command('list')
@click.option('--scope', type=click.Choice(['session', 'tab', 'window', 'app']),
              default=None, help='Limit to one scope (default: all scopes).')
@click.option('-s', '--session', 'session_id', default=None)
@click.option('--json', 'use_json', is_flag=True)
def var_list(scope, session_id, use_json):
    """List variables by probing well-known iTerm2 built-ins. iTerm2's API has
    no enumeration primitive, so custom 'user.*' variables are not discoverable."""
    scopes = [scope] if scope else ['session', 'tab', 'window', 'app']

    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        out = {}
        for sc in scopes:
            target = None
            if sc == 'app':
                target = app
            elif sc == 'window':
                target = app.current_terminal_window
            elif sc == 'tab':
                w = app.current_terminal_window
                target = w.current_tab if w else None
            else:
                try:
                    target = await resolve_session(connection, session_id)
                except click.ClickException:
                    target = None
            scope_vals = {}
            if target is not None:
                for name in _KNOWN_VARS[sc]:
                    try:
                        val = await target.async_get_variable(name)
                    except Exception:
                        val = None
                    if val not in (None, ''):
                        scope_vals[name] = val
            out[sc] = scope_vals
        return out

    result = run_iterm(_run) or {}
    if use_json:
        click.echo(json.dumps(result, indent=2, default=str))
        return
    for sc in scopes:
        vals = result.get(sc, {})
        if not vals:
            continue
        if not scope:
            click.echo(f"# {sc}")
        for k, v in vals.items():
            click.echo(f"{k}={v}")


# ── App control ───────────────────────────────────────────────────────────

@cli.group('app')
def app_group():
    """Control the iTerm2 application."""
    pass


@app_group.command('version')
def app_version():
    """Show iTerm2 application version."""
    import subprocess
    result = subprocess.run(
        ['osascript', '-e', 'tell application "iTerm2" to get version'],
        capture_output=True, text=True)
    click.echo(result.stdout.strip() or 'unknown')


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
    result = run_iterm(_run)
    if isinstance(result, (list, tuple)):
        click.echo(' '.join(str(x) for x in result))
    else:
        click.echo(result or '')


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
        valid = sorted(k for k in dir(iterm2.PreferenceKey) if not k.startswith('_'))[:10]
        raise click.ClickException(
            f"Unknown preference key: {key!r}. "
            f"Run 'ita pref list' to see all valid keys. Examples: {', '.join(valid)}."
        )


@pref.command('get')
@click.argument('key')
def pref_get(key):
    async def _run(connection):
        return await iterm2.async_get_preference(connection, _resolve_pref_key(key))
    result = run_iterm(_run)
    if result is not None:
        # iTerm2 returns Python bool or int 1/0 for boolean prefs
        if isinstance(result, bool) or (isinstance(result, int) and result in (0, 1)):
            click.echo('true' if result else 'false')
        else:
            click.echo(result)


def _coerce_pref_value(value: str):
    """Coerce a string value to int, bool, or string for preference storage."""
    # Bool check first (before int, since 0/1 are valid ints)
    low = value.lower()
    if low == 'true':
        return True
    if low == 'false':
        return False
    # Try int, then fall back to string
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


@pref.command('set')
@click.argument('key')
@click.argument('value')
def pref_set(key, value):
    async def _run(connection):
        pref_key = _resolve_pref_key(key)
        typed = _coerce_pref_value(value)
        await iterm2.async_set_preference(connection, pref_key, typed)
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
    result = run_iterm(_run)
    if isinstance(result, (list, tuple)):
        click.echo(' '.join(str(x) for x in result))
    else:
        click.echo(result or '')


@pref.command('tmux')
@click.argument('key', required=False)
@click.argument('value', required=False)
def pref_tmux(key, value):
    """Get all tmux prefs, or set a specific one.
    Key is a PreferenceKey enum name (e.g. OPEN_TMUX_WINDOWS_IN)."""
    async def _run(connection):
        if key and value:
            pref_key = _resolve_pref_key(key)
            typed = int(value) if value.isdigit() else (
                True if value == 'true' else (False if value == 'false' else value))
            await iterm2.async_set_preference(connection, pref_key, typed)
        else:
            keys = ['OPEN_TMUX_WINDOWS_IN', 'TMUX_DASHBOARD_LIMIT',
                    'AUTO_HIDE_TMUX_CLIENT_SESSION', 'USE_TMUX_PROFILE']
            return {k: await iterm2.async_get_preference(connection, _resolve_pref_key(k)) for k in keys}
    result = run_iterm(_run)
    if isinstance(result, dict):
        click.echo(json.dumps(result, indent=2))


# ── Broadcast ─────────────────────────────────────────────────────────────

@cli.group()
def broadcast():
    """Control input broadcasting across panes."""
    pass


@broadcast.command('on')
@click.option('-s', '--session', 'session_id', default=None)
@click.option('--window', 'window_id', default=None)
def broadcast_on(session_id, window_id):
    """Broadcast input to all panes in window."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        if session_id:
            session = await resolve_session(connection, session_id)
            domain = iterm2.BroadcastDomain()
            domain.add_session(session)
            await iterm2.async_set_broadcast_domains(connection, [domain])
            return
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
    # Deduplicate while preserving order
    seen = set()
    unique_ids = []
    for sid in session_ids:
        if sid in seen:
            raise click.ClickException(f"Duplicate session ID: {sid}")
        seen.add(sid)
        unique_ids.append(sid)
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        domain = iterm2.BroadcastDomain()
        for sid in unique_ids:
            s = app.get_session_by_id(sid)
            if not s:
                raise click.ClickException(
                    f"Session {sid!r} not found. Run 'ita status' to list sessions.")
            domain.add_session(s)
        await iterm2.async_set_broadcast_domains(connection, [domain])
    run_iterm(_run)


@broadcast.command('set')
@click.argument('domains', nargs=-1, required=True)
def broadcast_set(domains):
    """Set all broadcast domains atomically. Each arg is a comma-separated
    list of session IDs forming one domain. Replaces any existing domains."""
    parsed = []
    for d in domains:
        ids = [sid.strip() for sid in d.split(',') if sid.strip()]
        if not ids:
            raise click.ClickException(f"Empty broadcast domain: {d!r}")
        parsed.append(ids)
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        built = []
        for ids in parsed:
            dom = iterm2.BroadcastDomain()
            for sid in ids:
                s = app.get_session_by_id(sid)
                if not s:
                    raise click.ClickException(
                        f"Session {sid!r} not found. Run 'ita status' to list sessions.")
                dom.add_session(s)
            built.append(dom)
        await iterm2.async_set_broadcast_domains(connection, built)
    run_iterm(_run)


@broadcast.command('list')
@click.option('--json', 'use_json', is_flag=True)
def broadcast_list(use_json):
    """List active broadcast domains."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        await app.async_refresh_broadcast_domains()
        return [
            [
                {'session_id': s.session_id, 'session_name': (s.name or '')}
                for s in d.sessions
            ]
            for d in app.broadcast_domains
        ]
    domains = run_iterm(_run) or []
    if use_json:
        click.echo(json.dumps(domains, indent=2))
        return
    if not domains:
        click.echo("No broadcast domains.")
        return
    for i, domain in enumerate(domains):
        click.echo(f"Domain {i} ({len(domain)} session{'s' if len(domain) != 1 else ''}):")
        if not domain:
            click.echo("  (empty)")
            continue
        for member in domain:
            name = member['session_name'] or '(unnamed)'
            click.echo(f"  {member['session_id']}  {name}")
