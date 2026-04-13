# src/_output.py
"""Output reading commands: read. Shared helpers exported for _stream, _query."""
import json
import re
import click
import iterm2
from ._core import (cli, run_iterm, resolve_session, strip, last_non_empty_index, read_session_lines, _is_prompt_line, _SENTINEL_RE)


def _clean_lines(contents) -> list[str]:
	result = [strip(contents.line(i).string) for i in range(contents.number_of_lines)]
	result = [ln for ln in result if not _SENTINEL_RE.match(ln)]
	while result and not result[-1].strip():
		result.pop()
	return result


async def _session_meta(session) -> dict:
	return {
		'session_id': session.session_id,
		'session_name': strip(session.name or ''),
		'process': strip(await session.async_get_variable('jobName') or ''),
		'path': strip(await session.async_get_variable('path') or ''),
	}


async def _read_session(session, lines: int, scrollback: bool = False) -> dict:
	if scrollback:
		all_lines = await read_session_lines(session, include_scrollback=True)
		result = [ln for ln in all_lines if not _SENTINEL_RE.match(ln)]
		result = result[-lines:]
	else:
		contents = await session.async_get_screen_contents()
		last_idx = last_non_empty_index(contents)
		if last_idx < 0:
			result = []
		else:
			start = max(0, last_idx + 1 - lines)
			result = [strip(contents.line(i).string) for i in range(start, last_idx + 1)]
			result = [ln for ln in result if not _SENTINEL_RE.match(ln)]
			while result and not result[-1].strip():
				result.pop()
	meta = await _session_meta(session)
	return {**meta, 'lines': result, 'count': len(result)}


@cli.command()
@click.argument('lines_arg', default=None, type=click.IntRange(min=1), required=False, metavar='LINES')
@click.option('-n', '--lines', 'lines_opt', default=None, type=click.IntRange(min=1),
	help='Read last N lines (alternative to positional).')
@click.option('--json', 'use_json', is_flag=True)
@click.option('--all', 'read_all', is_flag=True, help='Read from all sessions.')
@click.option('--ids-only', is_flag=True, default=False, help='With --all, print only session IDs.')
@click.option('--scrollback', is_flag=True, default=False, help='Include scrollback history.')
@click.option('--grep', 'grep_pattern', default=None, help='Filter lines matching regex.')
@click.option('--after-row', 'after_row', default=None, type=int, help='Skip first N rows.')
@click.option('--since-prompt', is_flag=True, default=False, help='Lines since last prompt marker.')
@click.option('--tail', 'tail_n', default=None, type=click.IntRange(min=1),
	help='Truncate the filtered result to the last N lines. Prepends '
		 '[truncated: X lines] when output was cut. (#126)')
@click.option('-s', '--session', 'session_id', default=None)
def read(lines_arg, lines_opt, use_json, read_all, ids_only, scrollback,
		 grep_pattern, after_row, since_prompt, tail_n, session_id):
	"""Read last N lines from session. Always clean."""
	n = lines_opt or lines_arg or 20
	grep_rx = None
	if grep_pattern:
		try:
			grep_rx = re.compile(grep_pattern)
		except re.error as e:
			raise click.ClickException(f"Invalid regex {grep_pattern!r}: {e}") from e

	def _filter(raw):
		result = raw
		if after_row is not None:
			result = result[after_row:]
		if grep_rx:
			result = [ln for ln in result if grep_rx.search(ln)]
		if since_prompt:
			# Scan backward to find the LAST prompt line; return everything after it.
			for i in range(len(result) - 1, -1, -1):
				if _is_prompt_line(result[i]):
					result = result[i + 1:]
					break
		# #126: --tail truncates AFTER other filters so the notice reflects
		# what the caller would otherwise have seen, and prepends a notice
		# so agents know context was cut.
		if tail_n is not None and len(result) > tail_n:
			result = [f"[truncated: {len(result)} lines]"] + result[-tail_n:]
		return result

	if read_all:
		async def _run_all(connection):
			app = await iterm2.async_get_app(connection)
			out = {}
			for window in app.terminal_windows:
				for tab in window.tabs:
					for s in tab.sessions:
						out[s.session_id] = await _read_session(s, n, scrollback)
			return out

		data = run_iterm(_run_all) or {}
		if ids_only:
			for sid in data:
				click.echo(sid)
		elif use_json:
			click.echo(json.dumps(data, ensure_ascii=False))
		else:
			for sid, sd in data.items():
				click.echo(f"--- {sid} ---")
				click.echo('\n'.join(_filter(sd['lines'])))
		return

	async def _run(connection):
		session = await resolve_session(connection, session_id)
		return await _read_session(session, n, scrollback)

	data = run_iterm(_run)
	filtered = _filter(data['lines'])
	if use_json:
		click.echo(json.dumps({**data, 'lines': filtered}, ensure_ascii=False))
	else:
		click.echo('\n'.join(filtered))
