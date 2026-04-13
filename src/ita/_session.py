# src/_session.py
"""Session lifecycle commands: new, close, activate, name, restart, resize, clear, capture."""
from pathlib import Path
import shlex
import click
import iterm2
from ._core import (cli, run_iterm, resolve_session, strip, read_session_lines,
	check_protected, _all_sessions, parse_filter, match_filter,
	session_writelock, _SENTINEL_RE, _fresh_name, next_free_name, snapshot,
	capture_focus, restore_focus)
from ._envelope import ita_command, ItaError, json_dumps
from ._lock import resolve_force_flags


def _force_options(f):
	"""Decorator stacking --force-protected / --force-lock / --force (deprecated).
	See _send._force_options for shared semantics (#294)."""
	f = click.option('--force', is_flag=True, hidden=True,
		help='DEPRECATED: use --force-protected and/or --force-lock (#294).')(f)
	f = click.option('--force-lock', is_flag=True,
		help='Override write-lock guard; reclaim from another live ita process (#294).')(f)
	f = click.option('--force-protected', is_flag=True,
		help='Override protected-session guard (#294).')(f)
	return f

# `_fresh_name` lives in `_core.py` now (moved for #289 so resolve_session can
# reach it without a circular import). Re-exported here so any caller still
# doing `from ._session import _fresh_name` keeps working.
__all__ = ['_fresh_name']


async def _wait_name_visible(session, target: str, attempts: int = 5, delay: float = 0.1) -> None:
	"""After async_set_name, block briefly until the name propagates (#160)."""
	import asyncio
	for _ in range(attempts):
		if (await _fresh_name(session)) == target:
			return
		await asyncio.sleep(delay)


async def _session_records(connection):
	"""Snapshot (session, record-dict) pairs — uses fresh name reads so bulk
	filters don't miss names set by another ita process (#160)."""
	app = await iterm2.async_get_app(connection)
	records = []
	for window in app.terminal_windows:
		for tab in window.tabs:
			for session in tab.sessions:
				records.append((session, {
					'session_id': session.session_id,
					'session_name': await _fresh_name(session),
					'window_id': window.window_id,
					'tab_id': tab.tab_id,
				}))
	return records


_NEW_WAIT_DEFAULT = 'shell_alive,writable'


@cli.command()
@click.option('--window', 'new_window', is_flag=True, help='Create new window instead of tab')
@click.option('--profile', default=None, help='Profile name')
@click.option('--name', 'session_name', default=None, help='Name for the new session')
@click.option('--reuse', is_flag=True, help='If --name exists, return existing session instead of error')
@click.option('--replace', is_flag=True, help='If --name exists, close the existing session and create a fresh one')
@click.option('--cwd', default=None, help='Working directory for the new session')
@click.option('--run', 'run_cmd', default=None, help='Command to fire immediately after creation (non-blocking)')
@click.option('--json', 'as_json', is_flag=True, help='Return full session object as JSON')
@click.option('--wait', 'wait_reqs', default=_NEW_WAIT_DEFAULT, show_default=True,
	help='Comma-separated readiness flags to satisfy before returning (#250).')
@click.option('--no-wait', 'no_wait', is_flag=True, help='Return immediately without waiting for session readiness.')
@click.option('--background', is_flag=True,
	help='Create without shifting focus; restore previously-focused target after creation (#346).')
def new(new_window, profile, session_name, reuse, replace, cwd, run_cmd, as_json, wait_reqs, no_wait, background):
	"""Create new tab (or window). Returns name (stdout) and session ID.

	By default waits until the session is alive and writable before returning
	(--wait=shell_alive,writable). Pass --no-wait to skip the wait entirely,
	or --wait=<flags> to customise which readiness conditions must be met.
	Valid flags: shell_alive, prompt_visible, shell_integration_active,
	jobName_populated, writable."""
	if reuse and replace:
		raise click.ClickException("--reuse and --replace are mutually exclusive.")
	from ._readiness import _probe, _parse_require, _POLL_INTERVAL
	required_flags = set() if no_wait else _parse_require(wait_reqs)
	async def _run(connection):
		# Snapshot batches the per-session `_fresh_name` reads in parallel
		# (#300/#302) — replaces the old serial loop that paid one RPC per
		# session just to enumerate existing names.
		snap = await snapshot(connection)
		app = snap.app
		captured = await capture_focus(app) if background else None
		fresh_pairs = [(s, snap.fresh_names.get(s.session_id, '')) for s in snap.sessions]
		existing_names = snap.names()
		# If --name given, check uniqueness / reuse / replace
		if session_name:
			for s, n in fresh_pairs:
				if n == session_name:
					if reuse:
						tab = s.tab
						window = tab.window if tab else None
						return {
							'name': n,
							'session_id': s.session_id,
							'tab_id': tab.tab_id if tab else None,
							'window_id': window.window_id if window else None,
						}
					if replace:
						try:
							await s.async_close(force=True)
						except Exception:
							pass
						existing_names.discard(n)
						break
					# CONTRACT §2 "Mandatory naming on creation (#342)":
					# `--name` provided AND taken → bad-args with a message
					# naming the conflict; never silently auto-rename.
					raise ItaError("bad-args",
						f"name {session_name!r} already taken; "
						f"pass --replace, --reuse, or pick another name.")
		try:
			if new_window:
				window = await iterm2.Window.async_create(connection, profile=profile)
				session = window.current_tab.current_session
			else:
				# Prefer a tab in an existing window (#174). `current_terminal_window`
				# is None when iTerm2 has no focused window even if other windows
				# exist — fall back to any open terminal window before creating a
				# brand-new one, since windows are harder to reap than tabs.
				window = app.current_terminal_window
				if not window and app.terminal_windows:
					window = app.terminal_windows[0]
				if not window:
					window = await iterm2.Window.async_create(connection, profile=profile)
					session = window.current_tab.current_session
				else:
					tab = await window.async_create_tab(profile=profile)
					session = tab.current_session
		except iterm2.CreateTabException as e:
			# iTerm2 signals invalid profile via the CreateTabResponse status
			# name serialized as the exception message (#322). Check the
			# structured status name, not a substring of arbitrary output.
			if str(e) == 'INVALID_PROFILE_NAME':
				raise ItaError("bad-args", f"Profile not found: {profile!r}") from e
			raise ItaError("bad-args", f"Could not create tab: {e}") from e
		# Set session name
		name = session_name
		if not name:
			# CONTRACT §2 "Mandatory naming on creation (#342)": no
			# `--name` → auto-name with the lowest free counter. Shared
			# helper across object kinds (s/t/w/tmux).
			name = next_free_name('s', existing_names)
		await session.async_set_name(name)
		# Block briefly until the name is visible via the variable API so the
		# very next ita invocation sees it (#160).
		await _wait_name_visible(session, name)
		# --wait: poll readiness flags before returning (#250).
		if required_flags:
			import asyncio as _asyncio
			deadline = _asyncio.get_event_loop().time() + 5.0
			while True:
				flags = await _probe(session)
				if all(flags.get(f, False) for f in required_flags):
					break
				if _asyncio.get_event_loop().time() >= deadline:
					break
				await _asyncio.sleep(_POLL_INTERVAL)
		# --cwd: send `cd <dir>` as a shell command. Using async_send_text is
		# the simplest path that works with any profile; profile-level working
		# directory would require custom-profile mutation which is heavier.
		if cwd:
			await session.async_send_text(f"cd {shlex.quote(str(cwd))}\n")
		# --run: fire user command after optional cd. Non-blocking: we just
		# send text and return; the caller doesn't wait for completion.
		if run_cmd:
			tail = '' if run_cmd.endswith('\n') else '\n'
			await session.async_send_text(run_cmd + tail)
		tab = session.tab
		window = tab.window if tab else None
		if captured is not None:
			await restore_focus(app, captured)
		return {
			'name': name,
			'session_id': session.session_id,
			'tab_id': tab.tab_id if tab else None,
			'window_id': window.window_id if window else None,
		}

	info = run_iterm(_run)
	if as_json:
		click.echo(json_dumps(info))
	else:
		click.echo(f"{info['name']}\t{info['session_id']}")


def _reject_combo(session_id, where, all_flag):
	"""--session / --where / --all are mutually exclusive selectors."""
	picked = [n for n, v in
			  (('--session', session_id), ('--where', where), ('--all', all_flag)) if v]
	if len(picked) > 1:
		raise click.ClickException(
			f"{', '.join(picked)} are mutually exclusive — pick one selector.")
	if not picked:
		raise click.ClickException(
			"no session specified. Use -s NAME, --where KEY=VALUE, or --all.")


@cli.command()
@click.option('-s', '--session', 'session_id', default=None)
@click.option('--where', 'filter_expr', default=None,
			  help='Bulk selector: KEY=VALUE, KEY~=PREFIX, or KEY!=VALUE (#125).')
@click.option('--all', 'all_flag', is_flag=True, help='Bulk close every session (#125).')
@click.option('-q', '--quiet', is_flag=True, help='Suppress confirmation message')
@click.option('--dry-run', is_flag=True, help='Print what would be closed without doing it')
@click.option('--json', 'use_json', is_flag=True,
			  help='Emit CONTRACT §4 envelope on stdout (single-session path only).')
@click.option('--allow-window-close', is_flag=True,
			  help='Permit closes that would cascade-close a window (CONTRACT §10, #340).')
@_force_options
@ita_command(op='close')
def close(session_id, filter_expr, all_flag, quiet, dry_run, use_json,
		  allow_window_close,
		  force_protected, force_lock, force):
	"""Close a session (or many via --where / --all).

	--json emits a CONTRACT §4 envelope on the single-session path. Bulk
	paths (--where / --all) still produce plain per-member lines for now;
	a future PR will give them stream-envelope semantics (§11)."""
	from ._envelope import ItaError
	fp, fl = resolve_force_flags(force, force_protected, force_lock)
	if session_id is not None and not session_id.strip():
		raise ItaError("bad-args", "--session cannot be empty")
	bulk = bool(filter_expr or all_flag)
	if not bulk:
		closed_id = None
		async def _run(connection):
			nonlocal closed_id
			session = await resolve_session(connection, session_id)
			check_protected(session.session_id, force_protected=fp)
			# CONTRACT §10 "Destructive blast radius — tab-by-tab default
			# (#340)": refuse a close that would cascade-close the window
			# unless --allow-window-close was passed.
			from ._cascade import session_close_would_cascade_window
			if not allow_window_close and session_close_would_cascade_window(session):
				raise ItaError("bad-args",
					f"Closing session {session.session_id[:8]}… would also close its "
					f"tab and window (last session in last tab). Pass "
					f"--allow-window-close to proceed (CONTRACT §10, #340).")
			closed_id = session.session_id
			if not dry_run:
				with session_writelock(session.session_id, force_lock=fl):
					await session.async_close(force=True)
		run_iterm(_run)
		if closed_id and not use_json:
			if dry_run:
				click.echo(f"Would close: {closed_id}")
			elif not quiet:
				click.echo(f"Closed: {closed_id}", err=True)
			else:
				click.echo(closed_id)
		return {
			"target": {"session": closed_id},
			"state_before": "ready",
			"state_after": "dead" if not dry_run else "ready",
			"data": {"session_id": closed_id, "dry_run": dry_run},
		}

	_reject_combo(session_id, filter_expr, all_flag)
	if filter_expr:
		key, op, value = parse_filter(filter_expr)

	from ._core import get_protected
	from ._cascade import session_close_would_cascade_window
	results = {'closed': [], 'skipped': []}
	warnings: list[dict] = []
	async def _run_bulk(connection):
		pairs = await _session_records(connection)
		if filter_expr:
			pairs = [(s, r) for s, r in pairs if match_filter(r, key, op, value)]
		# #13 set-merge: dedupe by session_id so a session appearing twice
		# (e.g. via overlapping domain iteration upstream) is closed once.
		seen: set[str] = set()
		deduped: list = []
		for s, r in pairs:
			if r['session_id'] in seen:
				continue
			seen.add(r['session_id'])
			deduped.append((s, r))
		protected = get_protected()
		for s, r in deduped:
			# #283: per-target protect check. Honored even in bulk paths.
			if r['session_id'] in protected and not fp:
				results['skipped'].append(('protected', r))
				continue
			# CONTRACT §10 "Bulk close protects against cascade (#340)":
			# per-member check — any close that would cascade-close a
			# window is refused and surfaced in warnings[], never silently
			# taken down. --allow-window-close opts in.
			if not allow_window_close and session_close_would_cascade_window(s):
				results['skipped'].append(('window-cascade', r))
				warnings.append({
					"code": "window-cascade-skipped",
					"reason": (
						f"session {r['session_id'][:8]}… skipped: closing it "
						f"would cascade-close window {r.get('window_id', '?')} "
						f"(last session in last tab). Pass --allow-window-close "
						f"to include cascading members (CONTRACT §10, #340)."
					),
					"session_id": r['session_id'],
				})
				continue
			results['closed'].append(r)
			if not dry_run:
				try:
					# #258: per-target writelock. A single bulk invocation
					# still serializes against sibling ita processes on each
					# member; concurrent members within THIS invocation run
					# sequentially (fcntl.flock is synchronous).
					with session_writelock(r['session_id'], force_lock=fl):
						await s.async_close(force=True)
				except ItaError:
					# lock conflict → surface as a skip, not an abort.
					results['skipped'].append(('locked', r))
				except Exception:
					# Best-effort bulk close — don't abort the whole batch on
					# a transient per-session failure.
					pass

	run_iterm(_run_bulk)
	verb = 'Would close' if dry_run else 'Closed'
	for r in results['closed']:
		label = f"{r['session_id']} ({r['session_name']})" if r['session_name'] else r['session_id']
		if quiet and not dry_run:
			click.echo(r['session_id'])
		else:
			click.echo(f"{verb}: {label}", err=not quiet and not dry_run)
	for reason, r in results['skipped']:
		label_reason = {
			'protected': 'protected',
			'window-cascade': 'would cascade-close window',
			'locked': 'locked',
		}.get(reason, reason)
		click.echo(f"Skipped ({label_reason}): {r['session_id']} ({r['session_name']})", err=True)
	# Surface window-cascade skips in the envelope's warnings[] per §10.
	return {"warnings": warnings, "data": {"closed": len(results['closed']),
		"skipped": len(results['skipped'])}}


@cli.command()
@click.argument('session_id_pos', metavar='SESSION_ID', required=False, default=None)
@click.option('-s', '--session', 'session_id_opt', default=None, help='Session to activate')
def activate(session_id_pos, session_id_opt):
	"""Focus/bring a session to front."""
	# Flag takes precedence; positional kept for backwards compat
	session_id = session_id_opt or session_id_pos
	async def _run(connection):
		session = await resolve_session(connection, session_id)
		await session.async_activate(select_tab=True, order_window_front=True)
	run_iterm(_run)


@cli.command()
@click.argument('title')
@click.option('-s', '--session', 'session_id', default=None)
@click.option('--where', 'filter_expr', default=None,
			  help='Bulk selector: KEY=VALUE, KEY~=PREFIX, or KEY!=VALUE (#125).')
@click.option('--all', 'all_flag', is_flag=True, help='Apply to every session (#125).')
@click.option('-y', '--yes', 'force', is_flag=True, help='Skip confirmation prompt.')
@click.option('--dry-run', is_flag=True, help='Print what would be renamed without doing it.')
@click.option('-q', '--quiet', is_flag=True, help='Suppress confirmation message')
def name(title, session_id, filter_expr, all_flag, force, dry_run, quiet):
	"""Rename session (or many via --where / --all)."""
	if not title.strip():
		raise click.ClickException("Name cannot be empty")
	bulk = bool(filter_expr or all_flag)
	if not bulk:
		renamed_id = None
		async def _run(connection):
			nonlocal renamed_id
			session = await resolve_session(connection, session_id)
			renamed_id = session.session_id
			if not dry_run:
				await session.async_set_name(title)
				await _wait_name_visible(session, title)
		run_iterm(_run)
		if dry_run:
			click.echo(f"Would rename: {renamed_id} -> {title}")
		elif not quiet:
			click.echo(f"Named: {renamed_id}")
		else:
			click.echo(renamed_id)
		return

	_reject_combo(session_id, filter_expr, all_flag)
	if filter_expr:
		key, op, value = parse_filter(filter_expr)
	renamed = []
	async def _run_bulk(connection):
		pairs = await _session_records(connection)
		if filter_expr:
			pairs = [(s, r) for s, r in pairs if match_filter(r, key, op, value)]
		for s, r in pairs:
			renamed.append(r)
			if not dry_run:
				await s.async_set_name(title)
				await _wait_name_visible(s, title)
	run_iterm(_run_bulk)
	verb = 'Would rename' if dry_run else 'Named'
	for r in renamed:
		if quiet and not dry_run:
			click.echo(r['session_id'])
		else:
			click.echo(f"{verb}: {r['session_id']} -> {title}")


@cli.command()
@click.option('-s', '--session', 'session_id', default=None)
@click.option('-q', '--quiet', is_flag=True, help='Suppress confirmation message')
@_force_options
def restart(session_id, quiet, force_protected, force_lock, force):
	"""Restart session. Prints new session ID (may differ after restart)."""
	fp, fl = resolve_force_flags(force, force_protected, force_lock)
	old_id = None
	async def _run(connection):
		nonlocal old_id
		import asyncio
		session = await resolve_session(connection, session_id)
		check_protected(session.session_id, force_protected=fp)
		old_id = session.session_id
		tab_id = session.tab.tab_id if session.tab else None
		with session_writelock(session.session_id, force_lock=fl):
			await session.async_restart(only_if_exited=False)
		# Wait briefly for iTerm2 to register the new session object
		await asyncio.sleep(0.5)
		# Re-fetch app state and find the replacement session in the same tab.
		# Use `terminal_windows` for parity with the rest of the codebase
		# (#297). If we cannot find a replacement we MUST NOT hand back the
		# old session id — that's the #319 staleness bug: the caller would
		# act on a dead session. Raise not-found instead.
		app2 = await iterm2.async_get_app(connection)
		if tab_id:
			for w in app2.terminal_windows:
				for t in w.tabs:
					if t.tab_id == tab_id and t.current_session:
						return t.current_session.session_id
		raise ItaError("not-found",
			f"session {old_id} restarted, but no replacement session was "
			f"found in tab {tab_id}. The session may have been closed; "
			f"run 'ita status' to inspect.")

	new_sid = run_iterm(_run)
	if new_sid:
		if not quiet:
			click.echo(f"Restarted: {new_sid}")
		else:
			click.echo(new_sid)


@cli.command()
@click.option('--cols', type=click.IntRange(min=1), required=True)
@click.option('--rows', type=click.IntRange(min=1), required=True)
@click.option('-s', '--session', 'session_id', default=None)
@click.option('-y', '--yes', 'force', is_flag=True, help='Skip confirmation prompt.')
@click.option('--dry-run', is_flag=True, help='Print what would be resized without doing it.')
@click.option('-q', '--quiet', is_flag=True, help='Suppress confirmation message')
def resize(cols, rows, session_id, force, dry_run, quiet):
	"""Resize session pane."""
	if dry_run:
		click.echo(f"Would: resize session to {cols}x{rows}")
		return
	async def _run(connection):
		session = await resolve_session(connection, session_id)
		size = iterm2.util.Size(cols, rows)
		# async_set_grid_size works for single-pane tabs but returns IMPOSSIBLE
		# when split panes are present. Fall back to the tab-layout path, which
		# honours each session's preferred_size and recalculates the whole tab.
		try:
			await session.async_set_grid_size(size)
		except Exception as e:
			if 'IMPOSSIBLE' not in str(e):
				raise
			try:
				session.preferred_size = size
				tab = session.tab
				if tab is None:
					raise click.ClickException(
						"Cannot resize: session has no containing tab (buried?).")
				await tab.async_update_layout()
			except click.ClickException:
				raise
			except Exception as e:
				raise click.ClickException(
					f"Cannot resize: {e} (fullscreen or tmux-CC windows cannot be resized via API)"
				) from e
		import asyncio
		await asyncio.sleep(0.1)
		actual_cols = session.grid_size.width
		actual_rows = session.grid_size.height
		if actual_cols != cols or actual_rows != rows:
			if not quiet:
				click.echo(
					f"warning: requested {cols}x{rows} but got {actual_cols}x{actual_rows}",
					err=True)
		elif not quiet:
			click.echo(f"Resized: {cols}x{rows}")
		return session.session_id
	resized_id = run_iterm(_run)
	if resized_id and quiet:
		click.echo(resized_id)


@cli.command('clear')
@click.option('-s', '--session', 'session_id', default=None)
@click.option('--where', 'filter_expr', default=None,
			  help='Bulk selector: KEY=VALUE, KEY~=PREFIX, or KEY!=VALUE (#125).')
@click.option('--all', 'all_flag', is_flag=True, help='Apply to every session (#125).')
@click.option('--dry-run', is_flag=True, help='Print what would be cleared without doing it.')
@click.option('-q', '--quiet', is_flag=True, help='Suppress confirmation message')
@_force_options
def clear_screen(session_id, filter_expr, all_flag, dry_run, quiet,
				 force_protected, force_lock, force):
	"""Clear session screen (Ctrl+L). Supports --where / --all for bulk."""
	fp, fl = resolve_force_flags(force, force_protected, force_lock)
	bulk = bool(filter_expr or all_flag)
	if not bulk:
		cleared_id = None
		async def _run(connection):
			nonlocal cleared_id
			session = await resolve_session(connection, session_id)
			cleared_id = session.session_id
			check_protected(session.session_id, force_protected=fp)
			if not dry_run:
				with session_writelock(session.session_id, force_lock=fl):
					await session.async_send_text('\x0c')
		run_iterm(_run)
		if dry_run:
			click.echo(f"Would clear: {cleared_id}")
		elif not quiet:
			click.echo(cleared_id)
		return

	_reject_combo(session_id, filter_expr, all_flag)
	if filter_expr:
		key, op, value = parse_filter(filter_expr)
	cleared = []
	async def _run_bulk(connection):
		pairs = await _session_records(connection)
		if filter_expr:
			pairs = [(s, r) for s, r in pairs if match_filter(r, key, op, value)]
		# §13 set-merge dedup.
		seen: set[str] = set()
		deduped = []
		for s, r in pairs:
			if r['session_id'] in seen:
				continue
			seen.add(r['session_id'])
			deduped.append((s, r))
		for s, r in deduped:
			# #283: per-target protect check for bulk ops.
			try:
				check_protected(r['session_id'], force_protected=fp)
			except Exception as exc:
				click.echo(f"Skipped {r['session_id'][:8]}…: {exc}", err=True)
				continue
			cleared.append(r)
			if not dry_run:
				# #258: per-target writelock inside the bulk loop. fcntl
				# serializes across processes; within this invocation
				# members are cleared sequentially.
				try:
					with session_writelock(r['session_id'], force_lock=fl):
						await s.async_send_text('\x0c')
				except ItaError as exc:
					click.echo(f"Skipped {r['session_id'][:8]}…: {exc.reason}", err=True)
					cleared.pop()
	run_iterm(_run_bulk)
	verb = 'Would clear' if dry_run else 'Cleared'
	for r in cleared:
		click.echo(f"{verb}: {r['session_id']}")


@cli.command()
@click.argument('file', required=False)
@click.option('-n', '--lines', 'lines', default=None, type=click.IntRange(min=1),
			  help='Limit output to last N lines (after filtering).')
@click.option('--scrollback', 'scrollback', is_flag=True, default=False,
			  help='Include scrollback history (full session output), not just the visible grid.')
@click.option('-s', '--session', 'session_id', default=None)
def capture(file, lines, scrollback, session_id):
	"""Save screen contents to file (or stdout if no file given).

	By default only the currently visible grid is captured. Pass --scrollback
	to include the full scrollback buffer — required when a command produced
	more output than fits on screen."""
	async def _run(connection):
		session = await resolve_session(connection, session_id)
		result = await read_session_lines(session, include_scrollback=scrollback)
		result = [ln for ln in result if not _SENTINEL_RE.match(ln)]
		return result

	result = run_iterm(_run)
	if lines is not None:
		result = result[-lines:]
	output = '\n'.join(result)
	if not output:
		output = '\n'
	if file:
		try:
			Path(file).expanduser().write_text(output)
		except (FileNotFoundError, PermissionError, IsADirectoryError) as e:
			raise click.ClickException(f"Cannot write {file}: {e}") from e
		click.echo(f"Saved to {file}")
	else:
		click.echo(output)
