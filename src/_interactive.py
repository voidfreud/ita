# src/_interactive.py
"""Interactive commands: alert, ask, pick, save-dialog, menu group, repl."""
import functools
import click
import iterm2
from _core import cli, run_iterm


@cli.command()
@click.argument('title')
@click.argument('message')
@click.option('--button', 'buttons', multiple=True, help='Add a button label')
def alert(title, message, buttons):
	"""Show macOS alert dialog. Returns clicked button label."""
	async def _run(connection):
		a = iterm2.Alert(title, message, connection)
		for b in buttons:
			a.add_button(b)
		return await a.async_run()
	result = run_iterm(_run)
	click.echo(result)


@cli.command()
@click.argument('title')
@click.argument('message')
@click.option('--default', 'default_val', default='', help='Pre-filled value')
def ask(title, message, default_val):
	"""Show text input dialog. Returns entered text (empty if cancelled)."""
	async def _run(connection):
		a = iterm2.TextInputAlert(title, message, default_val, connection)
		return await a.async_run()
	result = run_iterm(_run)
	if result is not None:
		click.echo(result)


@cli.command()
@click.option('--ext', 'extensions', multiple=True, help='Allowed file extensions')
@click.option('--multi', is_flag=True, help='Allow selecting multiple files')
def pick(extensions, multi):
	"""File open dialog. Returns selected path(s)."""
	async def _run(connection):
		panel = iterm2.OpenPanel()
		if extensions:
			panel.allowed_file_types = list(extensions)
		panel.allows_multiple_selection = multi
		return await panel.async_run(connection)
	result = run_iterm(_run)
	if result:
		for f in result:
			click.echo(f)


@cli.command('save-dialog')
@click.option('--name', 'filename', default=None, help='Pre-filled filename')
def save_dialog(filename):
	"""File save dialog. Returns chosen path."""
	async def _run(connection):
		panel = iterm2.SavePanel()
		if filename:
			panel.filename = filename
		return await panel.async_run(connection)
	result = run_iterm(_run)
	if result:
		click.echo(result)


class _MenuGroup(click.Group):
	"""Lets `ita menu "Shell/Split..."` work as a shortcut for `ita menu select`.
	If the first token isn't a known subcommand, we route it through `select`."""
	def resolve_command(self, ctx, args):
		if args and args[0] not in self.commands:
			if args[0].startswith('-'):
				raise click.UsageError(f"Unknown option: {args[0]!r}")
			return 'select', self.commands['select'], args
		return super().resolve_command(ctx, args)


@cli.group(cls=_MenuGroup)
def menu():
	"""Invoke iTerm2 menu items programmatically.

	Direct form: ita menu "Shell/Split Vertically with Current Profile"
	Subcommands: select, state, list
	"""
	pass


_MENU_GROUPS = ('iTerm2', 'Shell', 'Edit', 'View', 'Session', 'Scripts',
				'Profiles', 'Toolbelt', 'Window', 'Help')


@functools.lru_cache(maxsize=1)
def _menu_index():
	"""Build a dict of lookup keys → identifier string for every menu item iTerm2
	exposes. Keys include the raw identifier (e.g. 'Close'), the user-visible title
	(e.g. 'Close'), and group-qualified forms (e.g. 'Shell/Close', 'Shell.CLOSE')."""
	result = {}
	for group_name in _MENU_GROUPS:
		group = getattr(iterm2.MainMenu, group_name, None)
		if group is None:
			continue
		for member in group:
			mi = member.value  # MenuItemIdentifier: .title (user-visible) and .identifier (internal)
			ident = mi.identifier
			result[ident] = ident
			result[mi.title] = ident
			result[f"{group_name}/{mi.title}"] = ident
			result[f"{group_name}.{member.name}"] = ident
	return result


def _resolve_menu(key: str) -> str:
	"""Resolve a user-supplied menu key to its internal identifier, or fall through
	unchanged (letting iTerm2 reject unknown identifiers with its own error)."""
	idx = _menu_index()
	return idx.get(key, key)


@menu.command('list')
@click.option('--group', default=None, help='Filter by menu group (Shell, Edit, View, ...)')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSON')
def menu_list(group, output_json):
	"""List every menu item iTerm2 exposes as (group/title → identifier)."""
	import json
	items = []
	for group_name in _MENU_GROUPS:
		if group and group.lower() != group_name.lower():
			continue
		grp = getattr(iterm2.MainMenu, group_name, None)
		if grp is None:
			continue
		for member in grp:
			mi = member.value
			if output_json:
				items.append({
					'title': f"{group_name}/{mi.title}",
					'enabled': True
				})
			else:
				click.echo(f"{group_name}/{mi.title}\t{mi.identifier}")
	if output_json:
		click.echo(json.dumps(items))


_MENU_ERROR_MAP = {
	'DISABLED': "Menu item is disabled",
	'NOT_FOUND': "Menu item not found",
	'BAD_IDENTIFIER': "Menu item not found",
}


def _humanize_menu_error(e, path):
	msg = str(e)
	for code, human in _MENU_ERROR_MAP.items():
		if code in msg:
			if code == 'BAD_IDENTIFIER':
				raise click.ClickException(f"Menu item not found: {path!r}") from e
			raise click.ClickException(human) from e
	raise


@menu.command('select')
@click.argument('item')
def menu_select(item):
	"""Invoke a menu item. Accepts 'Shell/Close', 'Shell.CLOSE', or the raw
	identifier 'Close'. Use 'ita menu list' to see every valid input."""
	identifier = _resolve_menu(item)
	async def _run(connection):
		try:
			await iterm2.MainMenu.async_select_menu_item(connection, identifier)
		except Exception as e:
			_humanize_menu_error(e, item)
	run_iterm(_run)


@menu.command('state')
@click.argument('item')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSON')
def menu_state(item, output_json):
	"""Check if a menu item is checked/enabled. Accepts 'Shell/Close',
	'Shell.CLOSE', or the raw identifier 'Close'."""
	import json
	identifier = _resolve_menu(item)
	async def _run(connection):
		try:
			return await iterm2.MainMenu.async_get_menu_item_state(connection, identifier)
		except Exception as e:
			_humanize_menu_error(e, item)
	state = run_iterm(_run)
	if output_json:
		click.echo(json.dumps({
			'title': item,
			'enabled': state.enabled,
			'checked': state.checked
		}))
	else:
		click.echo(f"checked: {state.checked}")
		click.echo(f"enabled: {state.enabled}")


@cli.command()
def repl():
	"""Interactive REPL mode. Type 'exit' to quit."""
	from click.testing import CliRunner
	import shlex

	click.echo("ita REPL — type commands, 'exit' to quit")

	runner = CliRunner(mix_stderr=False)
	while True:
		try:
			line = click.prompt('ita', prompt_suffix=' > ')
			if line.strip() in ('exit', 'quit', 'q'):
				break
			if not line.strip():
				continue
			result = runner.invoke(cli, shlex.split(line))
			if result.output:
				click.echo(result.output, nl=False)
			if result.exit_code != 0:
				if result.stderr:
					click.echo(result.stderr, err=True, nl=False)
				if result.exception and not isinstance(result.exception, SystemExit):
					click.echo(f"Error: {result.exception}", err=True)
				elif not result.stderr:
					click.echo(f"Error: exited with code {result.exit_code}", err=True)
		except (KeyboardInterrupt, EOFError):
			break
	click.echo("Bye.")
