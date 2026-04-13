# src/_lock.py
"""Session write-lock CLI (#109).

`ita lock -s NAME`       acquire a persistent write-lock
`ita unlock -s NAME`     release it
`ita lock --list`        show all locks (live + stale)

Commands that mutate a session (run, send, key, inject, close, clear, restart)
acquire the lock for the duration of the call and release it in a finally
block, so a crashed invocation can't leave a permanent lock. See _core.py for
the lock API and stale-PID reclaim logic.
"""
import click
from ._core import (
	cli, run_iterm, resolve_session,
	acquire_writelock, release_writelock, get_writelocks, _pid_alive,
	confirm_or_skip, success_echo,
)


@cli.command()
@click.option('-s', '--session', 'session_id', default=None,
	help='Session to write-lock (name, UUID, or 8+ char UUID prefix).')
@click.option('--list', 'list_only', is_flag=True, help='List all write-locks.')
def lock(session_id, list_only):
	"""Manually acquire a persistent write-lock on a session.

	Unlike the per-command lock (which releases when the write finishes), this
	keeps the lock held by the current shell's PID until `ita unlock` or the
	process exits. Handy when you want to reserve a session across several
	commands while another agent is active."""
	if list_only:
		data = get_writelocks()
		if not data:
			click.echo("No write-locks.")
			return
		for sid, entry in sorted(data.items()):
			pid = int(entry.get('pid', 0))
			alive = 'live' if _pid_alive(pid) else 'stale'
			click.echo(f"{sid}\tpid={pid}\t{alive}\t{entry.get('at', '?')}")
		return
	async def _resolve(connection):
		session = await resolve_session(connection, session_id)
		return session.session_id
	sid = run_iterm(_resolve)
	if acquire_writelock(sid):
		click.echo(f"Write-locked: {sid}")
	else:
		raise click.ClickException(
			f"Session {sid[:8]}… is already write-locked by another live process."
		)


@cli.command()
@click.option('-s', '--session', 'session_id', default=None,
	help='Session to unlock.')
@click.option('-y', '--yes', 'force', is_flag=True, help='Skip confirmation prompt.')
@click.option('--dry-run', is_flag=True, help='Print what would be unlocked without doing it.')
@click.option('-q', '--quiet', is_flag=True, help='Suppress confirmation message.')
def unlock(session_id, force, dry_run, quiet):
	"""Release a persistent write-lock (reverse of `ita lock`)."""
	if not confirm_or_skip("release write-lock", dry_run=dry_run, yes=force):
		return
	async def _resolve(connection):
		session = await resolve_session(connection, session_id)
		return session.session_id
	sid = run_iterm(_resolve)
	# release_writelock is a no-op if we don't own the entry, so warn the user
	# if the lock is held by someone else before we call it.
	data = get_writelocks()
	entry = data.get(sid)
	if entry is None:
		success_echo(f"Not write-locked: {sid}", quiet)
		return
	import os
	if int(entry.get('pid', 0)) != os.getppid():
		# Different owner — best-effort release: drop the entry if the PID is
		# stale, otherwise refuse (don't let one shell steal another's lock).
		if not _pid_alive(int(entry.get('pid', 0))):
			data.pop(sid, None)
			from _core import _save_writelocks
			_save_writelocks(data)
			success_echo(f"Cleared stale lock: {sid}", quiet)
			return
		raise click.ClickException(
			f"Session {sid[:8]}… is write-locked by pid {entry.get('pid')}, "
			f"not this process. Use --force on the write command instead, or "
			f"end that process."
		)
	release_writelock(sid)
	success_echo(f"Unlocked: {sid}", quiet)
