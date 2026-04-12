# src/_layouts.py
"""Arrangement commands: save, restore, layouts group (list/delete/rename/export)."""
import json
import click
import iterm2
from _core import cli, run_iterm


# ── Arrangements ──────────────────────────────────────────────────────────

@cli.command()
@click.argument('name')
@click.option('--window', 'window_only', is_flag=True, help='Save current window only')
@click.option('--force', '-f', is_flag=True, help='Overwrite existing arrangement without warning')
@click.option('--backup', is_flag=True, help='Create .bak copy of existing arrangement before overwriting')
def save(name, window_only, force, backup):
	"""Save current layout as named arrangement."""
	if not name.strip():
		raise click.ClickException("Name cannot be empty")
	async def _run(connection):
		if not force:
			existing = await iterm2.Arrangement.async_list(connection)
			if name in (existing or []):
				raise click.ClickException(
					f"Arrangement {name!r} already exists. Use --force to overwrite.")
		else:
			if backup:
				existing = await iterm2.Arrangement.async_list(connection)
				if name in (existing or []):
					try:
						arr = await iterm2.Arrangement.async_get(connection, name)
						bak_name = f"{name}.bak"
						await arr.async_rename(bak_name)
						await iterm2.Arrangement.async_rename(connection, bak_name, name)
					except Exception:
						pass
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
@click.option('-q', '--quiet', is_flag=True, help='Suppress confirmation message')
@click.option('--dry-run', is_flag=True, help='Print what would be restored without doing it')
def restore(name, quiet, dry_run):
	"""Restore named arrangement."""
	if dry_run:
		click.echo(f"Would restore: {name}")
		return
	async def _run(connection):
		try:
			await iterm2.Arrangement.async_restore(connection, name)
		except Exception as e:
			msg = str(e)
			if 'ARRANGEMENT_NOT_FOUND' in msg or 'NOT_FOUND' in msg:
				raise click.ClickException(f"Arrangement {name!r} not found")
			raise click.ClickException(f"Failed to restore {name!r}: {msg}") from e
	run_iterm(_run)
	if not quiet:
		click.echo(f"Restored: {name}")


@cli.group(invoke_without_command=True)
@click.pass_context
def layouts(ctx):
	"""Manage saved arrangements."""
	if ctx.invoked_subcommand is None:
		async def _run(connection):
			return await iterm2.Arrangement.async_list(connection)
		for n in (run_iterm(_run) or []):
			if n and n.strip():
				click.echo(n)


@layouts.command('list')
def layouts_list():
	"""List all saved arrangements."""
	async def _run(connection):
		return await iterm2.Arrangement.async_list(connection)
	for n in (run_iterm(_run) or []):
		if n and n.strip():
			click.echo(n)


@layouts.command('delete')
@click.argument('name')
def layouts_delete(name):
	"""Delete a saved arrangement."""
	if not name.strip():
		raise click.ClickException("Layout name cannot be empty")
	async def _run(connection):
		try:
			await iterm2.Arrangement.async_delete(connection, name)
		except Exception as e:
			msg = str(e)
			if 'NOT_FOUND' in msg or 'ARRANGEMENT_NOT_FOUND' in msg:
				raise click.ClickException(f"Arrangement {name!r} not found")
			raise click.ClickException(f"Failed to delete {name!r}: {msg}") from e
	run_iterm(_run)
	click.echo(f"Deleted: {name}")


@layouts.command('rename')
@click.argument('old_name')
@click.argument('new_name')
def layouts_rename(old_name, new_name):
	"""Rename a saved arrangement."""
	if not old_name.strip():
		raise click.ClickException("Old layout name cannot be empty")
	if not new_name.strip():
		raise click.ClickException("New layout name cannot be empty")
	async def _run(connection):
		try:
			arrangement = await iterm2.Arrangement.async_get(connection, old_name)
			if not arrangement:
				raise click.ClickException(f"Arrangement {old_name!r} not found")
			await arrangement.async_rename(new_name)
		except click.ClickException:
			raise
		except Exception as e:
			msg = str(e)
			if 'NOT_FOUND' in msg or 'ARRANGEMENT_NOT_FOUND' in msg:
				raise click.ClickException(f"Arrangement {old_name!r} not found")
			raise click.ClickException(f"Failed to rename {old_name!r}: {msg}") from e
	run_iterm(_run)
	click.echo(f"Renamed: {old_name} -> {new_name}")


@layouts.command('export')
@click.argument('name')
def layouts_export(name):
	"""Print a saved arrangement as JSON."""
	if not name.strip():
		raise click.ClickException("Layout name cannot be empty")
	async def _run(connection):
		try:
			arrangement = await iterm2.Arrangement.async_get(connection, name)
			if not arrangement:
				raise click.ClickException(f"Arrangement {name!r} not found")
			return arrangement.to_json() if hasattr(arrangement, 'to_json') else str(arrangement)
		except click.ClickException:
			raise
		except Exception as e:
			msg = str(e)
			if 'NOT_FOUND' in msg or 'ARRANGEMENT_NOT_FOUND' in msg:
				raise click.ClickException(f"Arrangement {name!r} not found")
			raise click.ClickException(f"Failed to export {name!r}: {msg}") from e
	result = run_iterm(_run)
	if isinstance(result, str) and result.startswith('{'):
		click.echo(result)
	else:
		click.echo(json.dumps(result, indent=2, default=str, ensure_ascii=False))
