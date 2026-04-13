# src/_readiness.py
"""ita stabilize — wait until a session meets readiness conditions (#268).

Usage:
	ita stabilize -s <id> [--require prompt,shell_integration,jobName,writable]
	              [--timeout 5s] [--json]

Flags polled:
	shell_alive          session object resolves without error
	prompt_visible       last screen line looks like a prompt (requires shell_integration)
	shell_integration_active  jobName/lastCommand variables available via iterm2 API
	jobName_populated    session variable 'jobName' is non-empty
	writable             no live write-lock held on session
"""
import asyncio
import json
import re
import time
import click
import iterm2
from _core import cli, run_iterm, resolve_session, _load_writelocks, _pid_alive


_POLL_INTERVAL = 0.05  # 50 ms


_ALL_FLAGS = (
	'shell_alive',
	'prompt_visible',
	'shell_integration_active',
	'jobName_populated',
	'writable',
)

_DEFAULT_REQUIRE = {'shell_alive', 'writable'}


def _parse_timeout(s: str) -> float:
	"""Parse '5s', '500ms', or bare float/int string → seconds."""
	s = s.strip()
	if s.endswith('ms'):
		return float(s[:-2]) / 1000
	if s.endswith('s'):
		return float(s[:-1])
	return float(s)


def _parse_require(s: str) -> set[str]:
	flags = {f.strip() for f in s.split(',') if f.strip()}
	unknown = flags - set(_ALL_FLAGS)
	if unknown:
		raise click.ClickException(
			f"Unknown --require flag(s): {', '.join(sorted(unknown))}. "
			f"Valid: {', '.join(_ALL_FLAGS)}"
		)
	return flags


async def _probe(session: 'iterm2.Session') -> dict[str, bool]:
	"""Single probe pass — returns all flag values."""
	result: dict[str, bool] = {}

	# shell_alive — if we resolved the session, it's alive
	result['shell_alive'] = True

	# shell_integration_active — try fetching a variable only set by shell integration
	si_var = None
	try:
		si_var = await session.async_get_variable('jobName')
		result['shell_integration_active'] = True
	except Exception:
		result['shell_integration_active'] = False

	# jobName_populated
	result['jobName_populated'] = bool(si_var)

	# prompt_visible — only meaningful if shell integration is active
	if result['shell_integration_active']:
		try:
			prompt = await iterm2.async_get_last_prompt(
				session.connection, session.session_id
			)
			result['prompt_visible'] = prompt is not None
		except Exception:
			result['prompt_visible'] = False
	else:
		result['prompt_visible'] = False

	# writable — no live write-lock on this session
	data = _load_writelocks()
	entry = data.get(session.session_id)
	if entry and _pid_alive(int(entry.get('pid', 0))):
		result['writable'] = False
	else:
		result['writable'] = True

	return result


@cli.command()
@click.option('-s', '--session', 'session_id', required=True,
	help='Session name, UUID, or 8+ char UUID prefix.')
@click.option('--require', 'require_str', default=','.join(sorted(_DEFAULT_REQUIRE)),
	show_default=True,
	help='Comma-separated flags that must be true for rc=0.')
@click.option('--timeout', 'timeout_str', default='5s', show_default=True,
	help='Max wait: 5s, 500ms, or bare seconds.')
@click.option('--json', 'use_json', is_flag=True,
	help='Always emit JSON envelope (default: only on failure).')
def stabilize(session_id, require_str, timeout_str, use_json):
	"""Wait until session meets readiness conditions.

	Polls every 50 ms until all --require flags are true or --timeout
	expires. Exits 0 when satisfied; non-zero with pending flags listed
	in error.pending (JSON) or on stderr (plain).
	"""
	try:
		required = _parse_require(require_str)
		timeout_s = _parse_timeout(timeout_str)
	except (ValueError, click.ClickException) as exc:
		raise click.ClickException(str(exc)) from exc

	async def _run(connection):
		session = await resolve_session(connection, session_id)
		deadline = asyncio.get_event_loop().time() + timeout_s
		flags: dict[str, bool] = {}
		while True:
			flags = await _probe(session)
			pending = [f for f in required if not flags.get(f, False)]
			if not pending:
				return flags, []
			if asyncio.get_event_loop().time() >= deadline:
				return flags, pending
			await asyncio.sleep(_POLL_INTERVAL)

	wall_start = time.monotonic()
	flags, pending = run_iterm(_run)
	elapsed_ms = int((time.monotonic() - wall_start) * 1000)

	envelope = {
		**flags,
		'elapsed_ms': elapsed_ms,
	}

	if pending:
		envelope['error'] = {'pending': pending}
		if use_json:
			click.echo(json.dumps(envelope, ensure_ascii=False))
		else:
			click.echo(
				f"Timeout: required flags not satisfied: {', '.join(pending)}",
				err=True,
			)
		raise SystemExit(1)

	if use_json:
		click.echo(json.dumps(envelope, ensure_ascii=False))
