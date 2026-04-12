# src/_meta.py
"""Meta commands: commands (tree), doctor (health check)."""
import json
import shutil
import click
import iterm2
from _core import cli, run_iterm


@cli.command()
@click.option('--json', 'use_json', is_flag=True, help='Output as JSON (always JSON; flag for explicitness)')
def commands(use_json):
	"""Output full command tree as JSON."""
	def _build(group):
		result = []
		for name in sorted(group.commands.keys()):
			cmd = group.commands[name]
			entry = {
				'name': name,
				'help': (cmd.help or '').split('\n')[0],
			}
			if isinstance(cmd, click.Group):
				entry['commands'] = _build(cmd)
			result.append(entry)
		return result

	tree = {'name': 'ita', 'commands': _build(cli)}
	click.echo(json.dumps(tree, indent=2))


@cli.command()
def doctor():
	"""Verify ita setup and iTerm2 connectivity."""
	checks = []

	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		checks.append(('iTerm2 reachable', True, None))
		checks.append(('Python API responding', True, None))

		try:
			import subprocess
			r = subprocess.run(
				['osascript', '-e', 'tell application "iTerm2" to get version'],
				capture_output=True, text=True, timeout=5)
			version = r.stdout.strip()
			checks.append(('iTerm2 version', True, version or 'unknown'))
		except Exception:
			checks.append(('iTerm2 version', False, 'Could not determine'))

		# Shell integration: check all sessions for iterm2_shell_integration_version
		si_version = None
		for window in app.windows:
			for tab in window.tabs:
				for session in tab.sessions:
					val = await session.async_get_variable('user.iterm2_shell_integration_version')
					if val:
						si_version = val
						break
				if si_version:
					break
			if si_version:
				break
		if si_version:
			checks.append(('Shell integration', True, f'v{si_version}'))
		else:
			checks.append(('Shell integration', False, 'not detected on any session'))

	try:
		run_iterm(_run)
	except Exception as e:
		click.echo(f"✗ iTerm2 reachable: {e}")
		return

	# uv and tmux are checked outside the async context (no iTerm2 needed)
	uv_path = shutil.which("uv")
	checks.append(('uv available', bool(uv_path), uv_path or None))
	tmux_path = shutil.which("tmux")
	checks.append(('tmux available', bool(tmux_path), tmux_path or None))

	for check_name, passed, detail in checks:
		symbol = '✓' if passed else '✗'
		detail_str = f' ({detail})' if detail else ''
		click.echo(f"{symbol} {check_name}{detail_str}")
