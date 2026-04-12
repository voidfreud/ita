# src/_session.py
"""Session lifecycle commands: new, close, activate, name, restart, resize, clear, capture."""
from pathlib import Path
import re
import click
import iterm2
from _core import cli, run_iterm, resolve_session, strip, read_session_lines, check_protected, _all_sessions, parse_filter, match_filter


async def _fresh_name(session) -> str:
	"""Read the live session name via a fresh RPC, falling back to the cached
	snapshot. The app-snapshot `session.name` is populated asynchronously by
	iTerm2 and can lag behind a prior `async_set_name` call from another
	process (see #160), so for uniqueness / reuse checks we query the variable
	directly."""
	try:
		fresh = await session.async_get_variable('session.name')
	except Exception:
		fresh = None
	if not fresh:
		try:
			fresh = await session.async_get_variable('name')
		except Exception:
			fresh = None
	if not fresh:
		fresh = session.name
	return strip(fresh or '')


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

_SENTINEL_RE = re.compile(r'^: ita-[0-9a-f]+;')


@cli.command()
@click.option('--window', 'new_window', is_flag=True, help='Create new window instead of tab')
@click.option('--profile', default=None, help='Profile name')
@click.option('--name', 'session_name', default=None, help='Name for the new session')
@click.option('--reuse', is_flag=True, help='If --name exists, return existing session instead of error')
def new(new_window, profile, session_name, reuse):
	"""Create new tab (or window). Returns name and session ID."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		all_sess = _all_sessions(app)
		# Build existing-names set from *fresh* variable reads so names set by
		# a prior ita process that haven't yet propagated to the app snapshot
		# still participate in uniqueness / auto-naming checks (#160).
		fresh_pairs = [(s, await _fresh_name(s)) for s in all_sess]
		existing_names = {n for _, n in fresh_pairs if n}
		# If --name given, check uniqueness / reuse
		if session_name:
			for s, n in fresh_pairs:
				if n == session_name:
					if reuse:
						return n, s.session_id
					raise click.ClickException(
						f"session name {session_name!r} already exists. "
						f"Use --reuse to return the existing session.")
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
		except Exception as e:
			if 'INVALID_PROFILE_NAME' in str(e):
				raise click.ClickException(f"Profile not found: {profile!r}") from e
			raise
		# Set session name
		name = session_name
		if not name:
			# Auto-name: s1, s2, s3, ...
			i = 1
			while f's{i}' in existing_names:
				i += 1
			name = f's{i}'
		await session.async_set_name(name)
		# Block briefly until the name is visible via the variable API so the
		# very next ita invocation sees it (#160).
		await _wait_name_visible(session, name)
		return name, session.session_id

	name, sid = run_iterm(_run)
	click.echo(f"{name}\t{sid}")


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
@click.option('--force', is_flag=True,
              help='Override protected-session guard (also required with --all to close protected).')
def close(session_id, filter_expr, all_flag, quiet, dry_run, force):
    """Close a session (or many via --where / --all)."""
    if session_id is not None and not session_id.strip():
        raise click.ClickException("--session cannot be empty")
    bulk = bool(filter_expr or all_flag)
    if not bulk:
        closed_id = None
        async def _run(connection):
            nonlocal closed_id
            session = await resolve_session(connection, session_id)
            check_protected(session.session_id, force=force)
            closed_id = session.session_id
            if not dry_run:
                await session.async_close(force=True)
        run_iterm(_run)
        if closed_id:
            if dry_run:
                click.echo(f"Would close: {closed_id}")
            elif not quiet:
                click.echo(f"Closed: {closed_id}", err=True)
            else:
                click.echo(closed_id)
        return

    _reject_combo(session_id, filter_expr, all_flag)
    if filter_expr:
        key, op, value = parse_filter(filter_expr)

    from _core import get_protected
    results = {'closed': [], 'skipped': []}
    async def _run_bulk(connection):
        pairs = await _session_records(connection)
        if filter_expr:
            pairs = [(s, r) for s, r in pairs if match_filter(r, key, op, value)]
        protected = get_protected()
        for s, r in pairs:
            if r['session_id'] in protected and not force:
                results['skipped'].append(r)
                continue
            results['closed'].append(r)
            if not dry_run:
                try:
                    await s.async_close(force=True)
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
    for r in results['skipped']:
        click.echo(f"Skipped (protected): {r['session_id']} ({r['session_name']})", err=True)


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
@click.option('--dry-run', is_flag=True, help='Print what would be renamed without doing it.')
@click.option('-q', '--quiet', is_flag=True, help='Suppress confirmation message')
def name(title, session_id, filter_expr, all_flag, dry_run, quiet):
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
def restart(session_id, quiet):
    """Restart session. Prints new session ID (may differ after restart)."""
    old_id = None
    async def _run(connection):
        nonlocal old_id
        import asyncio
        app = await iterm2.async_get_app(connection)
        session = await resolve_session(connection, session_id)
        old_id = session.session_id
        tab_id = session.tab.tab_id if session.tab else None
        await session.async_restart(only_if_exited=False)
        # Wait briefly for iTerm2 to register the new session object
        await asyncio.sleep(0.5)
        # Re-fetch app state and find the replacement session in the same tab
        app2 = await iterm2.async_get_app(connection)
        if tab_id:
            for w in app2.windows:
                for t in w.tabs:
                    if t.tab_id == tab_id and t.current_session:
                        return t.current_session.session_id
        return old_id

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
@click.option('-q', '--quiet', is_flag=True, help='Suppress confirmation message')
def resize(cols, rows, session_id, quiet):
    """Resize session pane."""
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
def clear_screen(session_id, filter_expr, all_flag, dry_run, quiet):
    """Clear session screen (Ctrl+L). Supports --where / --all for bulk."""
    bulk = bool(filter_expr or all_flag)
    if not bulk:
        cleared_id = None
        async def _run(connection):
            nonlocal cleared_id
            session = await resolve_session(connection, session_id)
            cleared_id = session.session_id
            if not dry_run:
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
        for s, r in pairs:
            cleared.append(r)
            if not dry_run:
                await s.async_send_text('\x0c')
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
        result = [l for l in result if not _SENTINEL_RE.match(l)]
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
