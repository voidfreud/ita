# src/_core.py
"""
Core helpers shared by all ita modules.
run_iterm(), resolve_session(), strip(), sticky context.
"""
import asyncio
import json
import sys
from pathlib import Path
from collections.abc import Awaitable, Callable
from typing import Any

import click
import iterm2

# ── Sticky context ─────────────────────────────────────────────────────────

CONTEXT_FILE = Path.home() / ".ita_context"

def get_sticky() -> str | None:
    """Return the sticky session ID, or None."""
    if CONTEXT_FILE.exists():
        v = CONTEXT_FILE.read_text().strip()
        return v if v else None
    return None

def set_sticky(session_id: str) -> None:
    """Persist session_id as sticky target."""
    CONTEXT_FILE.write_text(session_id)

def clear_sticky() -> None:
    """Remove sticky target."""
    CONTEXT_FILE.unlink(missing_ok=True)

# ── Output helpers ─────────────────────────────────────────────────────────

PROMPT_CHARS = ('❯', '$', '#', '%', '→', '>>')

def strip(text: str) -> str:
    """Remove null bytes from terminal output."""
    return text.replace('\x00', '')

def last_non_empty_index(contents) -> int:
    """Last non-empty line index in a ScreenContents, or -1 if blank.
    number_of_lines is grid height, not content height — the bottom rows are
    usually empty whitespace, so callers must scan backward to find content."""
    for i in range(contents.number_of_lines - 1, -1, -1):
        if strip(contents.line(i).string).strip():
            return i
    return -1

def emit(data: Any, use_json: bool = False) -> None:
    """Print data as plain text or JSON."""
    if use_json:
        click.echo(json.dumps(data, indent=2))
    else:
        if isinstance(data, list):
            for item in data:
                click.echo(item)
        else:
            click.echo(data)

# ── iTerm2 runner ──────────────────────────────────────────────────────────

def run_iterm(coro: Callable[..., Awaitable[Any]]) -> Any:
    """
    Run an iTerm2 async coroutine synchronously.
    Usage:
        result = run_iterm(lambda conn: some_async_fn(conn))
    """
    result: dict = {}
    error: dict = {}

    async def _main(connection):
        try:
            result['value'] = await coro(connection)
        except Exception as exc:
            error['exc'] = exc

    iterm2.run_until_complete(_main)

    if error:
        exc = error['exc']
        if isinstance(exc, click.ClickException):
            raise exc
        raise click.ClickException(str(exc))

    return result.get('value')

# ── Session resolver ────────────────────────────────────────────────────────

async def resolve_session(connection, session_id: str | None = None) -> 'iterm2.Session':
    """
    Resolve target session.
    Precedence: explicit session_id > sticky > currently focused.
    Raises ClickException if nothing found.
    """
    app = await iterm2.async_get_app(connection)
    sid = session_id or get_sticky()
    if sid:
        session = app.get_session_by_id(sid)
        if session:
            return session
        # Prefix match fallback — makes the 8-char IDs from `ita status` usable.
        sid_lower = sid.lower()
        matches = []
        for window in app.terminal_windows:
            for tab in window.tabs:
                for s in tab.sessions:
                    if s.session_id.lower().startswith(sid_lower):
                        matches.append(s)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise click.ClickException(
                f"Session prefix {sid!r} is ambiguous: matches {len(matches)} sessions.")
        raise click.ClickException(
            f"Session {sid!r} not found. Run 'ita status' to list sessions."
        )
    # Fall back to currently focused session
    window = app.current_terminal_window
    if window and window.current_tab and window.current_tab.current_session:
        return window.current_tab.current_session
    raise click.ClickException(
        "No session available. Run 'ita new' to create one."
    )

# ── CLI root ────────────────────────────────────────────────────────────────

@click.group()
@click.version_option(version='0.6.0')
def cli():
    """ita — agent-first iTerm2 control."""
    pass
