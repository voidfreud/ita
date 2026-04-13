# src/_envelope.py
"""Envelope assembly + exit-code taxonomy (CONTRACT §4, §6).

Phase 3 `envelope-exit-taxonomy` cluster.

Ships:
  - SCHEMA_VERSION, EXIT_CODES — the stable constants (unchanged).
  - ItaError — click.ClickException subclass carrying a §6 symbolic code.
  - emit_envelope() — assembles the §4 envelope and writes it to stdout
	(JSON mode) or writes a terse one-line success/error to stderr (plain
	mode, preserving the existing success_echo UX).
  - @ita_command(op, *, mutator=True) — wraps a Click command callback so
	every mutator gets consistent envelope/error handling with a single
	decorator application. Migration is piecemeal (pilot set this PR).

See docs/CONTRACT.md §3 (output), §4 (envelope), §6 (exit codes), §14 (invariants).
"""
import functools
import json
import sys
import time
from typing import Any

import click

SCHEMA_VERSION = "ita/1"

# Mode-independent exit codes (CONTRACT §6). Identical in plain, --json, and
# --json-stream modes. rc=1 is reserved for uncaught exceptions only.
EXIT_OK = 0
EXIT_NOT_FOUND = 2
EXIT_PROTECTED = 3
EXIT_TIMEOUT = 4
EXIT_LOCKED = 5
EXIT_BAD_ARGS = 6
EXIT_API_UNREACHABLE = 7
EXIT_NO_SHELL_INTEGRATION = 8

EXIT_CODES = {
	'ok': EXIT_OK,
	'not-found': EXIT_NOT_FOUND,
	'protected': EXIT_PROTECTED,
	'timeout': EXIT_TIMEOUT,
	'locked': EXIT_LOCKED,
	'bad-args': EXIT_BAD_ARGS,
	'api-unreachable': EXIT_API_UNREACHABLE,
	'no-shell-integration': EXIT_NO_SHELL_INTEGRATION,
}


class ItaError(click.ClickException):
	"""Structured error with a CONTRACT §6 code.

	Raise inside commands to signal a non-zero exit that both plain and
	--json modes render consistently. @ita_command turns this into an
	`error: {code, reason}` block on stdout (JSON) or a one-line stderr
	message + mapped exit code (plain)."""
	def __init__(self, code: str, reason: str):
		if code not in EXIT_CODES:
			raise ValueError(f"unknown ita exit code symbol: {code!r}")
		super().__init__(reason)
		self.code = code
		self.reason = reason
		self.exit_code = EXIT_CODES[code]


def emit_envelope(
	op: str,
	*,
	ok: bool,
	target: dict | None,
	state_before: str | None,
	state_after: str | None,
	elapsed_ms: int,
	warnings: list[dict],
	error: dict | None,
	data: dict | None,
	use_json: bool,
	mutator: bool = True,
) -> None:
	"""Emit the CONTRACT §4 envelope.

	JSON mode: single JSON object on stdout — always valid, even on error.
	Plain mode: success → terse confirmation on stderr (the `success_echo`
	channel, suppressible via -q); error → `ita: <reason>` on stderr.
	Stdout in plain mode is owned by the command body (the payload).
	"""
	if use_json:
		envelope: dict[str, Any] = {
			"schema": SCHEMA_VERSION,
			"ok": ok,
			"op": op,
			"target": target,
			"elapsed_ms": elapsed_ms,
			"warnings": warnings or [],
			"error": error,
			"data": data if data is not None else {},
		}
		if mutator:
			envelope["state_before"] = state_before
			envelope["state_after"] = state_after
		click.echo(json.dumps(envelope), nl=True)
	else:
		if not ok and error is not None:
			click.echo(f"ita: {error.get('reason', error.get('code', 'error'))}", err=True)


def ita_command(op: str, *, mutator: bool = True):
	"""Wrap a Click command callback with §4/§6 handling.

	The wrapped body SHOULD return a dict payload with any of:
	  - `target`: {session, name, ...} — the primary object acted on.
	  - `state_before`, `state_after`: §7 state names (mutators only).
	  - `data`: the command-specific payload dict.
	  - `warnings`: list of {code, reason}.
	Anything else in the dict is treated as `data` if `data` is absent.
	A bare None return is treated as success with empty data.

	Error mapping:
	  - ItaError → envelope.error = {code, reason}, exit EXIT_CODES[code].
	  - click.ClickException (legacy, non-ItaError) → wrapped as
		ItaError("bad-args", str(exc)). This conversion is documented so
		that pre-existing `raise click.ClickException(...)` sites in a
		wrapped body degrade gracefully to rc=6 / "bad-args" until they
		are migrated to a sharper code.
	  - On success, envelope.ok=true, rc=0.

	The decorator detects `--json` via Click's current context params
	(convention: the flag is named `use_json`). Commands that don't
	declare `--json` always emit plain-mode output; they still get
	consistent error handling and exit codes.
	"""
	def decorator(fn):
		@functools.wraps(fn)
		def wrapper(*args, **kwargs):
			start = time.monotonic()
			ctx = click.get_current_context(silent=True)
			params = ctx.params if ctx is not None else {}
			use_json = bool(params.get("use_json") or params.get("as_json"))
			try:
				payload = fn(*args, **kwargs) or {}
				if not isinstance(payload, dict):
					payload = {"data": payload}
				elapsed_ms = int((time.monotonic() - start) * 1000)
				target = payload.get("target")
				state_before = payload.get("state_before") if mutator else None
				state_after = payload.get("state_after") if mutator else None
				warnings = payload.get("warnings") or []
				# Anything not in the reserved key set becomes `data` if the
				# body didn't set `data` explicitly.
				data = payload.get("data")
				if data is None:
					reserved = {"target", "state_before", "state_after",
								"warnings", "data"}
					data = {k: v for k, v in payload.items() if k not in reserved}
				emit_envelope(
					op, ok=True, target=target,
					state_before=state_before, state_after=state_after,
					elapsed_ms=elapsed_ms, warnings=warnings,
					error=None, data=data,
					use_json=use_json, mutator=mutator,
				)
				return payload
			except ItaError as e:
				elapsed_ms = int((time.monotonic() - start) * 1000)
				emit_envelope(
					op, ok=False, target=None,
					state_before=None, state_after=None,
					elapsed_ms=elapsed_ms, warnings=[],
					error={"code": e.code, "reason": e.reason},
					data={}, use_json=use_json, mutator=mutator,
				)
				sys.exit(e.exit_code)
			except click.UsageError:
				# Click's UsageError (missing arg, bad option) is its own
				# concern — it owns rc=2 and the canonical 'Usage:' help
				# rendering. Don't intercept; let standalone_mode handling
				# upstream (or Click itself) render and exit.
				raise
			except click.ClickException as e:
				# Legacy path: any non-Ita, non-Usage ClickException is
				# surfaced as bad-args (rc=6). Migrate call sites to raise
				# ItaError with a sharper code when semantics are clearer
				# than "bad input".
				reason = e.format_message() if hasattr(e, "format_message") else str(e)
				elapsed_ms = int((time.monotonic() - start) * 1000)
				emit_envelope(
					op, ok=False, target=None,
					state_before=None, state_after=None,
					elapsed_ms=elapsed_ms, warnings=[],
					error={"code": "bad-args", "reason": reason},
					data={}, use_json=use_json, mutator=mutator,
				)
				sys.exit(EXIT_CODES["bad-args"])
		return wrapper
	return decorator
