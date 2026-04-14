# src/ita/__init__.py
"""ita — agent-first iTerm2 control.

Package entry. Importing this module loads every command module, which
registers commands on the shared `cli` group. The console-script
entrypoint (`ita = "ita:cli"` in pyproject.toml) imports this and calls
`cli()`.
"""
from ._core import cli  # re-exported at package level for `ita:cli`
from ._envelope import EXIT_CODES, ItaError, SCHEMA_VERSION  # noqa: F401


def main():
	"""Console-script entrypoint. Wraps cli() so an uncaught ItaError
	(raised by a non-migrated command via resolve_session) still exits
	with the §6-mapped code AND emits a §4 envelope on stdout when --json
	was on argv. Migrated @ita_command bodies emit the envelope themselves
	and never reach this fallback. See _envelope.py."""
	import json as _json
	import sys as _sys
	import click as _click

	def _argv_uses_json() -> bool:
		return any(a in ("--json", "--as-json") for a in _sys.argv[1:])

	# CONTRACT §10 "Auto-protect the Claude Code session (#340)": run once
	# per process before cli() dispatches. Best-effort — any failure is
	# swallowed inside the helper; command dispatch is never blocked.
	from ._claudecode import auto_protect_claudecode_session
	auto_protect_claudecode_session()

	try:
		cli(standalone_mode=False)
	except ItaError as e:
		if _argv_uses_json():
			envelope = {
				"schema": SCHEMA_VERSION,
				"ok": False,
				"op": _sys.argv[1] if len(_sys.argv) > 1 else "",
				"target": None,
				"state_before": None,
				"state_after": None,
				"elapsed_ms": 0,
				"warnings": [],
				"error": {"code": e.code, "reason": e.reason},
				"data": {},
			}
			_sys.stdout.write(_json.dumps(envelope) + "\n")
		else:
			_sys.stderr.write(f"ita: {e.reason}\n")
		_sys.exit(EXIT_CODES[e.code])
	except _click.ClickException as e:
		e.show()
		_sys.exit(e.exit_code)
	except _click.exceptions.Abort:
		_sys.stderr.write("Aborted!\n")
		_sys.exit(1)

# Import command modules for their side-effects (each registers on `cli`).
# noqa everywhere because these are unused at the name level.
from . import _orientation  # noqa: F401 — status, focus, version
from . import _overview     # noqa: F401 — overview
from . import _session      # noqa: F401 — new, close, activate, name, restart, resize, clear, capture
from . import _send         # noqa: F401 — run, send, inject, key
from . import _lock         # noqa: F401 — lock, unlock
from . import _output       # noqa: F401 — read
from . import _stream       # noqa: F401 — watch
from . import _query        # noqa: F401 — wait, selection, copy, get-prompt
from . import _pane         # noqa: F401 — split, pane, move, swap
from . import _tab          # noqa: F401 — tab group
from . import _layout       # noqa: F401 — window group
from . import _layouts      # noqa: F401 — layouts group
from . import _management   # noqa: F401 — profile group, presets
from . import _meta         # noqa: F401 — commands, doctor
from . import _config       # noqa: F401 — var, app, pref, broadcast
from . import _interactive  # noqa: F401 — alert, ask, pick, save-dialog, menu, repl
from . import _tmux         # noqa: F401 — tmux -CC group
from . import _events       # noqa: F401 — on group, on output/keystroke/focus/layout, annotate, rpc
from . import _on_prompt    # noqa: F401 — on prompt (#247 timeout fix)
from . import _on_session   # noqa: F401 — on session-new, on session-end
from . import _coprocess    # noqa: F401 — coprocess group
from . import _readiness    # noqa: F401 — stabilize

__all__ = ["cli"]
