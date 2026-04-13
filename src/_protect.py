# src/_protect.py
"""Session protection (~/.ita_protected).

A protected session is off-limits for write operations unless the caller
passes --force-protected. Stored as newline-delimited session IDs.

See docs/CONTRACT.md §10.
"""
from pathlib import Path

import click

PROTECTED_FILE = Path.home() / ".ita_protected"


def get_protected() -> set[str]:
	"""Return set of protected session IDs."""
	if not PROTECTED_FILE.exists():
		return set()
	return {line.strip() for line in PROTECTED_FILE.read_text().splitlines() if line.strip()}


def add_protected(session_id: str) -> None:
	"""Add session_id to the protected list."""
	existing = get_protected()
	existing.add(session_id)
	PROTECTED_FILE.write_text('\n'.join(sorted(existing)) + '\n')


def remove_protected(session_id: str) -> None:
	"""Remove session_id from the protected list."""
	existing = get_protected()
	existing.discard(session_id)
	if existing:
		PROTECTED_FILE.write_text('\n'.join(sorted(existing)) + '\n')
	else:
		PROTECTED_FILE.unlink(missing_ok=True)


def check_protected(session_id: str, force: bool = False) -> None:
	"""Raise ClickException if session_id is protected and force is False.

	Call this in any write command (run, send, key, inject, close, clear, restart)
	before performing the operation. Prevents accidentally writing to a designated
	session (e.g. the active Claude Code terminal) when focus shifts.
	"""
	if force:
		return
	if session_id in get_protected():
		raise click.ClickException(
			f"Session {session_id[:8]}… is protected (~/.ita_protected). "
			f"Use --force to override, or `ita unprotect -s {session_id[:8]}` to remove protection."
		)
