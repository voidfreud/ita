# src/_send.py
"""Input commands: run (atomic), send, inject, key.
File is named _send.py rather than _io.py to avoid collision with Python's built-in _io module."""
import asyncio
import sys
import time
import uuid
import click
import iterm2
from ._core import (cli, run_iterm, resolve_session, strip, PROMPT_CHARS,
	last_non_empty_index, check_protected, session_writelock, _is_prompt_line)
from ._envelope import ita_command, ItaError, json_dumps
from ._lock import resolve_force_flags


def _force_options(f):
	"""Decorator stacking --force-protected / --force-lock / --force (deprecated).

	Commands resolve the triple via `resolve_force_flags()` at call time."""
	f = click.option('--force', is_flag=True, hidden=True,
		help='DEPRECATED: use --force-protected and/or --force-lock (#294).')(f)
	f = click.option('--force-lock', is_flag=True,
		help='Override write-lock guard; reclaim from another live ita process (#294).')(f)
	f = click.option('--force-protected', is_flag=True,
		help='Override protected-session guard (#294).')(f)
	return f


def _trim_output_lines(lines: list[str]) -> list[str]:
	"""Drop trailing prompt/blank rows. Preserve content (CONTRACT §3, §9, #331).

	A trailing row that IS a bare prompt (per `_is_prompt_line`) is dropped —
	that's a freshly-rendered prompt below the command output. A content row
	that merely ends in a prompt character (e.g. `"cost: $"`, `"price: 5%"`)
	is CONTENT and MUST be kept verbatim: stripping the tail char there
	erased real data (#331).
	"""
	out = list(lines)
	# Drop trailing blanks first so a `[..., '$', '']` shape collapses.
	while out and not out[-1].strip():
		out.pop()
	# Drop a trailing bare-prompt row if one rendered after the output.
	if out and _is_prompt_line(out[-1]):
		out.pop()
	# Drop any blanks re-exposed by the prompt pop, plus leading blanks.
	while out and not out[-1].strip():
		out.pop()
	while out and not out[0].strip():
		out.pop(0)
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


async def _prompt_is_back(session) -> bool:
	"""True if the last non-empty screen row looks like a shell prompt —
	used after sending an interrupt to decide whether the foreground
	process has released control back to the shell. Best-effort: any
	screen-read failure is treated as 'still hung' so escalation proceeds."""
	try:
		contents = await session.async_get_screen_contents()
		last = last_non_empty_index(contents)
		if last < 0:
			return False
		return _is_prompt_line(strip(contents.line(last).string))
	except Exception:
		return False


async def _escalate_interrupt(session) -> bool:
	"""#175: interrupt ladder after a `run` timeout.

	Step 1: Ctrl+C. Wait ~1s for the prompt to come back.
	Step 2: Ctrl+U (clear any partial input) + Ctrl+C again. Wait ~1s.
	Step 3: `kill %% 2>/dev/null; kill -9 %% 2>/dev/null` sent as a shell
		command — targets the most-recent background/suspended job. Last
		resort when the foreground process has ignored SIGINT entirely.

	Returns True if we escalated past step 1 (caller surfaces this in JSON
	and stderr so users know the session may be in an unusual state)."""
	# Step 1: standard Ctrl+C.
	await session.async_send_text('\x03')
	await asyncio.sleep(1.0)
	if await _prompt_is_back(session):
		return False
	# Step 2: clear input line (a partial prompt can swallow the next ^C),
	# then send ^C again. This handles cases where the first Ctrl+C landed
	# inside a prompt that had leftover characters.
	await session.async_send_text('\x15')  # Ctrl+U: kill input line
	await asyncio.sleep(0.2)
	await session.async_send_text('\x03')
	await asyncio.sleep(1.0)
	if await _prompt_is_back(session):
		return True
	# Step 3: last resort — send explicit kill commands targeting the current
	# job (%%). If the shell is responsive at all, this will land; if the
	# shell itself is wedged, nothing here will help and we exit gracefully.
	await session.async_send_text('\x15')
	await asyncio.sleep(0.1)
	await session.async_send_text('kill %% 2>/dev/null; kill -9 %% 2>/dev/null\n')
	await asyncio.sleep(0.5)
	return True


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
@click.option('--tail', 'tail_n', default=None, type=click.IntRange(min=1),
		help='Truncate output to last N lines. Prepends [truncated: X lines] when output was cut. (#126)')
@click.option('--json', 'use_json', is_flag=True)
@click.option('--persist', is_flag=True,
		help="Run in the session's live shell (state persists — cd/env/aliases stay) "
			 "instead of an isolated subshell. GAP-11.")
@click.option('--check-integration', is_flag=True,
		help='Check only — report whether iTerm2 shell integration is active in the target session, then exit.')
@click.option('--stdin', 'stdin_file', default=None, type=click.File('r'),
		help='Read multi-line script from file (or - for stdin), run as one unit via bash -s heredoc, '
			 'capture exit code of last command. (#137)')
@click.option('-s', '--session', 'session_id', default=None)
@_force_options
@ita_command(op='run')
def run(cmd, timeout, lines, tail_n, use_json, persist, check_integration, stdin_file, session_id,
		force_protected, force_lock, force):
	"""Send command, wait for completion, return scoped output and exit code.
	By default the command runs in a subshell so `exit`, `cd`, and env mutations
	stay isolated. Pass `--persist` to run in the session's live shell (state
	persists across invocations — tradeoff: other input in the shell can race
	with the wrapper output, so only use when you actually need state). Exit-code
	capture requires iTerm2 shell integration to be active in the session; pass
	`--check-integration` to verify before relying on it. Without shell integration,
	exit code is always 0 (actual exit status is unavailable). Use `--stdin FILE`
	(or `--stdin -` for stdin) to run a multi-line script as a single unit
	(exit code of the last command). `--tail N` truncates output to the last N
	lines with a truncation notice — useful for long test/build output.
	On timeout the process exits 124 (GNU timeout convention); --json envelope
	also reports exit_code=124."""
	# #137: stdin synthesizes `cmd` from a multi-line script, then falls through
	# to the regular run pipeline so exit-code capture, timeout, and output
	# scoping all work identically. Heredoc delimiter is uniquified below using
	# the same tag we generate for echo-row detection.
	stdin_script = None
	if stdin_file is not None:
		if cmd is not None:
			raise click.UsageError('Cannot pass both CMD and --stdin')
		stdin_script = stdin_file.read().rstrip('\n\r')
		stdin_file.close()
		if not stdin_script.strip():
			raise click.ClickException('--stdin received empty script')
	if check_integration:
		# Short-circuit: don't execute `cmd`, just probe and report.
		async def _probe(connection):
			session = await resolve_session(connection, session_id)
			return await _has_shell_integration(session)
		active = run_iterm(_probe)
		if use_json:
			click.echo(json_dumps({'shell_integration': bool(active)}))
		else:
			click.echo('active' if active else 'missing')
		sys.exit(0 if active else 1)
	if cmd is None and stdin_script is None:
		raise click.UsageError('Missing argument CMD (or pass --stdin / --check-integration).')
	if cmd is not None and not cmd.strip():
		raise click.ClickException('run requires a non-empty command (or pass --check-integration)')
	fp, fl = resolve_force_flags(force, force_protected, force_lock)
	async def _run(connection):
		session = await resolve_session(connection, session_id)
		check_protected(session.session_id, force_protected=fp)
		# Writelock held for the whole send+await-completion window so a
		# second ita can't interleave input before this command finishes.
		with session_writelock(session.session_id, force_lock=fl):
			return await _run_inner(connection, session)

	async def _run_inner(connection, session):
		start = time.time()

		# #144 / #145: detect shell integration so we can (a) shorten the
		# PromptMonitor timeout when missing and (b) surface the state in JSON
		# (shell_integration + exit_code=null) so callers distinguish "exit 0"
		# from "exit code unavailable". No per-call stderr warning — `ita
		# doctor` is the single source of integration status, so agents don't
		# get 20 copies of the same warning across a session.
		integration_ok = await _has_shell_integration(session)

		# Tag rides in on the `:` null-command, which takes and discards its
		# arguments — POSIX-universal, no shell options required. zsh's
		# INTERACTIVE_COMMENTS option is off by default, so `#` would break
		# parsing. Spaces inside `( ... )` prevent zsh/bash arithmetic parsing
		# when user's cmd starts with `(`.
		tag = uuid.uuid4().hex[:12]
		# #137: stdin script runs as a single bash -s invocation fed via heredoc.
		# Delimiter is tag-derived so user content can't terminate it early.
		# Exit code of the last command in the script becomes the invocation's
		# exit code (bash default). Runs on one line of sent text — embedded
		# newlines in the heredoc are part of the text we send, and the shell
		# treats the whole thing as a single compound command.
		if stdin_script is not None:
			eof = f"ITA_{tag}_EOF"
			# The heredoc body is sent verbatim; bash reads until the delimiter.
			# `bash -s` reads the script from stdin; the subshell wrapping is
			# implicit (bash -s itself is the isolated process), so --persist
			# doesn't change structure here — but we still respect the flag by
			# choosing whether to fork a subshell around it.
			inner = f"bash -s <<'{eof}'\n{stdin_script}\n{eof}"
			if persist:
				wrapped = f": ita-{tag}; {inner}"
			else:
				wrapped = f": ita-{tag}; ( {inner} )"
		else:
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
		escalated = False
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
				# #175: escalation ladder — Ctrl+C is not enough for processes
				# that ignore SIGINT (editors, some REPLs). After each signal,
				# check whether the prompt returned; only escalate if still hung.
				escalated = await _escalate_interrupt(session)

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
			output_rows = rows[-lines:]
		else:
			# BUG-1: echo row not found — output scrolled past it. Recover from the
			# visible screen. Pass the tag so any wrap-continuation rows still
			# carrying it get dropped.
			fallback = _fallback_output(contents, lines, tag=tag)
			output_rows = fallback.split('\n') if fallback else []
			click.echo('⚠ output may be incomplete — echo row scrolled off screen', err=True)

		# #126: explicit --tail N overrides the default lines cap. #248:
		# the truncation notice does NOT go on stdout (that breaks `run -n N`'s
		# N-line contract). Plain mode surfaces it on stderr; JSON mode
		# exposes `data.truncated_from` instead.
		truncated_from = None
		if tail_n is not None and len(output_rows) > tail_n:
			truncated_from = len(output_rows)
			output_rows = output_rows[-tail_n:]

		output = '\n'.join(output_rows)

		return output, elapsed_ms, exit_code, timed_out, integration_ok, escalated, truncated_from

	output, elapsed_ms, exit_code, timed_out, integration_ok, escalated, truncated_from = run_iterm(_run)

	# Resolve target session id for envelope (re-resolve cheaply via params;
	# the body already proved it exists, so this is best-effort).
	target = {"session": session_id} if session_id else None

	if use_json:
		# CONTRACT §6: timeout -> rc=4. The decorator turns ItaError into
		# the envelope's error block + maps to EXIT_CODES['timeout']=4. The
		# inner command's own exit_code rides in `data.exit_code` (may be
		# null when shell integration is missing — preserved from #144).
		if timed_out:
			raise ItaError("timeout",
				f"timed out after {timeout}s" +
				(" (escalated past Ctrl+C)" if escalated else ""))
		return {
			"target": target,
			"state_before": "ready",
			"state_after": "ready",
			"data": {
				"output": output,
				"elapsed_ms": elapsed_ms,
				"exit_code": exit_code,
				"timed_out": timed_out,
				"escalated": bool(escalated),
				"shell_integration": bool(integration_ok),
				"truncated_from": truncated_from,
			},
		}

	# Plain mode: preserve the original UX exactly — output to stdout,
	# inner-rc propagation to ita's exit code (124 on timeout, otherwise
	# the inner command's rc). The decorator stays silent on success in
	# plain mode, so this echo path is unchanged from pre-decorator.
	# Documented divergence: plain-mode timeout exits 124 (GNU timeout
	# convention) while --json emits §6 timeout (rc=4). Plain-mode
	# migration to rc=4 is queued for a follow-up PR; see CONTRACT §6
	# amendment in this PR.
	click.echo(output)
	if truncated_from is not None:
		# #248: notice lives on stderr so stdout stays at exactly `lines` rows.
		click.echo(f"ita: truncated from {truncated_from} lines", err=True)
	if timed_out:
		suffix = ' (escalated past Ctrl+C)' if escalated else ''
		click.echo(f"ita: timed out after {timeout}s{suffix}", err=True)
		sys.exit(124)
	if exit_code is not None and exit_code != 0:
		sys.exit(exit_code)
	return None


@cli.command()
@click.argument('text')
@click.option('--raw', is_flag=True, help='Do not append newline')
@click.option('-n', '--no-newline', 'no_newline', is_flag=True, help='Do not append newline (alias for --raw)')
@click.option('-s', '--session', 'session_id', default=None)
@_force_options
def send(text, raw, no_newline, session_id, force_protected, force_lock, force):
	"""Send text to session. Appends newline unless --raw or -n.
	Note: Broadcast domains are not honored by send; text is sent directly
	to the target session only. Use 'ita broadcast add' to group sessions
	for coordinated input, then use 'ita key' or 'ita run' for broadcast."""
	fp, fl = resolve_force_flags(force, force_protected, force_lock)
	async def _run(connection):
		session = await resolve_session(connection, session_id)
		check_protected(session.session_id, force_protected=fp)
		with session_writelock(session.session_id, force_lock=fl):
			await session.async_send_text(text if (raw or no_newline) else text + '\n')
	run_iterm(_run)


@cli.command()
@click.argument('data')
@click.option('--hex', 'is_hex', is_flag=True, help='Interpret DATA as hex bytes')
@click.option('-s', '--session', 'session_id', default=None)
@_force_options
def inject(data, is_hex, session_id, force_protected, force_lock, force):
	"""Inject raw bytes into the terminal emulator's output stream (display side).
	For sending input to a running process (Ctrl+C, arrow keys, etc.) use 'ita key' instead."""
	fp, fl = resolve_force_flags(force, force_protected, force_lock)
	async def _run(connection):
		session = await resolve_session(connection, session_id)
		check_protected(session.session_id, force_protected=fp)
		# acquire writelock before encoding so a concurrent write sees the lock
		# immediately (encoding may raise — that's fine, __exit__ releases).
		with session_writelock(session.session_id, force_lock=fl):
			await _inject_impl(session, data, is_hex)

	async def _inject_impl(session, data, is_hex):
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
				raw = data.encode('utf-8')
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
@_force_options
def key(keys, session_id, force_protected, force_lock, force):
	"""Send keystrokes as user input. Use friendly names: ctrl+c, ctrl+d, esc, enter,
	tab, space, backspace, up, down, left, right, home, end, pgup, pgdn, f1-f19.
	Multiple keys are sent in order: 'ita key ctrl+c ctrl+c' sends Ctrl+C twice."""
	try:
		payload = b''.join(_parse_key(k) for k in keys)
	except click.ClickException:
		raise
	fp, fl = resolve_force_flags(force, force_protected, force_lock)
	async def _run(connection):
		session = await resolve_session(connection, session_id)
		check_protected(session.session_id, force_protected=fp)
		with session_writelock(session.session_id, force_lock=fl):
			# Decode bytes back to a str for async_send_text (it takes text, not raw bytes —
			# iTerm2 internally encodes via the session's terminal encoding).
			await session.async_send_text(payload.decode('latin-1'))
	run_iterm(_run)
