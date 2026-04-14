# src/_events.py
"""Event monitoring and misc commands.

After the #372 split this module owns:
  * the `on` Click group (the parent for all `ita on …` commands)
  * the simpler event waits that don't need their own module:
    `on output`, `on keystroke`, `on focus`, `on layout`
  * the standalone `annotate` and `rpc` commands
  * `_debug_warn`, the shared #316 best-effort logger used by sibling
    event modules

Larger / topical waits live in their own files and import `on` and
`_debug_warn` from here:
  * `_on_prompt.py`  — `on prompt` (the #247 fix lives there)
  * `_on_session.py` — `on session-new` / `on session-end` + UUID parsing
  * `_coprocess.py`  — `coprocess` group
"""
import asyncio
import json
import os
import re
import click
import iterm2
from ._core import cli, run_iterm, resolve_session, last_non_empty_index


def _debug_warn(where: str, exc: BaseException) -> None:
	"""#316: surface swallowed best-effort exceptions when ITA_DEBUG=1.

	These sites (name snapshot, unsubscribe-in-finally) are genuinely
	non-fatal — the primary result is already in hand — but silent `except
	Exception: pass` hid real bugs. Log under ITA_DEBUG so the info is
	reachable without polluting normal stderr.
	"""
	if os.environ.get('ITA_DEBUG') == '1':
		click.echo(f"ita[debug]: {where}: {type(exc).__name__}: {exc}", err=True)


@cli.group()
def on():
	"""One-shot event wait. Blocks until event fires, then exits."""
	pass


@on.command('output')
@click.argument('pattern')
@click.option('-t', '--timeout', default=60, type=int)
@click.option('-s', '--session', 'session_id', default=None)
@click.option('--json', 'use_json', is_flag=True, help='Emit {"line": ...} instead of plain text.')
def on_output(pattern, timeout, session_id, use_json):
	"""Block until PATTERN appears in session output. Returns matching line."""
	try:
		re.compile(pattern)
	except re.error as e:
		raise click.BadParameter(f"Invalid regex pattern: {e}")
	async def _run(connection):
		session = await resolve_session(connection, session_id)
		# Snapshot current screen first to avoid race condition (#86)
		contents = await session.async_get_screen_contents()
		for i in range(contents.number_of_lines):
			line = contents.line(i).string.replace('\x00', '')
			if re.search(pattern, line):
				return line
		async def _wait():
			async with session.get_screen_streamer() as streamer:
				while True:
					contents = await streamer.async_get()
					for i in range(contents.number_of_lines):
						line = contents.line(i).string.replace('\x00', '')
						if re.search(pattern, line):
							return line
		try:
			return await asyncio.wait_for(_wait(), timeout=timeout)
		except asyncio.TimeoutError:
			raise click.ClickException(f"Timeout: pattern {pattern!r} not found in {timeout}s")
	result = run_iterm(_run)
	if use_json:
		click.echo(json.dumps({'line': result}, ensure_ascii=False))
	else:
		click.echo(result)


@on.command('keystroke')
@click.argument('pattern')
@click.option('-t', '--timeout', default=60, type=int)
@click.option('-s', '--session', 'session_id', default=None)
@click.option('--json', 'use_json', is_flag=True, help='Emit {"chars": ...} instead of plain text.')
def on_keystroke(pattern, timeout, session_id, use_json):
	"""Block until a keystroke matching PATTERN (regex) is pressed. Prints the matched characters."""
	try:
		re.compile(pattern)
	except re.error as e:
		raise click.BadParameter(f"Invalid regex pattern: {e}")
	async def _run(connection):
		session = await resolve_session(connection, session_id)
		rx = re.compile(pattern)
		loop = asyncio.get_running_loop()
		deadline = loop.time() + timeout
		async with iterm2.KeystrokeMonitor(connection, session.session_id) as mon:
			while True:
				remaining = deadline - loop.time()
				if remaining <= 0:
					raise click.ClickException(
						f"Timeout: no keystroke matched {pattern!r} in {timeout}s")
				try:
					ks = await asyncio.wait_for(mon.async_get(), timeout=remaining)
				except asyncio.TimeoutError:
					raise click.ClickException(
						f"Timeout: no keystroke matched {pattern!r} in {timeout}s")
				chars = getattr(ks, 'characters', '') or ''
				if rx.search(chars):
					return chars
	result = run_iterm(_run)
	if use_json:
		click.echo(json.dumps({'chars': result}, ensure_ascii=False))
	else:
		click.echo(result)


@on.command('focus')
@click.option('-t', '--timeout', default=30, type=int)
@click.option('--json', 'use_json', is_flag=True, help='Emit {"event": ...} instead of plain text.')
def on_focus(timeout, use_json):
	"""Block until keyboard focus changes."""
	async def _run(connection):
		async with iterm2.FocusMonitor(connection) as m:
			try:
				update = await asyncio.wait_for(m.async_get_next_update(), timeout=timeout)
				return str(update)
			except asyncio.TimeoutError:
				raise click.ClickException(f"Timed out waiting for focus change after {timeout}s")
	result = run_iterm(_run)
	if use_json:
		click.echo(json.dumps({'event': result}, ensure_ascii=False))
	else:
		click.echo(result)


@on.command('layout')
@click.option('-t', '--timeout', default=30, type=int)
@click.option('--json', 'use_json', is_flag=True, help='Emit {"event": ...} instead of plain text.')
def on_layout(timeout, use_json):
	"""Block until window/tab/pane layout changes."""
	async def _run(connection):
		q = asyncio.Queue()
		async def cb(connection):
			await q.put(True)
		token = await iterm2.notifications.async_subscribe_to_layout_change_notification(
			connection, cb)
		try:
			await asyncio.wait_for(q.get(), timeout=timeout)
			return "layout changed"
		except asyncio.TimeoutError:
			raise click.ClickException(f"Timed out waiting for layout change after {timeout}s")
		finally:
			# #316: cleanup-path unsubscribe; see on_session_end for rationale.
			try:
				await iterm2.notifications.async_unsubscribe(connection, token)
			except (RuntimeError, ConnectionError, AttributeError) as exc:
				_debug_warn('on_layout: unsubscribe failed', exc)
	result = run_iterm(_run)
	if use_json:
		click.echo(json.dumps({'event': result}, ensure_ascii=False))
	else:
		click.echo(result)


# ── Standalone commands ────────────────────────────────────────────────────

@cli.command()
@click.argument('text')
@click.option('--range', 'range_', nargs=2, type=int, default=None,
			  help='Column range as two ints: START END (default: 0 80).')
@click.option('--start', 'range_start', type=int, default=None,
			  help='Column start position (deprecated: use --range START END).')
@click.option('--end', 'range_end', type=int, default=None,
			  help='Column end position (deprecated: use --range START END).')
@click.option('-s', '--session', 'session_id', default=None)
def annotate(text, range_, range_start, range_end, session_id):
	"""Add annotation to screen content."""
	if range_:
		start, end = range_
	else:
		start = range_start if range_start is not None else 0
		end = range_end if range_end is not None else 80
	if start > end:
		raise click.ClickException(f"range start ({start}) must be <= end ({end})")

	async def _run(connection):
		session = await resolve_session(connection, session_id)
		contents = await session.async_get_screen_contents()
		n = last_non_empty_index(contents)
		if n < 0:
			n = contents.number_of_lines - 1
		coord_range = iterm2.util.CoordRange(
			iterm2.util.Point(start, n),
			iterm2.util.Point(end, n))
		await session.async_add_annotation(coord_range, text)
	run_iterm(_run)


@cli.command()
@click.argument('invocation')
@click.option('-s', '--session', 'session_id', default=None)
def rpc(invocation, session_id):
	"""Invoke an RPC function in session context."""
	async def _run(connection):
		session = await resolve_session(connection, session_id)
		return await session.async_invoke_function(invocation)
	result = run_iterm(_run)
	if result is not None:
		click.echo(result)
