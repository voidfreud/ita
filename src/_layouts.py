# src/_layouts.py
"""Arrangement commands: save, restore, layouts group (list).

Note: iTerm2's Python API only supports save/restore/list for arrangements.
There is no public API for delete, rename, or export (no async_delete,
async_rename, or async_get on iterm2.Arrangement). Those commands were
removed — see issue #138.
"""
import click
import iterm2
from _core import cli, run_iterm


# ── Arrangements ──────────────────────────────────────────────────────────

@cli.command()
@click.argument('name')
@click.option('--window', 'window_only', is_flag=True, help='Save current window only')
@click.option('--force', '-f', is_flag=True, help='Overwrite existing arrangement without warning')
def save(name, window_only, force):
	"""Save current layout as named arrangement."""
	if not name.strip():
		raise click.ClickException("Name cannot be empty")
	async def _run(connection):
		if not force:
			existing = await iterm2.Arrangement.async_list(connection)
			if name in (existing or []):
				raise click.ClickException(
					f"Arrangement {name!r} already exists. Use --force to overwrite.")
		if window_only:
			app = await iterm2.async_get_app(connection)
			w = app.current_terminal_window
			if not w:
				raise click.ClickException("No current window — cannot save window layout.")
			await w.async_save_window_as_arrangement(name)
		else:
			await iterm2.Arrangement.async_save(connection, name)
		return True
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
