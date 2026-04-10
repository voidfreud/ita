# src/_send.py
"""Input commands: run (atomic), send, inject.
File is named _send.py rather than _io.py to avoid collision with Python's built-in _io module."""
import asyncio
import json
import time
import click
import iterm2
from _core import cli, run_iterm, resolve_session, strip

PROMPT_CHARS = ('❯', '$', '#', '%', '→', '>>')


def _last_non_empty_index(contents):
	"""Last non-empty line index in a ScreenContents, or -1 if the grid is blank.
	number_of_lines is grid height, not content height — the bottom rows are
	usually empty whitespace, so the caller must scan backward to find content."""
	for i in range(contents.number_of_lines - 1, -1, -1):
		if strip(contents.line(i).string).strip():
			return i
	return -1


@cli.command()
@click.argument('cmd')
@click.option('-t', '--timeout', default=30, type=int, help='Timeout seconds (default: 30)')
@click.option('-n', '--lines', default=50, type=int, help='Output lines to return (default: 50)')
@click.option('--json', 'use_json', is_flag=True)
@click.option('-s', '--session', 'session_id', default=None)
def run(cmd, timeout, lines, use_json, session_id):
	"""Send command, wait for completion, return clean output. Atomic — one call does all."""
	async def _run(connection):
		session = await resolve_session(connection, session_id)
		start = time.time()

		# Wait for completion via ScreenStreamer (event-driven, no polling).
		# Subscribe BEFORE sending so instant commands don't race past us.
		async with session.get_screen_streamer() as streamer:
			await session.async_send_text(cmd + '\n')
			cmd_seen = False
			for _ in range(timeout * 4):
				try:
					contents = await asyncio.wait_for(streamer.async_get(), timeout=1.0)
					last_idx = _last_non_empty_index(contents)
					if last_idx < 0:
						continue
					if not cmd_seen:
						screen_text = '\n'.join(
							strip(contents.line(i).string)
							for i in range(last_idx + 1)
						)
						if cmd in screen_text:
							cmd_seen = True
					if cmd_seen:
						last = strip(contents.line(last_idx).string).strip()
						if any(last.startswith(p) or last.endswith(p) for p in PROMPT_CHARS):
							break
				except asyncio.TimeoutError:
					continue

		elapsed_ms = int((time.time() - start) * 1000)

		# Read output: slice backward from the last non-empty line.
		contents = await session.async_get_screen_contents()
		last_idx = _last_non_empty_index(contents)
		if last_idx < 0:
			output = ''
		else:
			start_line = max(0, last_idx + 1 - lines)
			output_lines = [strip(contents.line(i).string) for i in range(start_line, last_idx + 1)]
			while output_lines and not output_lines[-1].strip():
				output_lines.pop()
			output = '\n'.join(output_lines)

		return output, elapsed_ms

	output, elapsed_ms = run_iterm(_run)

	if use_json:
		click.echo(json.dumps({'output': output, 'elapsed_ms': elapsed_ms}))
	else:
		click.echo(output)


@cli.command()
@click.argument('text')
@click.option('--raw', is_flag=True, help='Do not append newline')
@click.option('-s', '--session', 'session_id', default=None)
def send(text, raw, session_id):
	"""Send text to session. Appends newline unless --raw."""
	async def _run(connection):
		session = await resolve_session(connection, session_id)
		await session.async_send_text(text if raw else text + '\n')
	run_iterm(_run)


@cli.command()
@click.argument('data')
@click.option('--hex', 'is_hex', is_flag=True, help='Interpret DATA as hex bytes (e.g. 03 for Ctrl+C)')
@click.option('-s', '--session', 'session_id', default=None)
def inject(data, is_hex, session_id):
	"""Inject raw bytes. Use $'\\x03' for Ctrl+C, $'\\x1b' for Escape, etc."""
	async def _run(connection):
		session = await resolve_session(connection, session_id)
		if is_hex:
			raw = bytes.fromhex(data.replace(' ', ''))
		else:
			# Interpret escape sequences like \x03, \n, \t
			raw = data.encode('utf-8').decode('unicode_escape').encode('latin-1')
		await session.async_inject(raw)
	run_iterm(_run)
