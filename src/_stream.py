# src/_stream.py
"""Streaming commands: watch."""
import asyncio
import json
import click
import iterm2
from _core import cli, run_iterm, resolve_session, strip, last_non_empty_index
from _output import _clean_lines, _is_prompt_line


def _ts() -> int:
	return int(asyncio.get_event_loop().time() * 1000)


async def _stream_session(session, json_stream: bool, prefix: str = '') -> None:
	"""Stream one session until prompt: diff-based, only new/added lines emitted."""
	contents = await session.async_get_screen_contents()
	initial = _clean_lines(contents)
	if json_stream:
		click.echo(json.dumps(
			{'session_id': session.session_id, 'lines': initial, 'timestamp_ms': _ts()},
			ensure_ascii=False,
		))
	else:
		for line in initial:
			click.echo(f"{prefix}{line}" if prefix else line)

	last_idx = last_non_empty_index(contents)
	if last_idx >= 0 and _is_prompt_line(strip(contents.line(last_idx).string)):
		return

	prev_snapshot: tuple[str, ...] = tuple(initial)
	async with session.get_screen_streamer() as streamer:
		while True:
			contents = await streamer.async_get()
			snapshot = tuple(_clean_lines(contents))
			if snapshot != prev_snapshot:
				prev_set = set(prev_snapshot)
				new_lines = [l for l in snapshot if l not in prev_set]
				if new_lines:
					if json_stream:
						click.echo(json.dumps(
							{'session_id': session.session_id, 'lines': new_lines, 'timestamp_ms': _ts()},
							ensure_ascii=False,
						))
					else:
						for line in new_lines:
							click.echo(f"{prefix}{line}" if prefix else line)
				prev_snapshot = snapshot
			last_idx = last_non_empty_index(contents)
			if last_idx < 0:
				continue
			if _is_prompt_line(strip(contents.line(last_idx).string)):
				break


@cli.command()
@click.option('-s', '--session', 'session_id', default=None)
@click.option('-t', '--timeout', default=None, type=int,
	help='Exit after N seconds (0 = run forever).')
@click.option('--all', 'watch_all', is_flag=True, help='Stream all sessions simultaneously.')
@click.option('--json-stream', is_flag=True, default=False,
	help='Emit one JSON object per frame: {session_id, lines[], timestamp_ms}.')
def watch(session_id, timeout, watch_all, json_stream):
	"""Stream screen updates until prompt. Only new/added lines emitted per frame.

	--all streams every session in parallel. --json-stream switches to
	machine-readable output. -t/--timeout caps the run time in seconds.
	"""
	async def _run_single(connection, sid):
		session = await resolve_session(connection, sid)
		await _stream_session(session, json_stream)

	async def _run_all(connection):
		app = await iterm2.async_get_app(connection)
		tasks = []
		for window in app.terminal_windows:
			for tab in window.tabs:
				for session in tab.sessions:
					prefix = f"[{session.session_id}] " if not json_stream else ''
					tasks.append(_stream_session(session, json_stream, prefix))
		await asyncio.gather(*tasks)

	async def _run(connection):
		if watch_all:
			await _run_all(connection)
		else:
			await _run_single(connection, session_id)

	if timeout is not None and timeout > 0:
		async def _run_with_timeout(connection):
			try:
				await asyncio.wait_for(_run(connection), timeout=timeout)
			except asyncio.TimeoutError:
				pass
		run_iterm(_run_with_timeout)
	else:
		run_iterm(_run)
