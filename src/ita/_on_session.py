"""`ita on session-new` / `on session-end` — session lifecycle waits.

Split out of `_events.py` (#372). Both commands snapshot session
metadata before the relevant notification fires (names disappear when a
session ends; new-session payloads vary by iTerm2 version, hence
`_extract_uuid`).
"""
import asyncio
import json
import re
import click
import iterm2
from ._core import run_iterm, strip
from ._events import on, _debug_warn


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
