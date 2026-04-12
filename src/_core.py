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

# ── Protected sessions ──────────────────────────────────────────────────────

PROTECTED_FILE = Path.home() / ".ita_protected"

def get_protected() -> set[str]:
    """Return set of protected session IDs."""
    if not PROTECTED_FILE.exists():
        return set()
    return {line.strip() for line in PROTECTED_FILE.read_text().splitlines() if line.strip()}

def add_protected(session_id: str) -> None:
    """Add session_id to the protected list."""
    existing = get_protected()
    existing.add(session_id)
    PROTECTED_FILE.write_text('\n'.join(sorted(existing)) + '\n')

def remove_protected(session_id: str) -> None:
    """Remove session_id from the protected list."""
    existing = get_protected()
    existing.discard(session_id)
    if existing:
        PROTECTED_FILE.write_text('\n'.join(sorted(existing)) + '\n')
    else:
        PROTECTED_FILE.unlink(missing_ok=True)

def check_protected(session_id: str, force: bool = False) -> None:
    """Raise ClickException if session_id is in ~/.ita_protected and force is False.

    Call this in any write command (run, send, key, inject, close, clear, restart)
    before performing the operation. This prevents accidentally writing to a
    designated session (e.g. the active Claude Code terminal) when focus shifts."""
    if force:
        return
    if session_id in get_protected():
        raise click.ClickException(
            f"Session {session_id[:8]}… is protected (~/.ita_protected). "
            f"Use --force to override, or `ita unprotect -s {session_id[:8]}` to remove protection."
        )

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


async def read_session_lines(
    session: 'iterm2.Session',
    include_scrollback: bool = False,
) -> list[str]:
    """Read session output as a list of cleaned strings.

    When include_scrollback is False (default) returns only the visible grid —
    fast path, behavior unchanged. When True, returns scrollback history + the
    mutable grid via async_get_line_info + async_get_contents inside a
    Transaction so the session can't mutate between the two calls.

    Null bytes are stripped from every line; trailing blank lines are dropped.
    Callers filter ita sentinel rows themselves."""
    if not include_scrollback:
        contents = await session.async_get_screen_contents()
        result = [strip(contents.line(i).string) for i in range(contents.number_of_lines)]
    else:
        async with iterm2.Transaction(session.connection):
            info = await session.async_get_line_info()
            total = info.mutable_area_height + info.scrollback_buffer_height
            # first_line must be >= overflow; async_get_contents returns
            # however many lines are actually available.
            lines = await session.async_get_contents(info.overflow, total)
        result = [strip(line.string) for line in lines]
    while result and not result[-1].strip():
        result.pop()
    return result

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

__version__ = '1.1.0'

@click.group()
@click.version_option(version=__version__)
def cli():
    """ita — agent-first iTerm2 control."""
    pass
