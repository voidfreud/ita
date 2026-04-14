# src/_force.py
"""Shared `--force-*` option decorator for input commands (#294).

Lives in its own module so `_send.py`, `_run.py`, `_inject.py`, and any other
writer command can stack the same triple of flags without importing each other."""
import click


def _force_options(f):
	"""Decorator stacking --force-protected / --force-lock / --force (deprecated).

	Commands resolve the triple via `resolve_force_flags()` at call time."""
	f = click.option('--force', is_flag=True, hidden=True,
		help='DEPRECATED: use --force-protected and/or --force-lock (#294).')(f)
	f = click.option('--force-lock', is_flag=True,
		help='Override write-lock guard; reclaim from another live ita process (#294).')(f)
	f = click.option('--force-protected', is_flag=True,
		help='Override protected-session guard (#294).')(f)
	return f
