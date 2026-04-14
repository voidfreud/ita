# src/_probe.py
"""Session probes and output scoping helpers used by `ita run`.

Houses:
- `_has_shell_integration` — iTerm2 shell-integration detection (fail-closed).
- `_prompt_is_back` / `_escalate_interrupt` — the post-timeout Ctrl+C ladder.
- `_trim_output_lines` — trailing-prompt / blank-row scrubber for captured output.

Separated from `_send.py` so the `run` pipeline can consume them without pulling
in `send`/`inject`/`key` surface, and vice versa."""
import asyncio
import click
from ._core import strip, last_non_empty_index, _is_prompt_line


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

	Fail-closed (#234): on any probe exception we return False. Claiming
	integration exists when the probe itself failed would silently swallow
	exit codes (agents would see `exit_code=null` with `shell_integration=
	true`, an impossible combination). False is the safe advisory value —
	the caller then uses the no-integration code path and surfaces
	`shell_integration=false` honestly. A one-line debug warning is emitted
	to stderr so the failure isn't fully invisible."""
	try:
		v = await session.async_get_variable('user.iterm2_shell_integration_version')
		return bool(v)
	except Exception as e:
		click.echo(f"ita: shell-integration probe failed ({type(e).__name__}): "
			f"treating as missing", err=True)
		return False
