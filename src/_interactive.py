# src/_interactive.py
"""Interactive commands: alert, ask, pick, save-dialog, menu group, repl."""
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


@cli.group()
def menu():
    """Invoke iTerm2 menu items programmatically."""
    pass


@menu.command('list')
def menu_list():
    """List common menu item paths."""
    items = [
        "Shell/New Tab",
        "Shell/New Window",
        "Shell/Close",
        "Shell/Split Vertically with Current Profile",
        "Shell/Split Horizontally with Current Profile",
        "View/Enter Full Screen",
        "View/Exit Full Screen",
        "iTerm2/Preferences",
    ]
    for item in items:
        click.echo(item)


@menu.command('select')
@click.argument('item_path')
def menu_select(item_path):
    """Invoke menu item by path (e.g. 'Shell/New Tab')."""
    async def _run(connection):
        await iterm2.MainMenu.async_select_menu_item(connection, item_path)
    run_iterm(_run)


@menu.command('state')
@click.argument('item_path')
def menu_state(item_path):
    """Check if menu item is checked/enabled."""
    async def _run(connection):
        return await iterm2.MainMenu.async_get_menu_item_state(connection, item_path)
    click.echo(run_iterm(_run))


@cli.command()
def repl():
    """Interactive REPL mode. Maintains sticky context. Type 'exit' to quit."""
    from click.testing import CliRunner
    import shlex
    import _core

    click.echo("ita REPL — type commands, 'exit' to quit")
    click.echo(f"Target: {_core.get_sticky() or '(none)'}")

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
            if result.exit_code != 0 and result.exception:
                click.echo(f"Error: {result.exception}", err=True)
        except (KeyboardInterrupt, EOFError):
            break
    click.echo("Bye.")
