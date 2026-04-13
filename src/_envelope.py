# src/_envelope.py
"""Envelope scaffolding — exit-code taxonomy and schema version.

This module is the seed for CONTRACT §4 (envelope) and §6 (exit codes).
Phase 2 only ships the constants and a skeleton `ItaError`; the full
`emit_envelope()` helper and per-command wrapping lands in the Phase 3
envelope-exit-taxonomy branch.

See:
  - docs/CONTRACT.md §4 — envelope shape
  - docs/CONTRACT.md §6 — exit-code taxonomy
"""
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
	--json modes can render consistently. The envelope emitter (Phase 3)
	will turn this into the `error: {code, reason}` block.
	"""
	def __init__(self, code: str, reason: str):
		if code not in EXIT_CODES:
			raise ValueError(f"unknown ita exit code symbol: {code!r}")
		super().__init__(reason)
		self.code = code
		self.reason = reason
		self.exit_code = EXIT_CODES[code]
