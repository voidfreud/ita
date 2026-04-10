# src/_send.py
"""Input commands: run (atomic), send, inject, key.
File is named _send.py rather than _io.py to avoid collision with Python's built-in _io module."""
import asyncio
import json
import re
import sys
import time
import uuid
import click
import iterm2
from _core import cli, run_iterm, resolve_session, strip, PROMPT_CHARS, last_non_empty_index


@cli.command()
@click.argument('cmd')
@click.option('-t', '--timeout', default=30, type=int, help='Timeout seconds (default: 30)')
@click.option('-n', '--lines', default=50, type=int, help='Output lines to return (default: 50)')
@click.option('--json', 'use_json', is_flag=True)
@click.option('-s', '--session', 'session_id', default=None)
def run(cmd, timeout, lines, use_json, session_id):
	"""Send command, wait for completion, return scoped output and exit code.
	Command runs in a subshell so side effects like `exit`, `cd`, and env
	mutations stay isolated. For state-persistent commands use `ita send`."""
	async def _run(connection):
		session = await resolve_session(connection, session_id)
		start = time.time()

		# Unique tag used as (a) OSC identity shared secret and (b) a searchable
		# token in the shell's command-echo line for output slicing.
		tag = uuid.uuid4().hex[:12]
		identity = f"ita-{tag}"
		# OSC 1337 custom control sequence: iTerm2 intercepts and consumes this
		# invisibly — it never reaches the terminal screen. Payload carries the
		# subshell's exit code. Wrapping user's cmd in (...) isolates destructive
		# side effects like `exit` from the parent shell.
		# Note the spaces inside `( ... )`: without them, a user command that itself
		# starts with `(` would form `((...))`, which zsh/bash parse as an arithmetic
		# expansion instead of a nested subshell.
		wrapped = f"( {cmd} ); _ita_rc=$?; printf '\\033]1337;Custom=id={identity}:%d\\033\\\\' $_ita_rc"

		exit_code = None
		async with iterm2.CustomControlSequenceMonitor(
				connection, identity, r'^(\d+)$', session.session_id) as mon:
			await session.async_send_text(wrapped + '\n')
			try:
				match = await asyncio.wait_for(mon.async_get(), timeout=timeout)
				exit_code = int(match.group(1))
			except asyncio.TimeoutError:
				pass  # fall through with exit_code=None

		elapsed_ms = int((time.time() - start) * 1000)

		# Find the command-echo row by searching for our unique tag. The tag
		# appears in the shell's echo of the wrapped command and nowhere else
		# (the OSC was consumed by iTerm2, so the only place the tag survives
		# visibly is the shell's echo of what the user "typed").
		contents = await session.async_get_screen_contents()
		echo_row = None
		for i in range(contents.number_of_lines):
			if tag in strip(contents.line(i).string):
				echo_row = i
				break

		last_idx = last_non_empty_index(contents)
		if echo_row is not None:
			# Slice strictly after the echo row. If the cmd had no output and the
			# new prompt hasn't re-rendered yet (echo_row == last_idx), this is
			# an empty range — exactly what we want.
			start_row = echo_row + 1
			end_row = max(start_row, last_idx + 1) if last_idx >= 0 else start_row
			# Cap to the `lines` most recent rows.
			if end_row - start_row > lines:
				start_row = end_row - lines
			output_lines = [strip(contents.line(i).string) for i in range(start_row, end_row)]
			# Drop trailing prompt row if present.
			if output_lines:
				tail = output_lines[-1].strip()
				if tail and any(tail.startswith(p) or tail.endswith(p) for p in PROMPT_CHARS):
					output_lines.pop()
			while output_lines and not output_lines[-1].strip():
				output_lines.pop()
			output = '\n'.join(output_lines)
		else:
			# Echo row not found (screen scrolled past it, or shell didn't echo).
			# Fallback: last N non-empty lines, old-style.
			if last_idx < 0:
				output = ''
			else:
				start_line = max(0, last_idx + 1 - lines)
				output_lines = [strip(contents.line(i).string) for i in range(start_line, last_idx + 1)]
				while output_lines and not output_lines[-1].strip():
					output_lines.pop()
				output = '\n'.join(output_lines)

		return output, elapsed_ms, exit_code

	output, elapsed_ms, exit_code = run_iterm(_run)

	if use_json:
		click.echo(json.dumps({'output': output, 'elapsed_ms': elapsed_ms, 'exit_code': exit_code}))
	else:
		click.echo(output)

	if exit_code is not None and exit_code != 0:
		sys.exit(exit_code)


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
@click.option('--hex', 'is_hex', is_flag=True, help='Interpret DATA as hex bytes')
@click.option('-s', '--session', 'session_id', default=None)
def inject(data, is_hex, session_id):
	"""Inject raw bytes into the terminal emulator's output stream (display side).
	For sending input to a running process (Ctrl+C, arrow keys, etc.) use 'ita key' instead."""
	async def _run(connection):
		session = await resolve_session(connection, session_id)
		if is_hex:
			raw = bytes.fromhex(data.replace(' ', ''))
		else:
			raw = data.encode('utf-8').decode('unicode_escape').encode('latin-1')
		await session.async_inject(raw)
	run_iterm(_run)


# Friendly key names → literal byte sequences delivered as user input.
# Control chars are single bytes; special keys use the standard VT100/xterm
# escape sequences that iTerm2's shell consumers already understand.
_KEY_MAP = {
	'enter': '\r',
	'return': '\r',
	'tab': '\t',
	'backspace': '\x7f',
	'esc': '\x1b',
	'escape': '\x1b',
	'space': ' ',
	'up': '\x1b[A',
	'down': '\x1b[B',
	'right': '\x1b[C',
	'left': '\x1b[D',
	'home': '\x1b[H',
	'end': '\x1b[F',
	'pgup': '\x1b[5~',
	'pgdn': '\x1b[6~',
	'pagedown': '\x1b[6~',
	'pageup': '\x1b[5~',
	'delete': '\x1b[3~',
	'f1': '\x1bOP', 'f2': '\x1bOQ', 'f3': '\x1bOR', 'f4': '\x1bOS',
	'f5': '\x1b[15~', 'f6': '\x1b[17~', 'f7': '\x1b[18~', 'f8': '\x1b[19~',
	'f9': '\x1b[20~', 'f10': '\x1b[21~', 'f11': '\x1b[23~', 'f12': '\x1b[24~',
}


def _parse_key(token: str) -> bytes:
	"""Resolve 'ctrl+c', 'alt+f', 'f5', 'enter', etc. to the bytes iTerm2 should deliver as input."""
	t = token.strip().lower()
	if not t:
		raise click.ClickException("empty key token")
	# ctrl+<letter|number> → 0x01..0x1a (letters), 0x00 for @, 0x1b for [, etc.
	if t.startswith('ctrl+') or t.startswith('c-'):
		rest = t.split('+', 1)[1] if '+' in t else t[2:]
		if len(rest) == 1:
			ch = rest
			if 'a' <= ch <= 'z':
				return bytes([ord(ch) - ord('a') + 1])
			if ch == '@':
				return b'\x00'
			if ch == '[':
				return b'\x1b'
			if ch == '\\':
				return b'\x1c'
			if ch == ']':
				return b'\x1d'
			if ch == '^':
				return b'\x1e'
			if ch == '_':
				return b'\x1f'
		raise click.ClickException(f"unsupported ctrl combination: {token!r}")
	# alt+<key> → ESC followed by the key's bytes
	if t.startswith('alt+') or t.startswith('a-') or t.startswith('meta+') or t.startswith('m-'):
		rest = t.split('+', 1)[1] if '+' in t else t[2:]
		if len(rest) == 1:
			return b'\x1b' + rest.encode('utf-8')
		if rest in _KEY_MAP:
			return b'\x1b' + _KEY_MAP[rest].encode('latin-1')
		raise click.ClickException(f"unsupported alt combination: {token!r}")
	# Named key
	if t in _KEY_MAP:
		return _KEY_MAP[t].encode('latin-1')
	# Single literal character
	if len(t) == 1:
		return token.encode('utf-8')
	raise click.ClickException(
		f"unknown key: {token!r}. Try ctrl+c, alt+f, enter, esc, tab, up, f5, etc."
	)


@cli.command()
@click.argument('keys', nargs=-1, required=True)
@click.option('-s', '--session', 'session_id', default=None)
def key(keys, session_id):
	"""Send keystrokes as user input. Use friendly names: ctrl+c, ctrl+d, esc, enter,
	tab, space, backspace, up, down, left, right, home, end, pgup, pgdn, f1-f12.
	Multiple keys are sent in order: 'ita key ctrl+c ctrl+c' sends Ctrl+C twice."""
	try:
		payload = b''.join(_parse_key(k) for k in keys)
	except click.ClickException:
		raise
	async def _run(connection):
		session = await resolve_session(connection, session_id)
		# Decode bytes back to a str for async_send_text (it takes text, not raw bytes —
		# iTerm2 internally encodes via the session's terminal encoding).
		await session.async_send_text(payload.decode('latin-1'))
	run_iterm(_run)
