# src/_stream.py
"""Streaming commands: watch."""
import asyncio
import click
import iterm2
from ._core import cli, run_iterm, resolve_session, strip, last_non_empty_index, _is_prompt_line
from ._envelope import json_dumps
from ._output import _clean_lines


def _ts() -> int:
	return int(asyncio.get_running_loop().time() * 1000)


async def _stream_session(session, json_stream: bool, prefix: str = '', name: str = '') -> None:
	"""Stream one session until prompt: diff-based, only new/added lines emitted.

	`prefix` is prepended to text-mode output (e.g. "[build] ").
	`name` is included in json-mode payloads as the `session` field.
	The `async with session.get_screen_streamer()` context manager guarantees
	the underlying subscription is torn down on every exit path (#176)."""
	contents = await session.async_get_screen_contents()
	initial = _clean_lines(contents)
	if json_stream:
		payload = {'session_id': session.session_id, 'lines': initial, 'timestamp_ms': _ts()}
		if name:
			payload['session'] = name
		click.echo(json_dumps(payload))
	else:
		for line in initial:
			click.echo(f"{prefix}{line}" if prefix else line)

	last_idx = last_non_empty_index(contents)
	if last_idx >= 0 and _is_prompt_line(strip(contents.line(last_idx).string)):
		return

	prev_snapshot: tuple[str, ...] = tuple(initial)
	prev_set: frozenset[str] = frozenset(prev_snapshot)
	async with session.get_screen_streamer() as streamer:
		while True:
			contents = await streamer.async_get()
			snapshot = tuple(_clean_lines(contents))
			if snapshot != prev_snapshot:
				if len(snapshot) < len(prev_snapshot):
					# Screen was cleared/reset: emit a reset marker then the full
					# new snapshot so consumers can detect the discontinuity (#230).
					new_lines = ['<<screen reset>>'] + list(snapshot)
				else:
					# Emit lines that appear in the new snapshot but weren't in prev.
					# Using set difference handles clears/rewrites/scrolls correctly;
					# slice-based growth assumption broke when content was overwritten.
					new_lines = [ln for ln in snapshot if ln not in prev_set]
				if new_lines:
					if json_stream:
						payload = {'session_id': session.session_id, 'lines': new_lines, 'timestamp_ms': _ts()}
						if name:
							payload['session'] = name
						click.echo(json_dumps(payload))
					else:
						for line in new_lines:
							click.echo(f"{prefix}{line}" if prefix else line)
				prev_snapshot = snapshot
				prev_set = frozenset(snapshot)
			last_idx = last_non_empty_index(contents)
			if last_idx < 0:
				continue
			if _is_prompt_line(strip(contents.line(last_idx).string)):
				break


@cli.command()
@click.option('-s', '--session', 'session_ids', default=None, multiple=True,
	help='Session to watch. Pass multiple times to watch several sessions.')
@click.option('-t', '--timeout', default=None, type=int,
	help='Exit after N seconds (0 = run forever).')
@click.option('--all', 'watch_all', is_flag=True, help='Stream all sessions simultaneously.')
@click.option('--json-stream', is_flag=True, default=False,
	help='Emit one JSON object per frame: {session, session_id, lines[], timestamp_ms}.')
@click.option('--json', 'use_json', is_flag=True, default=False,
	help='Alias for --json-stream.')
def watch(session_ids, timeout, watch_all, json_stream, use_json):
	"""Stream screen updates until prompt. Only new/added lines emitted per frame.

	--all streams every session in parallel. Pass -s/--session multiple times
	to stream a subset. --json-stream switches to machine-readable output.
	-t/--timeout caps the run time in seconds.
	"""
	json_stream = json_stream or use_json
	def _label(session) -> str:
		"""Short display label: session name if available, else short id."""
		nm = strip(getattr(session, 'name', '') or '').strip()
		if nm:
			return nm
		sid = session.session_id
		return sid[:8] if len(sid) > 8 else sid

	async def _collect_sessions(connection):
		app = await iterm2.async_get_app(connection)
		out = []
		for window in app.terminal_windows:
			for tab in window.tabs:
				for session in tab.sessions:
					out.append(session)
		return out

	async def _run_multi(connection, sessions):
		# Align prefixes for readability: [name   ] ...
		width = max((len(_label(s)) for s in sessions), default=0)
		tasks = []
		for session in sessions:
			name = _label(session)
			prefix = '' if json_stream else f"[{name.ljust(width)}] "
			# Each _stream_session manages its own streamer via `async with`,
			# so cancellation of gather cleans every subscription up (#176).
			tasks.append(_stream_session(session, json_stream, prefix, name))
		await asyncio.gather(*tasks)

	async def _run_single(connection, sid):
		session = await resolve_session(connection, sid)
		await _stream_session(session, json_stream, name=_label(session))

	async def _run(connection):
		if watch_all:
			sessions = await _collect_sessions(connection)
			if not sessions:
				raise click.ClickException("No sessions available to watch.")
			await _run_multi(connection, sessions)
		elif session_ids and len(session_ids) > 1:
			sessions = []
			for sid in session_ids:
				sessions.append(await resolve_session(connection, sid))
			await _run_multi(connection, sessions)
		else:
			sid = session_ids[0] if session_ids else None
			await _run_single(connection, sid)

	if timeout is not None and timeout > 0:
		async def _run_with_timeout(connection):
			try:
				await asyncio.wait_for(_run(connection), timeout=timeout)
			except asyncio.TimeoutError:
				pass
		run_iterm(_run_with_timeout)
	else:
		run_iterm(_run)
