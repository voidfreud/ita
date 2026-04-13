# src/ita/__init__.py
"""ita — agent-first iTerm2 control.

Package entry. Importing this module loads every command module, which
registers commands on the shared `cli` group. The console-script
entrypoint (`ita = "ita:cli"` in pyproject.toml) imports this and calls
`cli()`.
"""
from ._core import cli  # re-exported at package level for `ita:cli`

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
from . import _events       # noqa: F401 — on group, coprocess, annotate, rpc
from . import _readiness    # noqa: F401 — stabilize

__all__ = ["cli"]
