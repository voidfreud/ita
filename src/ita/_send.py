# src/_send.py
"""Input commands: `send` lives here; `run`, `inject`, `key` have moved to
sibling modules but are re-exported below so `from ita._send import run` etc.
keep working for tests and any external callers.

File is named _send.py rather than _io.py to avoid collision with Python's
built-in _io module. After the #12 split this module is a thin public facade;
each command's real body is in its own file (`_run.py`, `_inject.py`, `_stdin.py`,
`_probe.py`) so task #13's `inject` → envelope migration is a single-file edit."""
import click
from ._core import cli, run_iterm, resolve_session, check_protected, session_writelock
from ._lock import resolve_force_flags
from ._force import _force_options

# Re-exports: keep the pre-split import surface intact. Tests and callers
# that `from ita._send import run / inject / key / _parse_key / _trim_output_lines /
# _encode_inject_payload / _load_stdin_script / _has_shell_integration` must
# continue to work unchanged.
from ._run import run  # noqa: F401
from ._inject import (  # noqa: F401
	inject,
	key,
	_KEY_MAP,
	_parse_key,
	_encode_inject_payload,
)
from ._probe import (  # noqa: F401
	_has_shell_integration,
	_prompt_is_back,
	_escalate_interrupt,
	_trim_output_lines,
)
from ._stdin import _load_stdin_script  # noqa: F401


@cli.command()
@click.argument('text')
@click.option('--raw', is_flag=True, help='Do not append newline')
@click.option('-n', '--no-newline', 'no_newline', is_flag=True, help='Do not append newline (alias for --raw)')
@click.option('-s', '--session', 'session_id', default=None)
@_force_options
def send(text, raw, no_newline, session_id, force_protected, force_lock, force):
	"""Send text to session. Appends newline unless --raw or -n.
	Note: Broadcast domains are not honored by send; text is sent directly
	to the target session only. Use 'ita broadcast add' to group sessions
	for coordinated input, then use 'ita key' or 'ita run' for broadcast."""
	fp, fl = resolve_force_flags(force, force_protected, force_lock)
	async def _run(connection):
		session = await resolve_session(connection, session_id)
		check_protected(session.session_id, force_protected=fp)
		with session_writelock(session.session_id, force_lock=fl):
			await session.async_send_text(text if (raw or no_newline) else text + '\n')
	run_iterm(_run)
