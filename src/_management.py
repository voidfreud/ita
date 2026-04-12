# src/_management.py
"""Management commands: profile group, presets, theme."""
import json
import re
import click
import iterm2
from _core import cli, run_iterm, resolve_session

THEME_SHORTCUTS = {
	'red': 'Red Alert',
	# 'green' is handled specially: no built-in preset reads as green, so we
	# paint a dark-green background directly via profile properties below.
	'dark': 'Solarized Dark',
	'light': 'Solarized Light',
}

# Dark green success background, off-white foreground. Used when the user asks
# for `ita theme green` since iTerm2 ships no green color preset.
_GREEN_BG = (0.0, 0.20, 0.0)
_GREEN_FG = (0.85, 0.95, 0.85)


# ── Profiles ──────────────────────────────────────────────────────────────

@cli.group()
def profile():
	"""Manage profiles."""
	pass


@profile.command('list')
@click.option('--json', 'use_json', is_flag=True)
@click.option('--ids-only', is_flag=True, help='Print only profile GUIDs (one per line).')
def profile_list(use_json, ids_only):
	"""List all profiles."""
	async def _run(connection):
		profiles = await iterm2.PartialProfile.async_query(connection)
		return [(p.name, p.guid) for p in profiles]
	profiles = run_iterm(_run)
	if ids_only:
		for name, guid in profiles:
			click.echo(guid)
		return
	if use_json:
		click.echo(json.dumps([{'name': n, 'guid': g} for n, g in profiles], indent=2, ensure_ascii=False))
		return
	for name, guid in profiles:
		click.echo(f"{guid}  {name}")


def _profile_show_impl(name, session_id):
	"""Shared implementation for profile show/get."""
	async def _run(connection):
		if session_id or not name:
			session = await resolve_session(connection, session_id)
			p = await session.async_get_profile()
		else:
			profiles = await iterm2.PartialProfile.async_query(connection)
			p = next((x for x in profiles if x.name == name), None)
			if not p:
				raise click.ClickException(f"Profile {name!r} not found")
		result = {'name': p.name, 'guid': p.guid}
		for attr in ('foreground_color', 'background_color', 'cursor_color',
					 'normal_font', 'non_ascii_font', 'use_non_ascii_font',
					 'horizontal_spacing', 'vertical_spacing', 'cursor_type',
					 'transparency', 'blur', 'badge_text', 'command',
					 'working_directory', 'initial_text'):
			try:
				val = getattr(p, attr, None)
				if val is not None:
					result[attr] = str(val) if not isinstance(val, (str, int, float, bool)) else val
			except Exception:
				click.echo(f"warning: failed to read {attr}", err=True)
		return result
	click.echo(json.dumps(run_iterm(_run), indent=2, default=str, ensure_ascii=False))


@profile.command('show')
@click.argument('name', required=False)
@click.option('-s', '--session', 'session_id', default=None)
def profile_show(name, session_id):
	"""Show profile details."""
	_profile_show_impl(name, session_id)


@profile.command('get')
@click.argument('name', required=False)
@click.option('-s', '--session', 'session_id', default=None)
def profile_get(name, session_id):
	"""Get profile details (alias for show)."""
	_profile_show_impl(name, session_id)


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
		if hasattr(change, f'set_{property_name}'):
			property_name = f'set_{property_name}'
		else:
			raise click.ClickException(
				f"Unknown profile property: {property_name!r}. "
				"See iterm2.LocalWriteOnlyProfile for valid setters.")

	if re.search(r'_color(_light|_dark)?$', property_name) and not property_name.startswith('use_'):
		try:
			color_value = iterm2.Color(int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16))
		except (ValueError, IndexError):
			raise click.ClickException(
				f"Invalid hex color format for {property_name!r}: {value!r}. "
				"Expected format: #RRGGBB")
		value = color_value

	async def _run(connection):
		session = await resolve_session(connection, session_id)
		setattr(change, property_name, value)
		await session.async_set_profile_properties(change)
	run_iterm(_run)


# ── Visual ─────────────────────────────────────────────────────────────────

@cli.command()
@click.option('--json', 'use_json', is_flag=True)
def presets(use_json):
	"""List available color presets."""
	async def _run(connection):
		return await iterm2.ColorPreset.async_get_list(connection)
	names = run_iterm(_run) or []
	if use_json:
		click.echo(json.dumps(names, indent=2, ensure_ascii=False))
		return
	for name in names:
		click.echo(name)


@cli.command()
@click.argument('preset')
@click.option('-s', '--session', 'session_id', default=None)
@click.option('-q', '--quiet', is_flag=True, help='Suppress confirmation message')
@click.option('--dry-run', is_flag=True, help='Print what would be applied without doing it')
def theme(preset, session_id, quiet, dry_run):
	"""Apply color preset. Shortcuts: red, green, dark, light."""
	preset_name = THEME_SHORTCUTS.get(preset, preset)
	if dry_run:
		click.echo(f"Would apply theme: {preset_name!r}")
		return
	# Special case: `green` has no matching built-in preset — paint directly.
	if preset == 'green':
		async def _run_green(connection):
			session = await resolve_session(connection, session_id)
			wop = iterm2.WriteOnlyProfile(session.session_id, connection)
			bg = iterm2.Color(
				int(_GREEN_BG[0] * 255), int(_GREEN_BG[1] * 255), int(_GREEN_BG[2] * 255))
			fg = iterm2.Color(
				int(_GREEN_FG[0] * 255), int(_GREEN_FG[1] * 255), int(_GREEN_FG[2] * 255))
			await wop.async_set_background_color(bg)
			await wop.async_set_foreground_color(fg)
		run_iterm(_run_green)
		if not quiet:
			click.echo(f"Applied theme: green")
		return

	async def _run(connection):
		session = await resolve_session(connection, session_id)
		try:
			preset_obj = await iterm2.ColorPreset.async_get(connection, preset_name)
		except Exception as e:
			available = await iterm2.ColorPreset.async_get_list(connection)
			if 'PRESET_NOT_FOUND' in str(e):
				msg = f"Theme preset {preset_name!r} not found. Available presets:\n"
				msg += '\n'.join(f"  {p}" for p in (available or []))
				raise click.ClickException(msg) from e
			raise
		if not preset_obj:
			available = await iterm2.ColorPreset.async_get_list(connection)
			msg = f"Theme preset {preset_name!r} not found. Available presets:\n"
			msg += '\n'.join(f"  {p}" for p in (available or []))
			raise click.ClickException(msg)
		# WriteOnlyProfile is session-scoped and has the real async_set_color_preset.
		# LocalWriteOnlyProfile does not carry the preset setter.
		wop = iterm2.WriteOnlyProfile(session.session_id, connection)
		await wop.async_set_color_preset(preset_obj)

	run_iterm(_run)
	if not quiet:
		click.echo(f"Applied theme: {preset_name!r}")
