# src/_config.py
"""Config commands: var group, app group, pref group, broadcast group."""
import click
import iterm2
from ._core import cli, run_iterm, resolve_session, confirm_or_skip, success_echo, check_protected, session_writelock
from ._envelope import ItaError, json_dumps
from ._lock import resolve_force_flags


# ── Variables ─────────────────────────────────────────────────────────────

@cli.group()
def var():
	"""Get, set and list variables at session/tab/window/app scope."""
	pass


# Flat set of all known iTerm2 built-in variable names (unqualified) so that
# var get/set can skip the automatic 'user.' prefix for built-ins.
_BUILTIN_VAR_NAMES = frozenset(
	name
	for names in (
		# Session-scope builtins
		['autoLogId', 'autoName', 'badge', 'bundleId', 'columns', 'rows',
		 'creationTimeString', 'hostname', 'id', 'jobName', 'jobPid',
		 'lastCommand', 'name', 'path', 'presentationName', 'pwd',
		 'processTitle', 'sessionId', 'terminalIconName', 'tty',
		 'tmuxPaneTitle', 'tmuxRole', 'tmuxWindowTitle', 'username'],
		# Tab-scope builtins
		['title', 'tabTitle'],
		# Window-scope builtins
		['frame', 'style', 'number'],
		# App-scope builtins
		['effectiveTheme', 'localhostName', 'pid', 'termid', 'profileName'],
	)
	for name in names
)


@var.command('get')
@click.argument('name')
@click.option('--scope', type=click.Choice(['session', 'tab', 'window', 'app']), default='session')
@click.option('-s', '--session', 'session_id', default=None)
@click.option('--tab', 'tab_id', default=None, help='Tab ID for --scope tab (required; no focus fallback, #342).')
@click.option('--window', 'window_id', default=None, help='Window ID for --scope window (required; no focus fallback, #342).')
@click.option('--json', 'use_json', is_flag=True, help='Emit {name, value, scope} as JSON (#142).')
def var_get(name, scope, session_id, tab_id, window_id, use_json):
	if not name.startswith('user.') and '.' not in name and name not in _BUILTIN_VAR_NAMES:
		name = f'user.{name}'
	# CONTRACT §2 "Focus-fallback is forbidden, end of (#342)": window/tab
	# scopes require an explicit reference; previously fell back to
	# app.current_terminal_window.
	if scope == 'window' and not window_id:
		raise ItaError("bad-args", "--scope window requires --window WINDOW_ID (#342).")
	if scope == 'tab' and not tab_id:
		raise ItaError("bad-args", "--scope tab requires --tab TAB_ID (#342).")
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		if scope == 'app':
			return await app.async_get_variable(name)
		elif scope == 'window':
			w = app.get_window_by_id(window_id)
			if not w:
				raise ItaError("not-found", f"Window {window_id!r} not found.")
			return await w.async_get_variable(name)
		elif scope == 'tab':
			t = app.get_tab_by_id(tab_id)
			if not t:
				raise ItaError("not-found", f"Tab {tab_id!r} not found.")
			return await t.async_get_variable(name)
		else:
			session = await resolve_session(connection, session_id)
			return await session.async_get_variable(name)
	result = run_iterm(_run)
	if use_json:
		click.echo(json_dumps({'name': name, 'value': result, 'scope': scope}, default=str))
	else:
		click.echo(str(result) if result is not None else '')


@var.command('set')
@click.argument('name')
@click.argument('value')
@click.option('--scope', type=click.Choice(['session', 'tab', 'window', 'app']), default='session')
@click.option('-s', '--session', 'session_id', default=None)
@click.option('--tab', 'tab_id', default=None, help='Tab ID for --scope tab (required; no focus fallback, #342).')
@click.option('--window', 'window_id', default=None, help='Window ID for --scope window (required; no focus fallback, #342).')
@click.option('-q', '--quiet', is_flag=True, help='Suppress confirmation (#139).')
@click.option('--dry-run', is_flag=True, help='Print what would be set without doing it (#143).')
@click.option('--confirm', is_flag=True, help='Require confirmation before mutating (#143).')
@click.option('-y', '--yes', is_flag=True, help='Skip confirmation prompt (#143).')
@click.option('--json', 'use_json', is_flag=True, help='Emit {ok, name, scope} as JSON (#142).')
def var_set(name, value, scope, session_id, tab_id, window_id, quiet, dry_run, confirm, yes, use_json):
	"""Set a variable. iTerm2 requires custom variables to use the 'user.' prefix;
	it is added automatically if not present."""
	if not name.strip():
		raise ItaError("bad-args", "Variable name is required")
	if not name.startswith('user.') and '.' not in name and name not in _BUILTIN_VAR_NAMES:
		name = f'user.{name}'
	# CONTRACT §2 "Focus-fallback is forbidden, end of (#342)".
	if scope == 'window' and not window_id:
		raise ItaError("bad-args", "--scope window requires --window WINDOW_ID (#342).")
	if scope == 'tab' and not tab_id:
		raise ItaError("bad-args", "--scope tab requires --tab TAB_ID (#342).")
	msg = f"set {scope} variable {name} = {value!r}"
	if dry_run:
		click.echo(f"Would: {msg}")
		return
	if confirm and not confirm_or_skip(msg, dry_run=False, yes=yes):
		return
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		if scope == 'app':
			await app.async_set_variable(name, value)
		elif scope == 'window':
			w = app.get_window_by_id(window_id)
			if not w:
				raise ItaError("not-found", f"Window {window_id!r} not found.")
			await w.async_set_variable(name, value)
		elif scope == 'tab':
			t = app.get_tab_by_id(tab_id)
			if not t:
				raise ItaError("not-found", f"Tab {tab_id!r} not found.")
			await t.async_set_variable(name, value)
		else:
			session = await resolve_session(connection, session_id)
			await session.async_set_variable(name, value)
	run_iterm(_run)
	if use_json:
		click.echo(json_dumps({'ok': True, 'name': name, 'scope': scope}))
	else:
		success_echo(f"Set: {name} ({scope})", quiet=quiet)


# Well-known iTerm2 built-in variable names per scope. iTerm2's Python API has no
# "list all variables" call, so we probe a known set and print the non-empty ones.
# Custom variables (user.*) cannot be enumerated via the API — only those set in
# the current ita invocation are observable, which is why this lists built-ins only.
_KNOWN_VARS = {
	'session': [
		'autoLogId', 'autoName', 'badge', 'bundleId', 'columns', 'rows',
		'creationTimeString', 'hostname', 'id', 'jobName', 'jobPid',
		'lastCommand', 'name', 'path', 'presentationName', 'pwd',
		'processTitle', 'sessionId', 'terminalIconName', 'tty',
		'tmuxPaneTitle', 'tmuxRole', 'tmuxWindowTitle', 'username',
	],
	'tab': ['id', 'tmuxWindowTitle', 'title', 'tabTitle'],
	'window': [
		'id', 'frame', 'currentTab.tmuxWindowTitle', 'style', 'number',
	],
	'app': [
		'effectiveTheme', 'localhostName', 'pid', 'currentTab.currentSession.name',
	],
}


@var.command('list')
@click.option('--scope', type=click.Choice(['session', 'tab', 'window', 'app']),
			  default=None, help='Limit to one scope (default: all scopes).')
@click.option('-s', '--session', 'session_id', default=None)
@click.option('--tab', 'tab_id', default=None, help='Tab ID; required if --scope tab (#342).')
@click.option('--window', 'window_id', default=None, help='Window ID; required if --scope window (#342).')
@click.option('--json', 'use_json', is_flag=True)
def var_list(scope, session_id, tab_id, window_id, use_json):
	"""List variables by probing well-known iTerm2 built-ins. iTerm2's API has
	no enumeration primitive, so custom 'user.*' variables are not discoverable."""
	# CONTRACT §2 "Focus-fallback is forbidden, end of (#342)": when the user
	# explicitly names --scope window / --scope tab, require a matching
	# explicit reference; no silent fallback to current_terminal_window.
	if scope == 'window' and not window_id:
		raise ItaError("bad-args", "--scope window requires --window WINDOW_ID (#342).")
	if scope == 'tab' and not tab_id:
		raise ItaError("bad-args", "--scope tab requires --tab TAB_ID (#342).")
	scopes = [scope] if scope else ['session', 'tab', 'window', 'app']

	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		out = {}
		for sc in scopes:
			target = None
			if sc == 'app':
				target = app
			elif sc == 'window':
				# Default (scope unset): skip window scope if no explicit ref —
				# silent focus fallback is forbidden. Mirror of the session
				# branch's #287 treatment.
				if window_id:
					target = app.get_window_by_id(window_id)
				else:
					target = None
			elif sc == 'tab':
				if tab_id:
					target = app.get_tab_by_id(tab_id)
				else:
					target = None
			else:
				# #287: when session scope is *explicitly requested* and no
				# session can be resolved, surface the failure rather than
				# silently degrading to empty (violates §14.1 "never lie to
				# the caller"). When the user didn't name `--scope session`
				# (default = all scopes) and there's no `-s`, skip the
				# session scope rather than error — other scopes still work.
				if scope == 'session' or session_id:
					target = await resolve_session(connection, session_id)
				else:
					target = None
			scope_vals = {}
			if target is not None:
				for name in _KNOWN_VARS[sc]:
					try:
						val = await target.async_get_variable(name)
					except Exception:
						val = None
					if val not in (None, ''):
						scope_vals[name] = val
			out[sc] = scope_vals
		return out

	result = run_iterm(_run) or {}
	if use_json:
		click.echo(json_dumps(result, pretty=True, default=str))
		return
	for sc in scopes:
		vals = result.get(sc, {})
		if not vals:
			continue
		if not scope:
			click.echo(f"# {sc}")
		for k, v in vals.items():
			click.echo(f"{k}={v}")


# ── App control ───────────────────────────────────────────────────────────

@cli.group('app')
def app_group():
	"""Control the iTerm2 application."""
	pass


@app_group.command('version')
def app_version():
	"""Show iTerm2 application version."""
	import subprocess
	result = subprocess.run(
		['osascript', '-e', 'tell application "iTerm2" to get version'],
		capture_output=True, text=True)
	click.echo(result.stdout.strip() or 'unknown')


@app_group.command('activate')
def app_activate():
	"""Bring iTerm2 to front."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		await app.async_activate(raise_all_windows=True, ignoring_other_apps=True)
	run_iterm(_run)


@app_group.command('hide')
def app_hide():
	"""Hide iTerm2."""
	import subprocess
	subprocess.run(['osascript', '-e',
		'tell application "System Events" to set visible of process "iTerm2" to false'])


@app_group.command('quit')
def app_quit():
	"""Quit iTerm2."""
	import subprocess
	subprocess.run(['osascript', '-e', 'tell application "iTerm2" to quit'])


@app_group.command('theme')
def app_theme():
	"""Show current UI theme (light/dark/auto)."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		return await app.async_get_theme()
	result = run_iterm(_run)
	if isinstance(result, (list, tuple)):
		click.echo(' '.join(str(x) for x in result))
	else:
		click.echo(result or '')


# ── Preferences ───────────────────────────────────────────────────────────

@cli.group()
def pref():
	"""Read and write iTerm2 preferences."""
	pass


def _resolve_pref_key(key: str):
	"""Resolve a string to PreferenceKey enum, or raise ClickException with a useful hint."""
	try:
		return iterm2.PreferenceKey[key]
	except KeyError:
		valid = sorted(k for k in dir(iterm2.PreferenceKey) if not k.startswith('_'))[:10]
		raise click.ClickException(
			f"Unknown preference key: {key!r}. "
			f"Run 'ita pref list' to see all valid keys. Examples: {', '.join(valid)}."
		)


@pref.command('get')
@click.argument('key')
def pref_get(key):
	async def _run(connection):
		return await iterm2.async_get_preference(connection, _resolve_pref_key(key))
	result = run_iterm(_run)
	if result is not None:
		# iTerm2 returns Python bool or int 1/0 for boolean prefs
		if isinstance(result, bool) or (isinstance(result, int) and result in (0, 1)):
			click.echo('true' if result else 'false')
		else:
			click.echo(result)


def _coerce_pref_value(value: str):
	"""Coerce a string value to int, bool, or string for preference storage."""
	# Bool check first (before int, since 0/1 are valid ints)
	low = value.lower()
	if low == 'true':
		return True
	if low == 'false':
		return False
	# Try int, then fall back to string
	try:
		return int(value)
	except ValueError:
		pass
	try:
		return float(value)
	except ValueError:
		pass
	return value


@pref.command('set')
@click.argument('key')
@click.argument('value')
@click.option('-q', '--quiet', is_flag=True, help='Suppress confirmation (#139).')
@click.option('--dry-run', is_flag=True, help='Print what would be set (#143).')
@click.option('--confirm', is_flag=True, help='Require confirmation (#143).')
@click.option('-y', '--yes', is_flag=True, help='Skip confirmation prompt (#143).')
@click.option('--json', 'use_json', is_flag=True, help='Emit JSON result (#142).')
def pref_set(key, value, quiet, dry_run, confirm, yes, use_json):
	msg = f"set preference {key} = {value!r}"
	if dry_run:
		click.echo(f"Would: {msg}")
		return
	if confirm and not confirm_or_skip(msg, dry_run=False, yes=yes):
		return
	async def _run(connection):
		pref_key = _resolve_pref_key(key)
		typed = _coerce_pref_value(value)
		await iterm2.async_set_preference(connection, pref_key, typed)
	run_iterm(_run)
	if use_json:
		click.echo(json_dumps({'ok': True, 'key': key}))
	else:
		success_echo(f"Set: {key}", quiet=quiet)


@pref.command('list')
@click.option('--filter', 'filter_text', default=None)
@click.option('--json', 'use_json', is_flag=True, help='Emit as JSON array (#142).')
def pref_list(filter_text, use_json):
	async def _run(connection):
		keys = [k for k in dir(iterm2.PreferenceKey) if not k.startswith('_')]
		if filter_text:
			keys = [k for k in keys if filter_text.lower() in k.lower()]
		return keys
	keys = run_iterm(_run) or []
	if use_json:
		click.echo(json_dumps(keys))
	else:
		for k in keys:
			click.echo(k)


@pref.command('theme')
def pref_theme():
	"""Show current theme tags and dark/light mode."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		return await app.async_get_theme()
	result = run_iterm(_run)
	if isinstance(result, (list, tuple)):
		click.echo(' '.join(str(x) for x in result))
	else:
		click.echo(result or '')


@pref.command('tmux')
@click.argument('key', required=False)
@click.argument('value', required=False)
@click.option('-q', '--quiet', is_flag=True, help='Suppress confirmation.')
def pref_tmux(key, value, quiet):
	"""Get all tmux prefs, or set a specific one.
	Key is a PreferenceKey enum name (e.g. OPEN_TMUX_WINDOWS_IN)."""
	async def _run(connection):
		if key and value:
			pref_key = _resolve_pref_key(key)
			typed = int(value) if value.isdigit() else (
				True if value == 'true' else (False if value == 'false' else value))
			await iterm2.async_set_preference(connection, pref_key, typed)
		else:
			keys = ['OPEN_TMUX_WINDOWS_IN', 'TMUX_DASHBOARD_LIMIT',
					'AUTO_HIDE_TMUX_CLIENT_SESSION', 'USE_TMUX_PROFILE']
			return {k: await iterm2.async_get_preference(connection, _resolve_pref_key(k)) for k in keys}
	result = run_iterm(_run)
	if key and value:
		success_echo(f"Set: {key}", quiet=quiet)
	elif isinstance(result, dict):
		click.echo(json_dumps(result, pretty=True))


# ── Broadcast ─────────────────────────────────────────────────────────────

@cli.group()
def broadcast():
	"""Control input broadcasting across panes."""
	pass


@broadcast.command('on')
@click.option('-s', '--session', 'session_id', default=None)
@click.option('--window', 'window_id', default=None)
@click.option('--replace', is_flag=True,
			  help='Replace all existing broadcast domains (old behavior). '
				   'Default is to merge the new session into an existing domain.')
@click.option('-q', '--quiet', is_flag=True, help='Suppress confirmation (#139).')
@click.option('--dry-run', is_flag=True, help='Print what would be broadcast (#143).')
@click.option('--confirm', is_flag=True, help='Require confirmation (#143).')
@click.option('-y', '--yes', is_flag=True, help='Skip confirmation prompt (#143).')
def broadcast_on(session_id, window_id, replace, quiet, dry_run, confirm, yes):
	"""Broadcast input to all panes in window.

	By default merges into existing broadcast domains rather than replacing them
	(#103) — prevents silent data loss when adding a session to an active
	broadcast group. Pass --replace for the old atomic-replace behavior."""
	# CONTRACT §2 "Focus-fallback is forbidden, end of (#342)": require an
	# explicit -s or --window; the previous `app.current_terminal_window`
	# fallback is gone.
	if not session_id and not window_id:
		raise ItaError("bad-args",
			"no target specified. Use -s SESSION or --window WINDOW_ID. "
			"Focus-fallback is forbidden (CONTRACT §2, #342).")
	target = session_id or window_id
	msg = f"enable broadcast on {target}"
	if dry_run:
		click.echo(f"Would: {msg}")
		return
	if confirm and not confirm_or_skip(msg, dry_run=False, yes=yes):
		return
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		await app.async_refresh_broadcast_domains()
		existing = list(app.broadcast_domains) if not replace else []

		if session_id:
			session = await resolve_session(connection, session_id)
			# If there's already a domain, extend the first one; else create new.
			if existing:
				target_domain = existing[0]
				target_domain.add_session(session)
				domains = existing
			else:
				d = iterm2.BroadcastDomain()
				d.add_session(session)
				domains = [d]
			await iterm2.async_set_broadcast_domains(connection, domains)
		else:
			w = app.get_window_by_id(window_id)
			if not w:
				raise ItaError("not-found", f"Window {window_id!r} not found.")
			new_domain = iterm2.BroadcastDomain()
			for tab in w.tabs:
				for sess in tab.sessions:
					new_domain.add_session(sess)
			await iterm2.async_set_broadcast_domains(connection, existing + [new_domain])

		# Verify the API actually persisted the change (#249).
		await app.async_refresh_broadcast_domains()
		if not app.broadcast_domains:
			raise click.ClickException(
				"Broadcast enabled call succeeded but no domains were registered. "
				"iTerm2 may have silently rejected the request.")
	run_iterm(_run)
	success_echo(f"Broadcast enabled: {target}", quiet=quiet)


@broadcast.command('send')
@click.argument('text')
@click.option('--newline/--no-newline', default=True,
			  help='Append a newline so the shell executes (default: true).')
@click.option('--json', 'use_json', is_flag=True,
			  help='Emit per-session {session_id, ok, error} array (#279).')
@click.option('--on-dead', type=click.Choice(['fail', 'skip', 'prune']),
			  default='skip',
			  help='Behaviour when a session is unreachable: fail/skip/prune (#285).')
@click.option('--force-protected', is_flag=True,
			  help='Send to protected members too (#294). Off by default: protected sessions are skipped with a warning.')
@click.option('--force-lock', is_flag=True,
			  help='Override per-member write-lock guard (#294).')
@click.option('--force', is_flag=True, hidden=True,
			  help='DEPRECATED: use --force-protected and/or --force-lock (#294).')
def broadcast_send(text, newline, use_json, on_dead, force_protected, force_lock, force):
	"""Send TEXT to every session in every active broadcast domain (#147).

	iTerm2's broadcast-domain feature mirrors *keyboard* input, not API writes,
	so `ita send` bypasses the domain. This command fills that gap by iterating
	the current domains and calling async_send_text on each member.

	Sessions shared by multiple domains are sent to only once (#285).
	Every target is gated by CONTRACT §10 protect/lock checks per-member
	(#279 / §13)."""
	fp, fl = resolve_force_flags(force, force_protected, force_lock)
	payload = text + ('\n' if newline else '')
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		await app.async_refresh_broadcast_domains()
		domains = app.broadcast_domains
		if not domains:
			raise click.ClickException(
				"No active broadcast domains. Use `ita broadcast on` first.")

		# Deduplicate across domains (#285): keep first occurrence by session_id.
		seen_ids: set = set()
		unique_sessions = []
		for d in domains:
			for s in d.sessions:
				if s.session_id not in seen_ids:
					seen_ids.add(s.session_id)
					unique_sessions.append(s)

		results = []
		dead_ids: set = set()
		for s in unique_sessions:
			# #258, #279, §13 per-target gate. Protect/lock checks run BEFORE
			# each send so a protected member in the fleet doesn't leak input
			# under the orchestrator's ownership. Protected/locked members
			# are reported in `results` with ok=False and a structured code.
			try:
				check_protected(s.session_id, force_protected=fp)
			except ItaError as exc:
				results.append({'session_id': s.session_id, 'ok': False,
							   'error': exc.reason, 'code': exc.code})
				import sys as _sys
				print(f"Warning: skipping protected session {s.session_id}: {exc.reason}",
					  file=_sys.stderr)
				continue
			try:
				with session_writelock(s.session_id, force_lock=fl):
					await s.async_send_text(payload)
				results.append({'session_id': s.session_id, 'ok': True, 'error': None})
				continue
			except ItaError as exc:
				# locked or similar structured refusal — record, move on.
				results.append({'session_id': s.session_id, 'ok': False,
							   'error': exc.reason, 'code': exc.code})
				import sys as _sys
				print(f"Warning: skipping locked session {s.session_id}: {exc.reason}",
					  file=_sys.stderr)
				continue
			except Exception as exc:
				err = str(exc)
				if on_dead == 'fail':
					raise click.ClickException(
						f"Session {s.session_id!r} unreachable: {err}")
				elif on_dead == 'prune':
					dead_ids.add(s.session_id)
					import click as _click
					_click.echo(f"Warning: pruning dead session {s.session_id}", err=True)
				else:  # skip
					import sys as _sys
					print(f"Warning: skipping dead session {s.session_id}: {err}",
						  file=_sys.stderr)
				results.append({'session_id': s.session_id, 'ok': False, 'error': err})

		if dead_ids:
			# Re-set domains without the pruned sessions.
			surviving = []
			for d in domains:
				dom = iterm2.BroadcastDomain()
				for s in d.sessions:
					if s.session_id not in dead_ids:
						dom.add_session(s)
				if dom.sessions:
					surviving.append(dom)
			await iterm2.async_set_broadcast_domains(connection, surviving)

		return results

	results = run_iterm(_run) or []
	if use_json:
		click.echo(json_dumps(results, pretty=True))
	else:
		ok_count = sum(1 for r in results if r['ok'])
		click.echo(f"Sent to {ok_count}/{len(results)} session(s).")


@broadcast.command('off')
@click.option('-q', '--quiet', is_flag=True, help='Suppress confirmation (#139).')
@click.option('--dry-run', is_flag=True, help='Print what would be disabled (#143).')
@click.option('--confirm', is_flag=True, help='Require confirmation (#143).')
@click.option('-y', '--yes', is_flag=True, help='Skip confirmation prompt (#143).')
def broadcast_off(quiet, dry_run, confirm, yes):
	"""Stop all broadcasting."""
	msg = "disable all broadcast domains"
	if dry_run:
		click.echo(f"Would: {msg}")
		return
	if confirm and not confirm_or_skip(msg, dry_run=False, yes=yes):
		return
	async def _run(connection):
		await iterm2.async_set_broadcast_domains(connection, [])
	run_iterm(_run)
	success_echo("Broadcast disabled.", quiet=quiet)


@broadcast.command('add')
@click.argument('session_ids', nargs=-1, required=True)
def broadcast_add(session_ids):
	"""Add sessions to the first existing broadcast domain, or create a new one (#220).

	Merges into existing domains rather than replacing them. Use `broadcast set`
	for an explicit atomic replace."""
	# Deduplicate input while preserving order.
	seen = set()
	unique_ids = []
	for sid in session_ids:
		if sid in seen:
			raise click.ClickException(f"Duplicate session ID: {sid}")
		seen.add(sid)
		unique_ids.append(sid)
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		await app.async_refresh_broadcast_domains()
		existing = list(app.broadcast_domains)

		# Resolve session objects.
		sessions = []
		for sid in unique_ids:
			s = app.get_session_by_id(sid)
			if not s:
				raise click.ClickException(
					f"Session {sid!r} not found. Run 'ita status' to list sessions.")
			sessions.append(s)

		if existing:
			# Merge: add to first domain, skip already-present sessions (#220).
			target_domain = existing[0]
			already = {s.session_id for s in target_domain.sessions}
			for s in sessions:
				if s.session_id not in already:
					target_domain.add_session(s)
					already.add(s.session_id)
			await iterm2.async_set_broadcast_domains(connection, existing)
		else:
			domain = iterm2.BroadcastDomain()
			for s in sessions:
				domain.add_session(s)
			await iterm2.async_set_broadcast_domains(connection, [domain])
	run_iterm(_run)


@broadcast.command('set')
@click.argument('domains', nargs=-1, required=True)
def broadcast_set(domains):
	"""Set all broadcast domains atomically. Each arg is a comma-separated
	list of session IDs forming one domain. Replaces any existing domains."""
	parsed = []
	for d in domains:
		ids = [sid.strip() for sid in d.split(',') if sid.strip()]
		if not ids:
			raise click.ClickException(f"Empty broadcast domain: {d!r}")
		parsed.append(ids)
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		built = []
		for ids in parsed:
			dom = iterm2.BroadcastDomain()
			for sid in ids:
				s = app.get_session_by_id(sid)
				if not s:
					raise click.ClickException(
						f"Session {sid!r} not found. Run 'ita status' to list sessions.")
				dom.add_session(s)
			built.append(dom)
		await iterm2.async_set_broadcast_domains(connection, built)
	run_iterm(_run)


@broadcast.command('list')
@click.option('--json', 'use_json', is_flag=True)
def broadcast_list(use_json):
	"""List active broadcast domains."""
	async def _run(connection):
		app = await iterm2.async_get_app(connection)
		await app.async_refresh_broadcast_domains()
		return [
			[
				{'session_id': s.session_id, 'session_name': (s.name or '')}
				for s in d.sessions
			]
			for d in app.broadcast_domains
		]
	domains = run_iterm(_run) or []
	if use_json:
		click.echo(json_dumps(domains, pretty=True))
		return
	if not domains:
		click.echo("No broadcast domains.")
		return
	for i, domain in enumerate(domains):
		click.echo(f"Domain {i} ({len(domain)} session{'s' if len(domain) != 1 else ''}):")
		if not domain:
			click.echo("  (empty)")
			continue
		for member in domain:
			name = member['session_name'] or '(unnamed)'
			click.echo(f"  {member['session_id']}  {name}")
