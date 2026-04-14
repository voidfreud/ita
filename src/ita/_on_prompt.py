"""`ita on prompt` — block until the next shell prompt appears.

Split out of `_events.py` (#372). The wait/timeout logic here is the
#247 fix: silent timeout becomes a structured §4/§6 error with rc=4
(CONTRACT §14.1). For --json callers we also emit a parseable hint on
stderr so agents see elapsed_ms before Click renders the ItaError.
"""
import asyncio
import json
import click
from ._core import run_iterm, resolve_session, strip, PROMPT_CHARS, last_non_empty_index
from ._envelope import ItaError
from ._events import on


@on.command('prompt')
@click.option('-t', '--timeout', default=60, type=int)
@click.option('-s', '--session', 'session_id', default=None)
@click.option('--json', 'use_json', is_flag=True, help='Emit {"line": ...} instead of plain text.')
def on_prompt(timeout, session_id, use_json):
	"""Block until next shell prompt appears."""
	async def _run(connection):
		t0 = asyncio.get_running_loop().time()
		session = await resolve_session(connection, session_id)
		contents = await session.async_get_screen_contents()
		last_idx = last_non_empty_index(contents)
		if last_idx >= 0:
			last = strip(contents.line(last_idx).string).strip()
			if any(last.startswith(p) or last.endswith(p) for p in PROMPT_CHARS):
				return (True, last, int((asyncio.get_running_loop().time() - t0) * 1000))
		async with session.get_screen_streamer() as streamer:
			for _ in range(timeout):
				try:
					contents = await asyncio.wait_for(streamer.async_get(), timeout=1.0)
					last_idx = last_non_empty_index(contents)
					if last_idx < 0:
						continue
					last = strip(contents.line(last_idx).string).strip()
					if any(last.startswith(p) or last.endswith(p) for p in PROMPT_CHARS):
						return (True, last, int((asyncio.get_running_loop().time() - t0) * 1000))
				except asyncio.TimeoutError:
					continue
		elapsed_ms = int((asyncio.get_running_loop().time() - t0) * 1000)
		return (False, None, elapsed_ms)
	matched, result, elapsed_ms = run_iterm(_run)
	if matched:
		if use_json:
			click.echo(json.dumps({'line': result}, ensure_ascii=False))
		else:
			click.echo(result)
	else:
		# #247: silent timeout → structured §4/§6 error, rc=4 (CONTRACT §14.1).
		# For --json callers also emit a parseable hint on stderr so agents see
		# elapsed_ms before Click renders the ItaError. The ItaError itself
		# drives the exit code and the stderr `Error:` line in plain mode.
		if use_json:
			click.echo(
				json.dumps({'matched': False, 'reason': 'timeout', 'elapsed_ms': elapsed_ms},
				ensure_ascii=False),
				err=True,
			)
		raise ItaError('timeout', f"no prompt appeared within {timeout}s")
