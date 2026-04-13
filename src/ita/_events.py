# src/_events.py
"""Event monitoring and advanced commands: on group, coprocess, annotate, rpc."""
import asyncio
import json
import os
import re
import click
import iterm2
from ._core import cli, run_iterm, resolve_session, strip, PROMPT_CHARS, last_non_empty_index
from ._envelope import ItaError


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


_UUID_RE = re.compile(r'[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}')


def _extract_uuid(payload) -> str | None:
	"""Pull a 36-char UUID out of whatever the iTerm2 new-session API returns.
	The payload may be a str, a NewSessionNotification proto, a dict, or
	something with a .session_id attribute. Different iTerm2 versions wrap the
	id in quotes, prefix it with `s:` / `w:`, or hand back the raw proto."""
	if payload is None:
		return None
	# Unwrap common shapes first
	candidates = [payload]
	sid_attr = getattr(payload, 'session_id', None)
	if sid_attr is not None:
		candidates.append(sid_attr)
	if isinstance(payload, dict):
		for k in ('session_id', 'sessionId', 'id'):
			if k in payload:
				candidates.append(payload[k])
	# Regex-sweep stringified forms
	for c in candidates:
		if c is None:
			continue
		s = c if isinstance(c, str) else str(c)
		m = _UUID_RE.search(s)
		if m:
			return m.group(0)
	return None


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


@on.command('session-new')
@click.option('-t', '--timeout', default=30, type=int)
@click.option('--json', 'use_json', is_flag=True, help='Emit {"session_id": ..., "name": ...} instead of plain text.')
def on_session_new(timeout, use_json):
	"""Block until a new session is created (any session). Emits `UUID\\tNAME`
	when the session name is resolvable, otherwise just `UUID` (#131)."""
	async def _run(connection):
		try:
			async with iterm2.NewSessionMonitor(connection) as mon:
				raw = await asyncio.wait_for(mon.async_get(), timeout=timeout)
		except asyncio.TimeoutError:
			raise click.ClickException(f"Timed out waiting for new session after {timeout}s")
		uuid = _extract_uuid(raw)
		if not uuid:
			raise click.ClickException(
				f"Could not extract UUID from new-session payload: {raw!r}")
		# Best-effort name resolution — session may not be fully registered yet.
		# #316: narrowed — AttributeError (proto shape change), RuntimeError
		# (connection hiccup), iterm2 RPC errors. Genuinely non-fatal: we
		# already have the UUID. Surface under ITA_DEBUG.
		name = ''
		try:
			app = await iterm2.async_get_app(connection)
			s = app.get_session_by_id(uuid)
			if s is not None:
				name = strip(s.name or '')
		except (AttributeError, RuntimeError, ConnectionError) as exc:
			_debug_warn('on_session_new: name lookup failed', exc)
		return (uuid, name)
	uuid, name = run_iterm(_run)
	if use_json:
		click.echo(json.dumps({'session_id': uuid, 'name': name}, ensure_ascii=False))
	else:
		click.echo(f"{uuid}\t{name}" if name else uuid)


@on.command('session-end')
@click.option('-t', '--timeout', default=60, type=int)
@click.option('-s', '--session', 'session_id', default=None,
			  help='Filter to a specific session (default: any session ending).')
@click.option('--json', 'use_json', is_flag=True, help='Emit {"session_id": ..., "name": ...} instead of plain text.')
def on_session_end(timeout, session_id, use_json):
	"""Block until a session terminates. Without -s, fires on ANY session
	ending (#131). Emits `UUID\\tNAME` when the name was known before
	termination, otherwise just `UUID`."""
	async def _run(connection):
		target = session_id
		# Snapshot names BEFORE termination — the session object is usually
		# gone by the time the terminate notification fires.
		name_map = {}
		try:
			app = await iterm2.async_get_app(connection)
			for w in app.terminal_windows:
				for t in w.tabs:
					for s in t.sessions:
						name_map[s.session_id] = strip(s.name or '')
		except (AttributeError, RuntimeError, ConnectionError) as exc:
			# #316: partial snapshot is acceptable — terminate notifications
			# still fire with the UUID; names are a nice-to-have.
			_debug_warn('on_session_end: name snapshot failed', exc)
		q = asyncio.Queue()
		async def cb(connection, notification):
			sid = notification.session_id
			if not target or sid == target:
				await q.put(sid)
		token = await iterm2.notifications.async_subscribe_to_terminate_session_notification(
			connection, cb)
		try:
			sid = await asyncio.wait_for(q.get(), timeout=timeout)
			name = name_map.get(sid, '')
			return (sid, name)
		except asyncio.TimeoutError:
			raise click.ClickException(f"Timed out waiting for session termination after {timeout}s")
		finally:
			# #316: unsubscribe runs after the primary result is in hand.
			# Connection may already be closing; swallowing narrowly is OK.
			try:
				await iterm2.notifications.async_unsubscribe(connection, token)
			except (RuntimeError, ConnectionError, AttributeError) as exc:
				_debug_warn('on_session_end: unsubscribe failed', exc)
	sid, name = run_iterm(_run)
	if use_json:
		click.echo(json.dumps({'session_id': sid, 'name': name}, ensure_ascii=False))
	else:
		click.echo(f"{sid}\t{name}" if name else sid)


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


# ── Advanced ───────────────────────────────────────────────────────────────

@cli.group()
def coprocess():
	"""Attach a subprocess to session I/O."""
	pass


@coprocess.command('start')
@click.argument('cmd')
@click.option('-s', '--session', 'session_id', default=None)
def coprocess_start(cmd, session_id):
	"""Start coprocess connected to session stdin/stdout."""
	async def _run(connection):
		session = await resolve_session(connection, session_id)
		existing = await session.async_get_coprocess()
		if existing:
			raise click.ClickException("A coprocess is already attached to this session. Stop it first with 'ita coprocess stop'.")
		await session.async_run_coprocess(cmd)
		coprocess = await session.async_get_coprocess()
		if coprocess and hasattr(coprocess, 'pid'):
			return f"PID {coprocess.pid}"
		return "Coprocess started"
	result = run_iterm(_run)
	click.echo(result)


@coprocess.command('stop')
@click.option('-s', '--session', 'session_id', default=None)
def coprocess_stop(session_id):
	"""Stop running coprocess."""
	async def _run(connection):
		session = await resolve_session(connection, session_id)
		existing = await session.async_get_coprocess()
		if not existing:
			raise click.ClickException("No coprocess is attached to this session.")
		await session.async_stop_coprocess()
	run_iterm(_run)


@coprocess.command('list')
def coprocess_list():
	"""List running coprocesses across all sessions."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		found = []
		for window in app.terminal_windows:
			for tab in window.tabs:
				for session in tab.sessions:
					cp = await session.async_get_coprocess()
					if cp:
						pid_str = str(cp.pid) if hasattr(cp, 'pid') else "unknown"
						cmd_str = str(cp.command) if hasattr(cp, 'command') else "unknown"
						found.append(f"{session.session_id} (PID {pid_str}): {cmd_str}")
		if not found:
			return "No running coprocesses"
		return "\n".join(found)
	result = run_iterm(_run)
	click.echo(result)


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
