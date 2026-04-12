#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["iterm2", "click"]
# ///
"""
ita — agent-first iTerm2 control.
Entry point. Imports and registers all command modules.
"""
import sys
from pathlib import Path

# Ensure src/ siblings are importable
sys.path.insert(0, str(Path(__file__).parent))

from _core import cli  # noqa: E402 — must come after sys.path modification

# Import all modules — each registers its commands on `cli` at import time
import _orientation  # noqa: E402, F401 — status, focus, version
import _overview     # noqa: E402, F401 — overview (single-call situational awareness, #124)
import _session      # noqa: E402, F401 — new, close, activate, name, restart, resize, clear, capture
import _send         # noqa: E402, F401 — run, send, inject (not _io: collides with built-in)
import _lock         # noqa: E402, F401 — lock, unlock (#109 session write-lock)
import _output       # noqa: E402, F401 — read (helpers: _clean_lines, _is_prompt_line)
import _stream       # noqa: E402, F401 — watch
import _query        # noqa: E402, F401 — wait, selection, copy, get-prompt
import _layout       # noqa: E402, F401 — split, pane, move, tab group, window group
import _layouts      # noqa: E402, F401 — save, restore, layouts group (list/delete/rename/export)
import _management   # noqa: E402, F401 — profile group, presets, theme
import _meta         # noqa: E402, F401 — commands, doctor
import _config       # noqa: E402, F401 — var, app, pref, broadcast groups
import _interactive  # noqa: E402, F401 — alert, ask, pick, save-dialog, menu group, repl
import _tmux         # noqa: E402, F401 — tmux -CC group
import _events       # noqa: E402, F401 — on group, coprocess, annotate, rpc

if __name__ == '__main__':
	cli()
