# src/_overview.py
"""Situational awareness: `ita overview` — tree + content preview in one call.

Replaces the 2–3 call pattern (`status` + `read --all` [+ `tmux connections`])
with a single IPC round that yields window/tab/session hierarchy, per-session
metadata, and optional trailing output lines. Token-compact by default."""
import json
import click
import iterm2
from ._core import cli, run_iterm, strip, parse_filter, match_filter
from ._output import _clean_lines


async def _tail_lines(session, n: int) -> list[str]:
	"""Return up to n cleaned trailing lines from session screen."""
	if n <= 0:
		return []
	contents = await session.async_get_screen_contents()
	cleaned = _clean_lines(contents)
	return cleaned[-n:] if cleaned else []


async def _gather(connection, lines: int, include_preview: bool,
		filter_kov: tuple | None) -> dict:
	app = await iterm2.async_get_app(connection)
	# tmux connection summary — cheap, one call
	tmux_state = []
	try:
		conns = await iterm2.tmux.async_get_tmux_connections(connection)
		for c in conns or []:
			tmux_state.append({
				'connection_id': getattr(c, 'connection_id', None),
				'owning_session_id': getattr(
					getattr(c, 'owning_session', None), 'session_id', None),
			})
	except Exception:
		pass

	current_sid = None
	cw = app.current_terminal_window
	if cw and cw.current_tab and cw.current_tab.current_session:
		current_sid = cw.current_tab.current_session.session_id

	windows = []
	for window in app.windows:
		w_entry = {
			'window_id': window.window_id,
			'tabs': [],
		}
		for tab in window.tabs:
			t_entry = {
				'tab_id': tab.tab_id,
				'tmux_window_id': tab.tmux_window_id,
				'sessions': [],
			}
			for session in tab.sessions:
				proc = strip(await session.async_get_variable('jobName') or '')
				path = strip(await session.async_get_variable('path') or '')
				s_entry = {
					'session_id': session.session_id,
					'session_name': strip(session.name or ''),
					'process': proc,
					'path': path,
					'window_id': window.window_id,
					'tab_id': tab.tab_id,
					'is_current': session.session_id == current_sid,
				}
				# Filter — evaluated against the per-session record
				if filter_kov is not None:
					k, op, v = filter_kov
					if not match_filter(s_entry, k, op, v):
						continue
				if include_preview and lines > 0:
					try:
						s_entry['lines'] = await _tail_lines(session, lines)
					except Exception:
						s_entry['lines'] = []
				else:
					s_entry['lines'] = []
				t_entry['sessions'].append(s_entry)
			# Drop tabs emptied by the filter
			if t_entry['sessions'] or filter_kov is None:
				w_entry['tabs'].append(t_entry)
		if w_entry['tabs'] or filter_kov is None:
			windows.append(w_entry)

	return {'windows': windows, 'tmux': tmux_state}


def _short(sid: str) -> str:
	return (sid or '')[:8]


def _render_text(data: dict, show_preview: bool) -> list[str]:
	out = []
	tmux_by_win = {}  # window_id -> list of tmux_window_ids on its tabs
	for w in data['windows']:
		tmux_ids = [t['tmux_window_id'] for t in w['tabs'] if t.get('tmux_window_id')]
		if tmux_ids:
			tmux_by_win[w['window_id']] = tmux_ids

	for w in data['windows']:
		suffix = ''
		if w['window_id'] in tmux_by_win:
			suffix = f" [tmux {', '.join(tmux_by_win[w['window_id']])}]"
		out.append(f"Window {w['window_id']}{suffix}")
		for t in w['tabs']:
			tmux_tag = f" (tmux {t['tmux_window_id']})" if t.get('tmux_window_id') else ''
			out.append(f"  Tab {t['tab_id']}{tmux_tag}")
			for s in t['sessions']:
				marker = '*' if s.get('is_current') else ' '
				name = (s['session_name'] or '')[:18]
				proc = (s['process'] or '')[:10]
				path = s['path'] or ''
				out.append(
					f"    {marker} {_short(s['session_id']):<8}  "
					f"{name:<18}  {proc:<10}  {path}"
				)
				if show_preview:
					for line in s.get('lines', []):
						# strip blanks already handled in _clean_lines
						out.append(f"      > {line}")
	if data.get('tmux'):
		out.append('')
		out.append('tmux connections:')
		for c in data['tmux']:
			out.append(f"  conn={c.get('connection_id')}  owner={c.get('owning_session_id')}")
	return out


@cli.command()
@click.option('--lines', 'lines_n', default=1, type=click.IntRange(min=0),
	help='Trailing lines per session (default 1). 0 = structure only.')
@click.option('--no-preview', is_flag=True,
	help='Skip content preview entirely (faster). Equivalent to --lines 0.')
@click.option('--json', 'use_json', is_flag=True,
	help='Structured output: windows/tabs/sessions hierarchy + tmux state.')
@click.option('--where', 'filter_expr', default=None,
	help='Filter sessions by property (same syntax as `status --where`).')
def overview(lines_n, no_preview, use_json, filter_expr):
	"""One-shot situational awareness: window/tab/session tree + recent output.

	Replaces `ita status` + `ita read --all` in a single call.  Use `--lines 0`
	or `--no-preview` for pure structure; `--lines 5` for richer context."""
	include_preview = not no_preview
	effective_lines = 0 if no_preview else lines_n
	kov = None
	if filter_expr:
		kov = parse_filter(filter_expr)

	async def _run(connection):
		return await _gather(connection, effective_lines, include_preview, kov)

	data = run_iterm(_run) or {'windows': [], 'tmux': []}

	if use_json:
		click.echo(json.dumps(data, indent=2, ensure_ascii=False))
		return
	for line in _render_text(data, include_preview and effective_lines > 0):
		click.echo(line)
