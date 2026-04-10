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

# Modules will be imported here once built (Tasks 3-12)
# import _orientation
# import _session
# import _io
# import _output
# import _layout
# import _management
# import _config
# import _interactive
# import _tmux
# import _events

if __name__ == '__main__':
    cli()
