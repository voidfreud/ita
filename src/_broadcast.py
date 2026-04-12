# src/_broadcast.py
"""Broadcast commands: on, off, add, set, list."""
import json
import click
import iterm2
from _core import cli, run_iterm, resolve_session


@cli.group()
def broadcast():
	"""Control input broadcasting across panes."""
	pass


@broadcast.command('on')
@click.option('-s', '--session', 'session_id', default=None)
@click.option('--window', 'window_id', default=None)
@click.option('--dry-run', is_flag=True, help='Print what would be broadcast without doing it')
def broadcast_on(session_id, window_id, dry_run):
	"""Broadcast input to all panes in window."""
	domain_sessions = []
	async def _run(connection):
		nonlocal domain_sessions
		app = await iterm2.async_get_app(connection)
		await app.async_refresh_broadcast_domains()
		existing_domains = list(app.broadcast_domains)
		if session_id:
			session = await resolve_session(connection, session_id)
			domain = iterm2.BroadcastDomain()
			domain.add_session(session)
			domain_sessions = [session.session_id]
			if not dry_run:
				existing_domains.append(domain)
				await iterm2.async_set_broadcast_domains(connection, existing_domains)
			return
		w = app.get_window_by_id(window_id) if window_id else app.current_terminal_window
		if not w:
			return
		domain = iterm2.BroadcastDomain()
		for tab in w.tabs:
			for session in tab.sessions:
				domain.add_session(session)
				domain_sessions.append(session.session_id)
		if not dry_run:
			existing_domains.append(domain)
			await iterm2.async_set_broadcast_domains(connection, existing_domains)
	run_iterm(_run)
	if dry_run and domain_sessions:
		click.echo(f"Would broadcast to: {', '.join(domain_sessions)}")


@broadcast.command('off')
def broadcast_off():
	"""Stop all broadcasting."""
	async def _run(connection):
		await iterm2.async_set_broadcast_domains(connection, [])
	run_iterm(_run)


@broadcast.command('add')
@click.argument('session_ids', nargs=-1, required=True)
def broadcast_add(session_ids):
	"""Group sessions into a broadcast domain."""
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
		existing_domains = list(app.broadcast_domains)
		domain = iterm2.BroadcastDomain()
		for sid in unique_ids:
			s = app.get_session_by_id(sid)
			if not s:
				raise click.ClickException(
					f"Session {sid!r} not found. Run 'ita status' to list sessions.")
			domain.add_session(s)
		existing_domains.append(domain)
		await iterm2.async_set_broadcast_domains(connection, existing_domains)
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
		return [[s.session_id for s in d.sessions] for d in app.broadcast_domains]
	domains = run_iterm(_run) or []
	if use_json:
		click.echo(json.dumps(domains, indent=2))
		return
	if not domains:
		click.echo("No broadcast domains active.")
		return
	for i, domain in enumerate(domains):
		click.echo(f"Domain {i}: {', '.join(domain)}")
