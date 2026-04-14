# src/_run.py
"""`ita run` — send a command, wait for COMMAND_END, return scoped output + rc.

Owns the full run pipeline: optional `--stdin` script assembly, the `:` tag
wrapper for echo-row detection, COMMAND_END polling with a no-integration
timeout clamp (#326), the post-timeout interrupt ladder (#175), output scoping
to the row after the echo, and the --persist settle (#324).

Split out of `_send.py` so the 200+ LOC run logic has its own roof and the rest
of the input-command surface stays small."""
import asyncio
import sys
import time
import uuid
import click
import iterm2
from ._core import (cli, run_iterm, resolve_session, strip, last_non_empty_index,
	check_protected, session_writelock)
from ._envelope import ita_command, ItaError, json_dumps
from ._lock import resolve_force_flags
from ._force import _force_options
from ._probe import _has_shell_integration, _escalate_interrupt, _trim_output_lines
from ._stdin import _load_stdin_script


def _build_wrapped_command(cmd: str | None, stdin_script: str | None,
		persist: bool, tag: str) -> str:
	"""Assemble the full text sent to the session for `ita run`.

	The `:` null-command carries our unique `tag` so output scoping can find
	the echo row; `(...)` isolates a subshell (unless `--persist`). When
	`--stdin` is in play we wrap `bash -s <<EOF ... EOF` with a tag-derived
	heredoc delimiter so user content can't close it early (#137)."""
	if stdin_script is not None:
		eof = f"ITA_{tag}_EOF"
		# The heredoc body is sent verbatim; bash reads until the delimiter.
		# `bash -s` is itself the isolated process, so --persist doesn't
		# change isolation — only whether we additionally fork a subshell.
		inner = f"bash -s <<'{eof}'\n{stdin_script}\n{eof}"
		return f": ita-{tag}; {inner}" if persist else f": ita-{tag}; ( {inner} )"
	# Collapse backslash-newline continuations to avoid zsh subsh> prompt leak (#83)
	cmd_flat = (cmd or '').replace('\\\n', ' ')
	return f": ita-{tag}; {cmd_flat}" if persist else f": ita-{tag}; ( {cmd_flat} )"


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
@click.option('--stdin', 'stdin_path', default=None, type=str,
		help='Read multi-line script from FILE (or - for stdin), run as one unit via bash -s heredoc, '
			 'capture exit code of last command. Path must resolve under CWD unless '
			 '--stdin-allow-outside-cwd is passed (#137, #325).')
@click.option('--stdin-allow-outside-cwd', 'stdin_allow_outside_cwd', is_flag=True,
		help='Permit --stdin to read a file whose realpath resolves outside the caller\'s CWD. '
			 'Explicit, agent-side opt-in; off by default (#325, CONTRACT §14.4).')
@click.option('-s', '--session', 'session_id', default=None)
@_force_options
@ita_command(op='run')
def run(cmd, timeout, lines, tail_n, use_json, persist, check_integration, stdin_path,
		stdin_allow_outside_cwd, session_id,
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
	if stdin_path is not None:
		if cmd is not None:
			raise click.UsageError('Cannot pass both CMD and --stdin')
		# #325: validate path BEFORE reading. Traversal / outside-CWD paths
		# are rejected as bad-args (rc=6) with a clear message. CONTRACT §14.4.
		stdin_script = _load_stdin_script(stdin_path, stdin_allow_outside_cwd).rstrip('\n\r')
		if not stdin_script.strip():
			raise ItaError("bad-args", "--stdin received empty script")
	elif stdin_allow_outside_cwd:
		raise ItaError("bad-args",
			"--stdin-allow-outside-cwd requires --stdin (#325)")
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

		# Tag rides in on the `:` null-command — POSIX-universal, no shell
		# options required. zsh's INTERACTIVE_COMMENTS is off by default so
		# `#` would break parsing. See `_build_wrapped_command` for shape.
		tag = uuid.uuid4().hex[:12]
		wrapped = _build_wrapped_command(cmd, stdin_script, persist, tag)

		# Shell integration delivers COMMAND_END with the exit code. If the session
		# has no shell integration loaded, this times out and exit_code stays None.
		exit_code = None
		timed_out = False
		escalated = False
		async with iterm2.PromptMonitor(
				connection, session.session_id,
				modes=[iterm2.PromptMonitor.Mode.COMMAND_END]) as mon:
			await session.async_send_text(wrapped + '\n')
			# #326: without shell integration, COMMAND_END never fires — waiting
			# the full user timeout would stall the caller needlessly, so we clamp
			# the poll to 2s and return without an exit code. The command keeps
			# running in the session; we just can't observe completion. Critically,
			# we DO NOT run the interrupt ladder in that case — killing a healthy
			# long-running process (make build, pip install, REPL) is the bug.
			effective_timeout = timeout if integration_ok else min(timeout, 2)
			try:
				mode, payload = await asyncio.wait_for(mon.async_get(), timeout=effective_timeout)
				if mode == iterm2.PromptMonitor.Mode.COMMAND_END and isinstance(payload, int):
					exit_code = payload
			except asyncio.TimeoutError:
				if integration_ok:
					# Real timeout: COMMAND_END was expected and didn't arrive.
					timed_out = True
					# #175: escalation ladder — Ctrl+C isn't enough for processes
					# that ignore SIGINT (editors, some REPLs). After each signal,
					# check whether the prompt returned; only escalate if still hung.
					escalated = await _escalate_interrupt(session)
				# else (#326): no-integration clamp expired. Leave timed_out=False,
				# exit_code=None. Callers read `shell_integration: false` +
				# `exit_code: null` as "command dispatched, completion unobservable."

		# #324: --persist runs in the live shell, so command output races with
		# any in-flight input the user/agent may interleave. The writelock bars
		# ita-vs-ita races, but not shell-side typing. Add a brief settle before
		# the screen read so trailing output rows land inside the capture window.
		# This is a runtime guard — the prior code only documented the risk.
		if persist:
			await asyncio.sleep(0.2)

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
			# #317: echo row not found — we can't reliably scope output to this
			# command. Previously we warned on stderr but returned rc=0 with a
			# best-effort fallback, which violates CONTRACT §14.1 (must not
			# report success when the observable effect is incomplete). Fail
			# loud with rc=2 / not-found so the caller doesn't mistake a
			# degraded capture for a successful run.
			raise ItaError("not-found",
				"run echo row not found — output could not be reliably scoped "
				"(the command may have scrolled off-screen, or the session was "
				"disturbed mid-capture)")

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
