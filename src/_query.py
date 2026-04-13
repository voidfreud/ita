# src/_query.py
"""Point-in-time query commands: wait, selection, copy, get-prompt."""
import asyncio
import json
import re
import subprocess
import click
import iterm2
from _core import cli, run_iterm, resolve_session, strip, last_non_empty_index, _is_prompt_line


@cli.command()
@click.option('--pattern', default=None, help='Regex to wait for (use --fixed-string for literal).')
@click.option('--fixed-string', 'fixed_string', is_flag=True,
	help='Treat --pattern as literal substring.')
@click.option('-t', '--timeout', default=30, type=int)
@click.option('--json', 'use_json', is_flag=True, help='Output {matched, line, elapsed_ms}.')
@click.option('-s', '--session', 'session_id', default=None)
def wait(pattern, fixed_string, timeout, use_json, session_id):
	"""Block until next shell prompt (or pattern) appears. Event-driven via ScreenStreamer."""
	matcher = None
	if pattern:
		if fixed_string:
			def matcher(text): return pattern in text
		else:
			try:
				rx = re.compile(pattern)
			except re.error as e:
				raise click.ClickException(f"Invalid regex {pattern!r}: {e}") from e
			def matcher(text): return rx.search(text) is not None

	async def _run(connection):
		session = await resolve_session(connection, session_id)
		start = asyncio.get_event_loop().time()
		matched_line = None

		def _check(contents) -> bool:
			nonlocal matched_line
			if matcher is not None:
				for i in range(contents.number_of_lines):
					line = strip(contents.line(i).string)
					if matcher(line):
						matched_line = line
						return True
				return False
			last_idx = last_non_empty_index(contents)
			if last_idx < 0:
				return False
			line = strip(contents.line(last_idx).string)
			if _is_prompt_line(line):
				matched_line = line
				return True
			return False

		contents = await session.async_get_screen_contents()
		if _check(contents):
			return (True, matched_line, asyncio.get_event_loop().time() - start)

		async def _stream_loop():
			async with session.get_screen_streamer() as streamer:
				while True:
					contents = await streamer.async_get()
					if _check(contents):
						return (True, matched_line, asyncio.get_event_loop().time() - start)

		try:
			return await asyncio.wait_for(_stream_loop(), timeout=timeout)
		except asyncio.TimeoutError:
			return (False, matched_line, asyncio.get_event_loop().time() - start)

	result = run_iterm(_run)
	found, matched_line, elapsed = result
	elapsed_ms = int(elapsed * 1000)

	if use_json:
		click.echo(json.dumps(
			{'matched': found, 'line': matched_line, 'elapsed_ms': elapsed_ms},
			ensure_ascii=False,
		))
	elif not found:
		# #231: text mode timeout must be distinguishable from a match (rc != 0).
		click.echo("timeout", err=True)
		raise SystemExit(1)


@cli.command()
@click.option('--json', 'use_json', is_flag=True)
@click.option('-s', '--session', 'session_id', default=None)
def selection(use_json, session_id):
	"""Get currently selected text."""
	async def _run(connection):
		session = await resolve_session(connection, session_id)
		sel = await session.async_get_selection()
		if not sel:
			return ''
		text = await session.async_get_selection_text(sel)
		return strip(text or '')

	text = run_iterm(_run)
	if use_json:
		click.echo(json.dumps({'text': text or None}, ensure_ascii=False))
	elif not text:
		return
	else:
		click.echo(text)


@cli.command()
@click.option('-s', '--session', 'session_id', default=None)
def copy(session_id):
	"""Copy selected text to macOS clipboard."""
	async def _run(connection):
		session = await resolve_session(connection, session_id)
		sel = await session.async_get_selection()
		if not sel:
			return ''
		text = await session.async_get_selection_text(sel)
		return strip(text or '')

	text = run_iterm(_run)
	if not text:
		return
	subprocess.run(['pbcopy'], input=text.encode(), check=True)
	click.echo(f"Copied {len(text)} chars to clipboard.")


@cli.command('get-prompt')
@click.option('-s', '--session', 'session_id', default=None)
@click.option('--json', 'use_json', is_flag=True, default=False)
def get_prompt(session_id, use_json):
	"""Get last prompt info: cwd, command, exit code."""
	async def _run(connection):
		session = await resolve_session(connection, session_id)
		try:
			prompt = await iterm2.async_get_last_prompt(connection, session.session_id)
		except Exception:
			return None
		if not prompt:
			return None
		raw_exit = await session.async_get_variable('lastExitStatus')
		exit_code = int(raw_exit) if raw_exit is not None else None
		return {
			'cwd': prompt.working_directory,
			'command': prompt.command,
			'exit_code': exit_code,
		}

	result = run_iterm(_run)
	if use_json:
		if result:
			result['present'] = True
			click.echo(json.dumps(result, ensure_ascii=False))
		else:
			click.echo(json.dumps({'cwd': None, 'command': None, 'exit_code': None, 'present': False}, ensure_ascii=False))
	elif result:
		click.echo(f"cwd:      {result['cwd']}")
		click.echo(f"command:  {result['command']}")
		click.echo(f"exit_code: {result['exit_code']}")
	else:
		click.echo("No prompt info — is shell integration active?")
