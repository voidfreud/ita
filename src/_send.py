# src/_send.py
"""Input commands: run (atomic), send, inject, key.
File is named _send.py rather than _io.py to avoid collision with Python's built-in _io module."""
import asyncio
import json
import sys
import time
import uuid
import click
import iterm2
from _core import cli, run_iterm, resolve_session, strip, PROMPT_CHARS, last_non_empty_index, check_protected

_shell_integration_warned = False


def _is_prompt_line(s: str) -> bool:
	"""True if s looks like a shell prompt line with no meaningful content
	(e.g. '~ ❯', '$', '% ', '~ ❯ :'). Catches both fully-rendered prompts and
	echo remnants where only the prompt + command-separator punctuation survived."""
	t = s.strip()
	if not t:
		return False
	if t in PROMPT_CHARS:
		return True
	if any(t.startswith(p + ' ') for p in PROMPT_CHARS):
		return True
	if any(t.endswith(' ' + p) for p in PROMPT_CHARS):
		return True
	# Line contains a prompt char AND its non-prompt residue is only punctuation /
	# whitespace (e.g. '~ ❯ :' — echo row remnant with the `: ita-tag;` truncated).
	if any(p in t for p in PROMPT_CHARS):
		residue = t
		for p in PROMPT_CHARS:
			residue = residue.replace(p, '')
		if not residue.strip(' ~./:;'):
			return True
	return False


def _trim_output_lines(lines: list[str]) -> list[str]:
	"""Drop trailing prompt/blank rows, strip zsh `%` no-newline indicator from the
	final content line, and remove leading/trailing blanks. Never discards the last
	real content line — BUG-3: when the `%` indicator is alone on its own row right
	after real output, we strip it without deleting the content above it."""
	out = list(lines)
	# Drop a trailing prompt row (may happen when a fresh prompt rendered below output).
	if out and _is_prompt_line(out[-1]):
		out.pop()
	# Strip the zsh no-newline `%` indicator: it may live alone on the last row,
	# or be glued to the tail of the final content row.
	if out:
		tail = out[-1].rstrip()
		if tail == '%':
			# `%` alone → just remove the row; content above is preserved.
			out.pop()
		else:
			# `noeol%` or `... %` → strip the trailing prompt-char (but only one).
			for p in PROMPT_CHARS:
				if tail.endswith(p):
					trimmed = tail[: -len(p)].rstrip()
					# Only apply the strip if we're not erasing the whole line — a
					# bare prompt char here would already have been caught above.
					out[-1] = trimmed
					break
	# Drop leading/trailing blank rows.
	while out and not out[0].strip():
		out.pop(0)
	while out and not out[-1].strip():
		out.pop()
	return out


def _fallback_output(contents, lines_cap: int, tag: str | None = None) -> str:
	"""Echo marker not found or not useful — return the last N non-empty rows of
	the visible screen, trimmed of prompt/blank noise. Used when the command's echo
	row has scrolled off-screen (BUG-1) or was never recorded. If `tag` is given,
	drop rows that still contain the wrapper tag (prevents echo/wrap leakage)."""
	last_idx = last_non_empty_index(contents)
	if last_idx < 0:
		return ''
	rows = [strip(contents.line(i).string).rstrip() for i in range(0, last_idx + 1)]
	if tag:
		rows = [r for r in rows if tag not in r]
	rows = _trim_output_lines(rows)
	return '\n'.join(rows[-lines_cap:])


async def _has_shell_integration(session) -> bool:
	"""Best-effort detection. iTerm2 shell integration sets the user variable
	`user.iterm2_shell_integration_version` on session start. Absence of that
	variable is a strong signal integration isn't loaded in the target session.
	Returns True on error (caller should treat detection as advisory)."""
	try:
		v = await session.async_get_variable('user.iterm2_shell_integration_version')
		return bool(v)
	except Exception:
		return True  # fail-open: don't block run on a probe failure


@cli.command()
@click.argument('cmd', required=False)
@click.option('-t', '--timeout', default=30, type=click.IntRange(min=1), help='Timeout seconds (default: 30)')
@click.option('-n', '--lines', default=50, type=click.IntRange(min=1), help='Output lines to return (default: 50)')
@click.option('--json', 'use_json', is_flag=True)
@click.option('--persist', is_flag=True,
		help="Run in the session's live shell (state persists — cd/env/aliases stay) "
			 "instead of an isolated subshell. GAP-11.")
@click.option('--check-integration', is_flag=True,
		help='Check only — report whether iTerm2 shell integration is active in the target session, then exit.')
@click.option('--stdin', 'stdin_file', default=None, type=click.File('r'),
		help='Read script from file (or - for stdin) and send line by line with small delays.')
@click.option('-s', '--session', 'session_id', default=None)
@click.option('--force', is_flag=True, help='Override protected-session guard.')
def run(cmd, timeout, lines, use_json, persist, check_integration, stdin_file, session_id, force):
	"""Send command, wait for completion, return scoped output and exit code.
	By default the command runs in a subshell so `exit`, `cd`, and env mutations
	stay isolated. Pass `--persist` to run in the session's live shell (state
	persists across invocations — tradeoff: other input in the shell can race
	with the wrapper output, so only use when you actually need state). Exit-code
	capture requires iTerm2 shell integration to be active in the session; pass
	`--check-integration` to verify before relying on it. Without shell integration,
	exit code is always 0 (actual exit status is unavailable). Use `--stdin FILE`
	(or `--stdin -` for stdin) to read a multi-line script and send it line by line
	with small delays to avoid overwhelming the shell."""
	if stdin_file is not None:
		if cmd is not None:
			raise click.UsageError('Cannot pass both CMD and --stdin')
		script_lines = [line.rstrip('\n\r') for line in stdin_file.readlines()]
		stdin_file.close()
		async def _send_script(connection):
			session = await resolve_session(connection, session_id)
			check_protected(session.session_id, force=force)
			for line in script_lines:
				await session.async_send_text(line + '\n')
				await asyncio.sleep(0.05)
		run_iterm(_send_script)
		sys.exit(0)
	if check_integration:
		# Short-circuit: don't execute `cmd`, just probe and report.
		async def _probe(connection):
			session = await resolve_session(connection, session_id)
			return await _has_shell_integration(session)
		active = run_iterm(_probe)
		if use_json:
			click.echo(json.dumps({'shell_integration': bool(active)}))
		else:
			click.echo('active' if active else 'missing')
		sys.exit(0 if active else 1)
	if cmd is None:
		raise click.UsageError('Missing argument CMD (or pass --check-integration).')
	if not cmd.strip():
		raise click.ClickException('run requires a non-empty command (or pass --check-integration)')
	async def _run(connection):
		global _shell_integration_warned
		session = await resolve_session(connection, session_id)
		check_protected(session.session_id, force=force)
		start = time.time()

		# GAP-10: warn early on stderr if shell integration is missing — exit
		# codes won't be delivered and run will have to rely on timeout.
		integration_ok = await _has_shell_integration(session)
		if not integration_ok and not _shell_integration_warned:
			click.echo(
				"ita: warning — iTerm2 shell integration not detected in target "
				"session; exit codes and timeout detection may be unreliable. "
				"See https://iterm2.com/documentation-shell-integration.html",
				err=True,
			)
			_shell_integration_warned = True

		# Tag rides in on the `:` null-command, which takes and discards its
		# arguments — POSIX-universal, no shell options required. zsh's
		# INTERACTIVE_COMMENTS option is off by default, so `#` would break
		# parsing. Spaces inside `( ... )` prevent zsh/bash arithmetic parsing
		# when user's cmd starts with `(`.
		tag = uuid.uuid4().hex[:12]
		# Collapse backslash-newline continuations to avoid zsh subsh> prompt leaking (#83)
		cmd_flat = cmd.replace('\\\n', ' ')
		# --persist runs the command in the caller's live shell (no subshell),
		# so state (cwd, vars, aliases) sticks. The `:` tag line still prefixes
		# the send so output-scoping/echo-row detection keeps working.
		if persist:
			wrapped = f": ita-{tag}; {cmd_flat}"
		else:
			wrapped = f": ita-{tag}; ( {cmd_flat} )"

		# Shell integration delivers COMMAND_END with the exit code. If the session
		# has no shell integration loaded, this times out and exit_code stays None.
		exit_code = None
		timed_out = False
		async with iterm2.PromptMonitor(
				connection, session.session_id,
				modes=[iterm2.PromptMonitor.Mode.COMMAND_END]) as mon:
			await session.async_send_text(wrapped + '\n')
			try:
				mode, payload = await asyncio.wait_for(mon.async_get(), timeout=(min(timeout, 2) if not integration_ok else timeout))
				if mode == iterm2.PromptMonitor.Mode.COMMAND_END and isinstance(payload, int):
					exit_code = payload
			except asyncio.TimeoutError:
				timed_out = True  # no shell integration, or command genuinely timed out
				await session.async_send_text('\x03')  # kill orphaned subshell

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
			# Slice strictly after the echo row. If the command produced no output
			# and the new prompt hasn't re-rendered yet, this is empty — which is
			# the correct answer.
			start_row = echo_row + 1
			end_row = max(start_row, last_idx + 1) if last_idx >= 0 else start_row
			rows = [strip(contents.line(i).string).rstrip() for i in range(start_row, end_row)]
			rows = _trim_output_lines(rows)
			output = '\n'.join(rows[-lines:])
		else:
			# BUG-1: echo row not found — output scrolled past it. Recover from the
			# visible screen. Pass the tag so any wrap-continuation rows still
			# carrying it get dropped.
			output = _fallback_output(contents, lines, tag=tag)

		return output, elapsed_ms, exit_code, timed_out

	output, elapsed_ms, exit_code, timed_out = run_iterm(_run)

	if use_json:
		# 124 is the GNU `timeout` convention for "command timed out".
		# Surface it as an int so consumers can rely on isinstance(exit_code, int).
		json_exit = 124 if timed_out else (exit_code if exit_code is not None else -1)
		click.echo(json.dumps({
			'output': output,
			'elapsed_ms': elapsed_ms,
			'exit_code': json_exit,
			'timed_out': timed_out,
		}))
	else:
		click.echo(output)
		if timed_out:
			click.echo(f"ita: timed out after {timeout}s", err=True)

	# Timeout is always a failure (rc=1). Otherwise propagate the command's own rc.
	if timed_out:
		sys.exit(1)
	if exit_code is not None and exit_code != 0:
		sys.exit(exit_code)


@cli.command()
@click.argument('text')
@click.option('--raw', is_flag=True, help='Do not append newline')
@click.option('-n', '--no-newline', 'no_newline', is_flag=True, help='Do not append newline (alias for --raw)')
@click.option('-s', '--session', 'session_id', default=None)
@click.option('--force', is_flag=True, help='Override protected-session guard.')
def send(text, raw, no_newline, session_id, force):
	"""Send text to session. Appends newline unless --raw or -n.
	Note: Broadcast domains are not honored by send; text is sent directly
	to the target session only. Use 'ita broadcast add' to group sessions
	for coordinated input, then use 'ita key' or 'ita run' for broadcast."""
	async def _run(connection):
		session = await resolve_session(connection, session_id)
		check_protected(session.session_id, force=force)
		await session.async_send_text(text if (raw or no_newline) else text + '\n')
	run_iterm(_run)


@cli.command()
@click.argument('data')
@click.option('--hex', 'is_hex', is_flag=True, help='Interpret DATA as hex bytes')
@click.option('-s', '--session', 'session_id', default=None)
@click.option('--force', is_flag=True, help='Override protected-session guard.')
def inject(data, is_hex, session_id, force):
	"""Inject raw bytes into the terminal emulator's output stream (display side).
	For sending input to a running process (Ctrl+C, arrow keys, etc.) use 'ita key' instead."""
	async def _run(connection):
		session = await resolve_session(connection, session_id)
		check_protected(session.session_id, force=force)
		if is_hex:
			normalized = data.replace(' ', '')
			if not normalized:
				return  # empty hex string is a no-op
			try:
				raw = bytes.fromhex(normalized)
			except ValueError as e:
				raise click.ClickException(
					f"Invalid hex data: {data!r}. Use two-character pairs (e.g. '03' for Ctrl+C).") from e
		else:
			try:
				raw = data.encode('utf-8').decode('unicode_escape').encode('latin-1')
			except (UnicodeDecodeError, UnicodeEncodeError) as e:
				raise click.ClickException(
					f"Cannot encode {data!r}: {e}. "
					f"Use --hex for raw bytes (e.g. `ita inject --hex 71` for 'q')."
				) from e
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
	'f13': '\x1b[25~', 'f14': '\x1b[26~', 'f15': '\x1b[28~', 'f16': '\x1b[29~',
	'f17': '\x1b[31~', 'f18': '\x1b[32~', 'f19': '\x1b[33~',
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
@click.option('--force', is_flag=True, help='Override protected-session guard.')
def key(keys, session_id, force):
	"""Send keystrokes as user input. Use friendly names: ctrl+c, ctrl+d, esc, enter,
	tab, space, backspace, up, down, left, right, home, end, pgup, pgdn, f1-f19.
	Multiple keys are sent in order: 'ita key ctrl+c ctrl+c' sends Ctrl+C twice."""
	try:
		payload = b''.join(_parse_key(k) for k in keys)
	except click.ClickException:
		raise
	async def _run(connection):
		session = await resolve_session(connection, session_id)
		check_protected(session.session_id, force=force)
		# Decode bytes back to a str for async_send_text (it takes text, not raw bytes —
		# iTerm2 internally encodes via the session's terminal encoding).
		await session.async_send_text(payload.decode('latin-1'))
	run_iterm(_run)
