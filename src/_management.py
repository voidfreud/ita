# src/_management.py
"""Management commands: save/restore, profile group, presets, theme."""
import json
import click
import iterm2
from _core import cli, run_iterm, resolve_session

THEME_SHORTCUTS = {
    'red': 'Red Alert',
    'green': 'Solarized Dark',
    'dark': 'Solarized Dark',
    'light': 'Solarized Light',
}


# ── Arrangements ──────────────────────────────────────────────────────────

@cli.command()
@click.argument('name')
@click.option('--window', 'window_only', is_flag=True, help='Save current window only')
def save(name, window_only):
    """Save current layout as named arrangement."""
    if not name.strip():
        raise click.ClickException("Name cannot be empty")
    async def _run(connection):
        if window_only:
            app = await iterm2.async_get_app(connection)
            w = app.current_terminal_window
            if w:
                await w.async_save_window_as_arrangement(name)
        else:
            await iterm2.Arrangement.async_save(connection, name)
    run_iterm(_run)
    click.echo(f"Saved: {name}")


@cli.command()
@click.argument('name')
def restore(name):
    """Restore named arrangement."""
    async def _run(connection):
        try:
            await iterm2.Arrangement.async_restore(connection, name)
        except Exception as e:
            msg = str(e)
            if 'ARRANGEMENT_NOT_FOUND' in msg or 'NOT_FOUND' in msg:
                raise click.ClickException(f"Arrangement {name!r} not found")
            raise click.ClickException(f"Failed to restore {name!r}: {msg}") from e
    run_iterm(_run)
    click.echo(f"Restored: {name}")


@cli.command()
def layouts():
    """List all saved arrangements."""
    async def _run(connection):
        return await iterm2.Arrangement.async_list(connection)
    for n in (run_iterm(_run) or []):
        if n and n.strip():
            click.echo(n)


# ── Profiles ──────────────────────────────────────────────────────────────

@cli.group()
def profile():
    """Manage profiles."""
    pass


@profile.command('list')
def profile_list():
    """List all profiles."""
    async def _run(connection):
        profiles = await iterm2.PartialProfile.async_query(connection)
        return [(p.name, p.guid) for p in profiles]
    for name, guid in run_iterm(_run):
        click.echo(f"{guid}  {name}")


@profile.command('show')
@click.argument('name', required=False)
@click.option('-s', '--session', 'session_id', default=None)
def profile_show(name, session_id):
    """Show profile details."""
    async def _run(connection):
        if session_id or not name:
            session = await resolve_session(connection, session_id)
            p = await session.async_get_profile()
        else:
            profiles = await iterm2.PartialProfile.async_query(connection)
            p = next((x for x in profiles if x.name == name), None)
            if not p:
                raise click.ClickException(f"Profile {name!r} not found")
        # Collect a useful subset of properties
        result = {'name': p.name, 'guid': p.guid}
        for attr in ('foreground_color', 'background_color', 'cursor_color',
                     'normal_font', 'non_ascii_font', 'use_non_ascii_font',
                     'horizontal_spacing', 'vertical_spacing', 'cursor_type',
                     'transparency', 'blur', 'badge_text', 'command',
                     'working_directory', 'initial_text'):
            try:
                val = getattr(p, attr, None)
                if val is not None:
                    # Some props are objects (Color) — stringify
                    result[attr] = str(val) if not isinstance(val, (str, int, float, bool)) else val
            except Exception:
                pass
        return result
    click.echo(json.dumps(run_iterm(_run), indent=2, default=str))


@profile.command('apply')
@click.argument('name')
@click.option('-s', '--session', 'session_id', default=None)
def profile_apply(name, session_id):
    """Apply named profile to session."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        profiles = await iterm2.PartialProfile.async_query(connection)
        p = next((x for x in profiles if x.name == name), None)
        if not p:
            raise click.ClickException(f"Profile {name!r} not found")
        await session.async_set_profile(p)
    run_iterm(_run)


@profile.command('set')
@click.argument('property_name')
@click.argument('value')
@click.option('-s', '--session', 'session_id', default=None)
def profile_set(property_name, value, session_id):
    """Set a profile property on session."""
    if not property_name.strip():
        raise click.ClickException("Profile property name cannot be empty")
    change = iterm2.LocalWriteOnlyProfile()
    if not hasattr(change, property_name):
        raise click.ClickException(
            f"Unknown profile property: {property_name!r}. "
            "See iterm2.LocalWriteOnlyProfile for valid setters.")
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        setattr(change, property_name, value)
        await session.async_set_profile_properties(change)
    run_iterm(_run)


# ── Visual ─────────────────────────────────────────────────────────────────

@cli.command()
def presets():
    """List available color presets."""
    async def _run(connection):
        return await iterm2.ColorPreset.async_get_list(connection)
    for name in (run_iterm(_run) or []):
        click.echo(name)


@cli.command()
@click.argument('preset')
@click.option('-s', '--session', 'session_id', default=None)
def theme(preset, session_id):
    """Apply color preset. Shortcuts: red, green, dark, light."""
    preset_name = THEME_SHORTCUTS.get(preset, preset)

    async def _run(connection):
        session = await resolve_session(connection, session_id)
        preset_obj = await iterm2.ColorPreset.async_get(connection, preset_name)
        if not preset_obj:
            raise click.ClickException(
                f"Preset {preset_name!r} not found. Run 'ita presets' to list.")
        # WriteOnlyProfile is session-scoped and has the real async_set_color_preset.
        # LocalWriteOnlyProfile does not carry the preset setter.
        wop = iterm2.WriteOnlyProfile(session.session_id, connection)
        await wop.async_set_color_preset(preset_obj)

    run_iterm(_run)
