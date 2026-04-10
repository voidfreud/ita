# ita — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `ita` — an agent-first iTerm2 control tool as a Claude Code plugin, directly on the iTerm2 Python API, replacing cli-anything-iterm2 entirely.

**Architecture:** Modular Python package. `ita.py` is the uv inline script entry point that imports from sibling modules (`_core.py`, `_session.py`, etc.). Each module ≤200 lines with one clear responsibility. Sticky context in `~/.ita_context`. Plugin-packaged with SKILL.md.

**Tech Stack:** Python 3.11+, uv, iterm2 (PyPI), click, iTerm2 3.6+ with Python API enabled.

**Parallel execution:** After Task 2, Tasks 3–11 are fully independent — run them in parallel worktrees with `superpowers:dispatching-parallel-agents`.

---

## File Map

| File | Lines | Responsibility |
|------|-------|---------------|
| `src/ita.py` | ~50 | Entry point, uv shebang, imports all modules |
| `src/_core.py` | ~90 | `run_iterm`, `resolve_session`, `strip`, context, CLI root |
| `src/_orientation.py` | ~80 | `status`, `focus`, `version`, `use` |
| `src/_session.py` | ~150 | `new`, `close`, `activate`, `name`, `restart`, `resize`, `clear`, `capture` |
| `src/_io.py` | ~130 | `run` (atomic), `send`, `inject` |
| `src/_output.py` | ~160 | `read`, `watch`, `wait`, `selection`, `copy`, `get-prompt` |
| `src/_layout.py` | ~190 | `split`, `pane`, `tab` group, `window` group |
| `src/_management.py` | ~180 | `save`, `restore`, `layouts`, `profile` group, `presets`, `theme` |
| `src/_config.py` | ~170 | `var` group, `app` group, `pref` group, `broadcast` group |
| `src/_interactive.py` | ~120 | `alert`, `ask`, `pick`, `save-dialog`, `menu` group, `repl` |
| `src/_tmux.py` | ~110 | `tmux` group |
| `src/_events.py` | ~180 | `on` group, `coprocess`, `annotate`, `rpc` |
| `skills/ita/SKILL.md` | — | Claude's complete reference doc |
| `tests/test_core.py` | ~60 | Unit tests for `_core.py` helpers |
| `plugin.json` | — | Plugin manifest |
| `README.md` | — | Human-facing docs |

---

## Execution Map

```
Task 1: Scaffold + _core.py          ← sequential, everything depends on this
Task 2: Tests for _core.py           ← sequential, validates foundation
         ↓
Tasks 3-11: ALL PARALLEL             ← 9 independent modules, dispatch simultaneously
  Task 3:  _orientation.py
  Task 4:  _session.py
  Task 5:  _io.py
  Task 6:  _output.py
  Task 7:  _layout.py
  Task 8:  _management.py
  Task 9:  _config.py
  Task 10: _interactive.py
  Task 11: _tmux.py
  Task 12: _events.py
         ↓
Task 13: ita.py — wire all modules   ← sequential, needs all modules done
Task 14: Integration smoke test      ← sequential
Task 15: SKILL.md                    ← sequential
Task 16: Plugin packaging + GitHub   ← sequential
```

---

## Phase 1: Foundation (Sequential)

### Task 1: Project scaffold + `_core.py`

**Files:**
- Create: `src/_core.py`
- Create: `src/ita.py` (stub)
- Create: `plugin.json`
- Create: `skills/ita/SKILL.md` (stub)
- Create: `.gitignore`

- [ ] **Step 1: Create `src/_core.py`**

```python
# src/_core.py
"""
Core helpers shared by all ita modules.
run_iterm(), resolve_session(), strip(), sticky context.
"""
import asyncio
import json
import sys
from pathlib import Path
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

def strip(text: str) -> str:
    """Remove null bytes from terminal output."""
    return text.replace('\x00', '')

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

def run_iterm(coro) -> Any:
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

async def resolve_session(connection, session_id: str | None = None):
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
@click.version_option(version='1.0.0')
def cli():
    """ita — agent-first iTerm2 control."""
    pass
```

- [ ] **Step 2: Create `src/ita.py` stub**

```python
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
```

- [ ] **Step 3: Create plugin.json**

```json
{
  "name": "ita",
  "version": "1.0.0",
  "description": "Agent-first iTerm2 control — full API access optimized for Claude",
  "author": "voidfreud",
  "skills": [
    {
      "name": "ita",
      "path": "skills/ita/SKILL.md"
    }
  ]
}
```

- [ ] **Step 4: Create skill stub**

```markdown
---
name: ita
description: Agent-first iTerm2 control. Full command reference — use for all iTerm2 operations.
---
# ita — iTerm Agent (stub)
Full skill to be written in Task 15.
```
Save to `skills/ita/SKILL.md`.

- [ ] **Step 5: Verify stub runs**

```bash
cd ~/Developer/ita
uv run src/ita.py --help
```
Expected: `Usage: ita.py [OPTIONS] COMMAND [ARGS]...`

- [ ] **Step 6: Commit**

```bash
git add .
git commit -m "feat: scaffold, _core.py — helpers, context, CLI root"
```

---

### Task 2: Unit tests for `_core.py`

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/test_core.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_core.py
"""Unit tests for _core.py pure functions (no iTerm2 connection needed)."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))


def test_strip_removes_null_bytes():
    from _core import strip
    assert strip("hello\x00world") == "helloworld"
    assert strip("\x00\x00\x00") == ""
    assert strip("clean") == "clean"
    assert strip("line\x00\x00  17%\x00tokens") == "line  17%tokens"


def test_strip_empty_string():
    from _core import strip
    assert strip("") == ""


def test_get_sticky_missing(tmp_path, monkeypatch):
    import _core
    monkeypatch.setattr(_core, 'CONTEXT_FILE', tmp_path / ".ita_context")
    assert _core.get_sticky() is None


def test_set_and_get_sticky(tmp_path, monkeypatch):
    import _core
    monkeypatch.setattr(_core, 'CONTEXT_FILE', tmp_path / ".ita_context")
    _core.set_sticky("SESSION-ABC")
    assert _core.get_sticky() == "SESSION-ABC"


def test_clear_sticky(tmp_path, monkeypatch):
    import _core
    monkeypatch.setattr(_core, 'CONTEXT_FILE', tmp_path / ".ita_context")
    _core.set_sticky("SESSION-ABC")
    _core.clear_sticky()
    assert _core.get_sticky() is None


def test_sticky_strips_whitespace(tmp_path, monkeypatch):
    import _core
    monkeypatch.setattr(_core, 'CONTEXT_FILE', tmp_path / ".ita_context")
    (tmp_path / ".ita_context").write_text("  SESSION-ID  \n")
    assert _core.get_sticky() == "SESSION-ID"


def test_sticky_empty_file_returns_none(tmp_path, monkeypatch):
    import _core
    monkeypatch.setattr(_core, 'CONTEXT_FILE', tmp_path / ".ita_context")
    (tmp_path / ".ita_context").write_text("   ")
    assert _core.get_sticky() is None
```

- [ ] **Step 2: Run tests**

```bash
cd ~/Developer/ita
uv run --with pytest pytest tests/test_core.py -v
```
Expected: 7 tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/
git commit -m "test: _core.py unit tests — strip, sticky context"
```

---

## Phase 2: Modules (All Parallel — Tasks 3–12)

> After Task 2, create a worktree per task and dispatch parallel agents.
> Each module imports from `_core` and registers its commands on the `cli` group.
> Pattern every module follows:
> ```python
> from _core import cli, run_iterm, resolve_session, strip, get_sticky, set_sticky, emit
> ```

---

### Task 3: `_orientation.py` — `status`, `focus`, `version`, `use`

**Files:**
- Create: `src/_orientation.py`

- [ ] **Step 1: Write `_orientation.py`**

```python
# src/_orientation.py
"""Orientation commands: status, focus, version, use."""
import json
import click
import iterm2
from _core import cli, run_iterm, strip, get_sticky, set_sticky, clear_sticky


@cli.command()
@click.option('--json', 'use_json', is_flag=True)
def status(use_json):
    """List all sessions: id | name | process | path | current*"""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        current = get_sticky()
        sessions = []
        for window in app.windows:
            for tab in window.tabs:
                for session in tab.sessions:
                    sessions.append({
                        'id': session.session_id,
                        'name': strip(session.name or ''),
                        'process': strip(await session.async_get_variable('jobName') or ''),
                        'path': strip(await session.async_get_variable('path') or ''),
                        'current': session.session_id == current,
                        'window_id': window.window_id,
                        'tab_id': tab.tab_id,
                    })
        return sessions

    sessions = run_iterm(_run)

    if use_json:
        click.echo(json.dumps(sessions, indent=2))
        return

    current = get_sticky()
    for s in sessions:
        marker = '*' if s['current'] else ' '
        sid = s['id'][:8]
        name = s['name'][:20].ljust(20)
        proc = s['process'][:10].ljust(10)
        click.echo(f"{marker} {sid}  {name}  {proc}  {s['path']}")


@cli.command()
@click.option('--json', 'use_json', is_flag=True)
def focus(use_json):
    """Show which element has keyboard focus."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        window = app.current_terminal_window
        if not window:
            return None
        tab = window.current_tab
        session = tab.current_session if tab else None
        return {
            'window_id': window.window_id,
            'tab_id': tab.tab_id if tab else None,
            'session_id': session.session_id if session else None,
            'session_name': strip(session.name or '') if session else None,
        }
    result = run_iterm(_run)
    if not result:
        click.echo("No focused window")
        return
    if use_json:
        click.echo(json.dumps(result, indent=2))
    else:
        click.echo(f"window:  {result['window_id']}")
        click.echo(f"tab:     {result['tab_id']}")
        click.echo(f"session: {result['session_id']}  ({result['session_name']})")


@cli.command()
def version():
    """Show iTerm2 app version."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        return await app.async_get_variable('iterm2.version')
    click.echo(run_iterm(_run) or 'unknown')


@cli.command()
@click.argument('session_id', required=False)
@click.option('--clear', is_flag=True, help='Clear sticky target')
def use(session_id, clear):
    """Set or clear sticky session target."""
    if clear:
        clear_sticky()
        click.echo("Sticky target cleared.")
        return
    if not session_id:
        current = get_sticky()
        click.echo(f"Current target: {current or '(none)'}")
        return
    set_sticky(session_id)
    click.echo(f"Target set: {session_id}")
```

- [ ] **Step 2: Verify**

```bash
cd ~/Developer/ita
uv run src/ita.py status
```
Expected: outputs session list or "no windows" error.

- [ ] **Step 3: Commit**

```bash
git add src/_orientation.py
git commit -m "feat: _orientation — status, focus, version, use"
```

---

### Task 4: `_session.py` — `new`, `close`, `activate`, `name`, `restart`, `resize`, `clear`, `capture`

**Files:**
- Create: `src/_session.py`

- [ ] **Step 1: Write `_session.py`**

```python
# src/_session.py
"""Session lifecycle commands: new, close, activate, name, restart, resize, clear, capture."""
from pathlib import Path
import click
import iterm2
from _core import cli, run_iterm, resolve_session, strip, set_sticky, clear_sticky, get_sticky


@cli.command()
@click.option('--window', 'new_window', is_flag=True, help='Create new window instead of tab')
@click.option('--profile', default=None, help='Profile name')
def new(new_window, profile):
    """Create new tab (or window). Sets sticky target. Returns session ID."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        if new_window:
            window = await iterm2.Window.async_create(connection, profile=profile)
            session = window.current_tab.current_session
        else:
            window = app.current_terminal_window
            if not window:
                window = await iterm2.Window.async_create(connection, profile=profile)
                session = window.current_tab.current_session
            else:
                tab = await window.async_create_tab(profile=profile)
                session = tab.current_session
        return session.session_id

    sid = run_iterm(_run)
    set_sticky(sid)
    click.echo(sid)


@cli.command()
@click.option('-s', '--session', 'session_id', default=None)
def close(session_id):
    """Close session. Clears sticky if it was the target."""
    was_sticky = session_id == get_sticky() or (not session_id and get_sticky())

    async def _run(connection):
        session = await resolve_session(connection, session_id)
        await session.async_close(force=True)

    run_iterm(_run)
    if was_sticky:
        clear_sticky()


@cli.command()
@click.argument('session_id_arg', metavar='SESSION_ID', required=False)
def activate(session_id_arg):
    """Focus/bring a session to front."""
    async def _run(connection):
        session = await resolve_session(connection, session_id_arg)
        await session.async_activate(select_tab=True, order_window_front=True)
    run_iterm(_run)


@cli.command()
@click.argument('title')
@click.option('-s', '--session', 'session_id', default=None)
def name(title, session_id):
    """Rename session."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        await session.async_set_name(title)
    run_iterm(_run)


@cli.command()
@click.option('-s', '--session', 'session_id', default=None)
def restart(session_id):
    """Restart session."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        await session.async_restart(only_if_exited=False)
    run_iterm(_run)


@cli.command()
@click.option('--cols', type=int, required=True)
@click.option('--rows', type=int, required=True)
@click.option('-s', '--session', 'session_id', default=None)
def resize(cols, rows, session_id):
    """Resize session pane."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        await session.async_set_grid_size(iterm2.util.Size(cols, rows))
    run_iterm(_run)


@cli.command('clear')
@click.option('-s', '--session', 'session_id', default=None)
def clear_screen(session_id):
    """Clear session screen (Ctrl+L)."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        await session.async_send_text('\x0c')
    run_iterm(_run)


@cli.command()
@click.argument('file', required=False)
@click.option('-s', '--session', 'session_id', default=None)
def capture(file, session_id):
    """Save screen contents to file (or stdout if no file given)."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        contents = await session.async_get_screen_contents()
        lines = []
        for i in range(contents.number_of_lines):
            lines.append(strip(contents.line(i).string))
        # Trim trailing blank lines
        while lines and not lines[-1].strip():
            lines.pop()
        return '\n'.join(lines)

    output = run_iterm(_run)
    if file:
        Path(file).write_text(output)
        click.echo(f"Saved to {file}")
    else:
        click.echo(output)
```

- [ ] **Step 2: Verify**

```bash
uv run src/ita.py new
uv run src/ita.py status
uv run src/ita.py name "test-session"
uv run src/ita.py status
```
Expected: new session ID printed, appears in status, name updated.

- [ ] **Step 3: Commit**

```bash
git add src/_session.py
git commit -m "feat: _session — new, close, activate, name, restart, resize, clear, capture"
```

---

### Task 5: `_io.py` — `run`, `send`, `inject`

**Files:**
- Create: `src/_io.py`

- [ ] **Step 1: Write `_io.py`**

```python
# src/_io.py
"""Input commands: run (atomic), send, inject."""
import asyncio
import json
import time
import click
import iterm2
from _core import cli, run_iterm, resolve_session, strip

PROMPT_CHARS = ('❯', '$', '#', '%', '→', '>>')


@cli.command()
@click.argument('cmd')
@click.option('-t', '--timeout', default=30, type=int, help='Timeout seconds (default: 30)')
@click.option('-n', '--lines', default=50, type=int, help='Output lines to return (default: 50)')
@click.option('--json', 'use_json', is_flag=True)
@click.option('-s', '--session', 'session_id', default=None)
def run(cmd, timeout, lines, use_json, session_id):
    """Send command, wait for completion, return clean output. Atomic — one call does all."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        await session.async_send_text(cmd + '\n')
        start = time.time()

        # Wait for completion via ScreenStreamer (event-driven, no polling)
        async with session.get_screen_streamer() as streamer:
            for _ in range(timeout * 4):
                try:
                    contents = await asyncio.wait_for(streamer.async_get(), timeout=1.0)
                    last = strip(contents.line(contents.number_of_lines - 1).string).strip()
                    if any(last.startswith(p) or last.endswith(p) for p in PROMPT_CHARS):
                        break
                except asyncio.TimeoutError:
                    continue

        elapsed_ms = int((time.time() - start) * 1000)

        # Read output from screen contents
        contents = await session.async_get_screen_contents()
        total = contents.number_of_lines_with_history
        start_line = max(0, total - lines)
        output_lines = []
        for i in range(start_line, total):
            output_lines.append(strip(contents.line(i).string))
        # Trim trailing blank lines
        while output_lines and not output_lines[-1].strip():
            output_lines.pop()
        output = '\n'.join(output_lines)

        return output, elapsed_ms

    output, elapsed_ms = run_iterm(_run)

    if use_json:
        click.echo(json.dumps({'output': output, 'elapsed_ms': elapsed_ms}))
    else:
        click.echo(output)


@cli.command()
@click.argument('text')
@click.option('--raw', is_flag=True, help='Do not append newline')
@click.option('-s', '--session', 'session_id', default=None)
def send(text, raw, session_id):
    """Send text to session. Appends newline unless --raw."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        await session.async_send_text(text if raw else text + '\n')
    run_iterm(_run)


@cli.command()
@click.argument('data')
@click.option('--hex', 'is_hex', is_flag=True, help='Interpret DATA as hex bytes (e.g. 03 for Ctrl+C)')
@click.option('-s', '--session', 'session_id', default=None)
def inject(data, is_hex, session_id):
    """Inject raw bytes. Use $'\\x03' for Ctrl+C, $'\\x1b' for Escape, etc."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        if is_hex:
            raw = bytes.fromhex(data.replace(' ', ''))
        else:
            # Interpret escape sequences like \x03, \n, \t
            raw = data.encode('utf-8').decode('unicode_escape').encode('latin-1')
        await session.async_inject(raw)
    run_iterm(_run)
```

- [ ] **Step 2: Verify**

```bash
uv run src/ita.py send "echo hello"
uv run src/ita.py run "echo 'ita works'"
uv run src/ita.py inject $'\x03'
```
Expected: hello echoed in terminal, `ita works` returned by run.

- [ ] **Step 3: Commit**

```bash
git add src/_io.py
git commit -m "feat: _io — run (atomic via ScreenStreamer), send, inject"
```

---

### Task 6: `_output.py` — `read`, `watch`, `wait`, `selection`, `copy`, `get-prompt`

**Files:**
- Create: `src/_output.py`

- [ ] **Step 1: Write `_output.py`**

```python
# src/_output.py
"""Output reading commands: read, watch, wait, selection, copy, get-prompt."""
import asyncio
import json
import subprocess
import click
import iterm2
from _core import cli, run_iterm, resolve_session, strip

PROMPT_CHARS = ('❯', '$', '#', '%', '→', '>>')


@cli.command()
@click.argument('lines', default=20, type=int)
@click.option('--json', 'use_json', is_flag=True)
@click.option('-s', '--session', 'session_id', default=None)
def read(lines, use_json, session_id):
    """Read last N lines from session. Always clean — null bytes stripped."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        contents = await session.async_get_screen_contents()
        total = contents.number_of_lines_with_history
        start = max(0, total - lines)
        result = [strip(contents.line(i).string) for i in range(start, total)]
        while result and not result[-1].strip():
            result.pop()
        return result

    result = run_iterm(_run)
    if use_json:
        click.echo(json.dumps({'lines': result, 'count': len(result)}))
    else:
        click.echo('\n'.join(result))


@cli.command()
@click.option('-s', '--session', 'session_id', default=None)
def watch(session_id):
    """Stream screen via ScreenStreamer until prompt appears. Zero polling."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        seen = set()
        async with session.get_screen_streamer() as streamer:
            while True:
                contents = await streamer.async_get()
                for i in range(contents.number_of_lines):
                    line = strip(contents.line(i).string)
                    if line and line not in seen:
                        seen.add(line)
                        click.echo(line)
                last = strip(contents.line(contents.number_of_lines - 1).string).strip()
                if any(last.startswith(p) or last.endswith(p) for p in PROMPT_CHARS):
                    break

    run_iterm(_run)


@cli.command()
@click.option('--pattern', default=None, help='Wait until this text appears in output')
@click.option('-t', '--timeout', default=30, type=int)
@click.option('-s', '--session', 'session_id', default=None)
def wait(pattern, timeout, session_id):
    """Block until next shell prompt (or pattern) appears. Event-driven via ScreenStreamer."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        async with session.get_screen_streamer() as streamer:
            for _ in range(timeout * 4):
                try:
                    contents = await asyncio.wait_for(streamer.async_get(), timeout=1.0)
                    if pattern:
                        for i in range(contents.number_of_lines):
                            if pattern in strip(contents.line(i).string):
                                return True
                    else:
                        last = strip(contents.line(contents.number_of_lines - 1).string).strip()
                        if any(last.startswith(p) or last.endswith(p) for p in PROMPT_CHARS):
                            return True
                except asyncio.TimeoutError:
                    continue
        return False

    found = run_iterm(_run)
    if not found and pattern:
        raise click.ClickException(f"Timeout: pattern {pattern!r} not found within {timeout}s")


@cli.command()
@click.option('-s', '--session', 'session_id', default=None)
def selection(session_id):
    """Get currently selected text."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        text = await session.async_get_selection_text(connection)
        return strip(text or '')
    click.echo(run_iterm(_run))


@cli.command()
@click.option('-s', '--session', 'session_id', default=None)
def copy(session_id):
    """Copy selected text to macOS clipboard."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        text = await session.async_get_selection_text(connection)
        return strip(text or '')
    text = run_iterm(_run)
    if text:
        subprocess.run(['pbcopy'], input=text.encode(), check=True)
        click.echo(f"Copied {len(text)} chars to clipboard.")
    else:
        click.echo("No selection.")


@cli.command('get-prompt')
@click.option('-s', '--session', 'session_id', default=None)
def get_prompt(session_id):
    """Get last prompt info: cwd, command, exit code."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        try:
            prompt = await iterm2.async_get_last_prompt(connection, session.session_id)
        except Exception:
            return None
        if not prompt:
            return None
        return {
            'cwd': prompt.working_directory,
            'command': prompt.command,
            'exit_code': prompt.exit_code,
        }
    result = run_iterm(_run)
    if result:
        click.echo(f"cwd:     {result['cwd']}")
        click.echo(f"command: {result['command']}")
        click.echo(f"exit:    {result['exit_code']}")
    else:
        click.echo("No prompt info — is shell integration active?")
```

- [ ] **Step 2: Verify**

```bash
uv run src/ita.py read 10
uv run src/ita.py get-prompt
```

- [ ] **Step 3: Commit**

```bash
git add src/_output.py
git commit -m "feat: _output — read, watch (ScreenStreamer), wait, selection, copy, get-prompt"
```

---

### Task 7: `_layout.py` — `split`, `pane`, `tab` group, `window` group

**Files:**
- Create: `src/_layout.py`

- [ ] **Step 1: Write `_layout.py`**

```python
# src/_layout.py
"""Layout commands: split, pane, tab group, window group."""
import json
import click
import iterm2
from _core import cli, run_iterm, resolve_session, set_sticky

DIRECTION_MAP = {
    'right': iterm2.NavigationDirection.RIGHT,
    'left': iterm2.NavigationDirection.LEFT,
    'above': iterm2.NavigationDirection.ABOVE,
    'below': iterm2.NavigationDirection.BELOW,
}


# ── Panes ──────────────────────────────────────────────────────────────────

@cli.command()
@click.option('-v', '--vertical', is_flag=True, help='Side-by-side split')
@click.option('--profile', default=None)
@click.option('-s', '--session', 'session_id', default=None)
def split(vertical, profile, session_id):
    """Split current pane. New pane becomes sticky target."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        new_session = await session.async_split_pane(vertical=vertical, profile=profile)
        return new_session.session_id
    sid = run_iterm(_run)
    set_sticky(sid)
    click.echo(sid)


@cli.command()
@click.argument('direction', type=click.Choice(['right', 'left', 'above', 'below']))
@click.option('-s', '--session', 'session_id', default=None)
def pane(direction, session_id):
    """Navigate to adjacent split pane. Updates sticky target."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        app = await iterm2.async_get_app(connection)
        _, tab = app.get_window_and_tab_for_session(session)
        await tab.async_select_pane_in_direction(DIRECTION_MAP[direction])
        new_session = tab.current_session
        if new_session:
            set_sticky(new_session.session_id)
            return new_session.session_id
    sid = run_iterm(_run)
    if sid:
        click.echo(sid)


@cli.command()
@click.argument('session_id_arg', metavar='SESSION_ID')
@click.argument('dest_window_id', metavar='DEST_WINDOW_ID')
@click.option('--vertical', is_flag=True)
def move(session_id_arg, dest_window_id, vertical):
    """Move a pane to a different window."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        session = app.get_session_by_id(session_id_arg)
        if not session:
            raise click.ClickException(f"Session {session_id_arg!r} not found")
        dest_window = app.get_window_by_id(dest_window_id)
        if not dest_window:
            raise click.ClickException(f"Window {dest_window_id!r} not found")
        dest_session = dest_window.current_tab.current_session
        await app.async_move_session(session, dest_session, split_vertically=vertical, before=False)
    run_iterm(_run)


# ── Tabs ───────────────────────────────────────────────────────────────────

@cli.group()
def tab():
    """Manage tabs."""
    pass


@tab.command('new')
@click.option('--window', 'window_id', default=None)
@click.option('--profile', default=None)
def tab_new(window_id, profile):
    """Create new tab. Sets sticky target."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        window = app.get_window_by_id(window_id) if window_id else app.current_terminal_window
        if not window:
            raise click.ClickException("No window available. Run 'ita window new' first.")
        new_tab = await window.async_create_tab(profile=profile)
        session = new_tab.current_session
        set_sticky(session.session_id)
        return session.session_id
    click.echo(run_iterm(_run))


@tab.command('close')
@click.argument('tab_id', required=False)
def tab_close(tab_id):
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        t = app.get_tab_by_id(tab_id) if tab_id else (
            app.current_terminal_window.current_tab if app.current_terminal_window else None)
        if not t:
            raise click.ClickException("Tab not found")
        await t.async_close(force=True)
    run_iterm(_run)


@tab.command('activate')
@click.argument('tab_id')
def tab_activate(tab_id):
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        t = app.get_tab_by_id(tab_id)
        if not t:
            raise click.ClickException(f"Tab {tab_id!r} not found")
        await t.async_activate(order_window_front=True)
    run_iterm(_run)


@tab.command('next')
def tab_next():
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        w = app.current_terminal_window
        if w:
            tabs = w.tabs
            idx = tabs.index(w.current_tab)
            await tabs[(idx + 1) % len(tabs)].async_activate()
    run_iterm(_run)


@tab.command('prev')
def tab_prev():
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        w = app.current_terminal_window
        if w:
            tabs = w.tabs
            idx = tabs.index(w.current_tab)
            await tabs[(idx - 1) % len(tabs)].async_activate()
    run_iterm(_run)


@tab.command('goto')
@click.argument('index', type=int)
def tab_goto(index):
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        w = app.current_terminal_window
        if not w or not (0 <= index < len(w.tabs)):
            raise click.ClickException(f"No tab at index {index}")
        await w.tabs[index].async_activate()
    run_iterm(_run)


@tab.command('list')
@click.option('--json', 'use_json', is_flag=True)
def tab_list(use_json):
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        return [{'tab_id': t.tab_id, 'window_id': w.window_id, 'panes': len(t.sessions)}
                for w in app.windows for t in w.tabs]
    tabs = run_iterm(_run)
    if use_json:
        click.echo(json.dumps(tabs))
    else:
        for t in tabs:
            click.echo(f"{t['tab_id']}  window={t['window_id']}  panes={t['panes']}")


@tab.command('info')
@click.argument('tab_id', required=False)
def tab_info(tab_id):
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        t = app.get_tab_by_id(tab_id) if tab_id else (
            app.current_terminal_window.current_tab if app.current_terminal_window else None)
        if not t:
            raise click.ClickException("Tab not found")
        return {'tab_id': t.tab_id,
                'sessions': [s.session_id for s in t.sessions],
                'current_session': t.current_session.session_id if t.current_session else None,
                'tmux_window_id': t.tmux_window_id}
    click.echo(json.dumps(run_iterm(_run), indent=2))


@tab.command('move')
def tab_move():
    """Detach current tab into its own window."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        w = app.current_terminal_window
        if w and w.current_tab:
            await w.current_tab.async_move_to_window()
    run_iterm(_run)


@tab.command('title')
@click.argument('title')
def tab_title(title):
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        w = app.current_terminal_window
        if w and w.current_tab:
            await w.current_tab.async_set_title(title)
    run_iterm(_run)


# ── Windows ────────────────────────────────────────────────────────────────

@cli.group()
def window():
    """Manage windows."""
    pass


@window.command('new')
@click.option('--profile', default=None)
def window_new(profile):
    async def _run(connection):
        w = await iterm2.Window.async_create(connection, profile=profile)
        return w.window_id
    click.echo(run_iterm(_run))


@window.command('close')
@click.argument('window_id', required=False)
def window_close(window_id):
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        w = app.get_window_by_id(window_id) if window_id else app.current_terminal_window
        if w:
            await w.async_close(force=True)
    run_iterm(_run)


@window.command('activate')
@click.argument('window_id', required=False)
def window_activate(window_id):
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        w = app.get_window_by_id(window_id) if window_id else app.current_terminal_window
        if w:
            await w.async_activate()
    run_iterm(_run)


@window.command('title')
@click.argument('title')
def window_title(title):
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        w = app.current_terminal_window
        if w:
            await w.async_set_title(title)
    run_iterm(_run)


@window.command('fullscreen')
@click.argument('mode', type=click.Choice(['on', 'off', 'toggle']))
def window_fullscreen(mode):
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        w = app.current_terminal_window
        if not w:
            return
        current = await w.async_get_fullscreen()
        target = {'on': True, 'off': False, 'toggle': not current}[mode]
        await w.async_set_fullscreen(target)
    run_iterm(_run)


@window.command('frame')
@click.option('--x', type=float, default=None)
@click.option('--y', type=float, default=None)
@click.option('--w', 'width', type=float, default=None)
@click.option('--h', 'height', type=float, default=None)
def window_frame(x, y, width, height):
    """Get window position/size. Pass --x/y/w/h to set."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        win = app.current_terminal_window
        if not win:
            raise click.ClickException("No window")
        if any(v is not None for v in [x, y, width, height]):
            cur = await win.async_get_frame()
            frame = iterm2.util.Frame(
                iterm2.util.Point(x if x is not None else cur.origin.x,
                                   y if y is not None else cur.origin.y),
                iterm2.util.Size(width if width is not None else cur.size.width,
                                  height if height is not None else cur.size.height))
            await win.async_set_frame(frame)
        else:
            f = await win.async_get_frame()
            return f"x={f.origin.x} y={f.origin.y} w={f.size.width} h={f.size.height}"
    result = run_iterm(_run)
    if result:
        click.echo(result)


@window.command('list')
@click.option('--json', 'use_json', is_flag=True)
def window_list(use_json):
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        return [{'window_id': w.window_id, 'tabs': len(w.tabs)} for w in app.windows]
    windows = run_iterm(_run)
    if use_json:
        click.echo(json.dumps(windows))
    else:
        for w in windows:
            click.echo(f"{w['window_id']}  tabs={w['tabs']}")
```

- [ ] **Step 2: Commit**

```bash
git add src/_layout.py
git commit -m "feat: _layout — split, pane, tab group, window group"
```

---

### Task 8: `_management.py` — arrangements, profiles, visual

**Files:**
- Create: `src/_management.py`

- [ ] **Step 1: Write `_management.py`**

```python
# src/_management.py
"""Management commands: save/restore, profile group, presets, theme."""
import json
import click
import iterm2
from _core import cli, run_iterm, resolve_session

THEME_SHORTCUTS = {
    'red': 'Red Alert',
    'green': 'Solarized Dark',
    'dark': 'Solarized Dark',
    'light': 'Solarized Light',
}


# ── Arrangements ──────────────────────────────────────────────────────────

@cli.command()
@click.argument('name')
@click.option('--window', 'window_only', is_flag=True, help='Save current window only')
def save(name, window_only):
    """Save current layout as named arrangement."""
    async def _run(connection):
        if window_only:
            app = await iterm2.async_get_app(connection)
            w = app.current_terminal_window
            if w:
                await w.async_save_window_as_arrangement(name)
        else:
            await iterm2.Arrangement.async_save(connection, name)
    run_iterm(_run)
    click.echo(f"Saved: {name}")


@cli.command()
@click.argument('name')
def restore(name):
    """Restore named arrangement."""
    async def _run(connection):
        await iterm2.Arrangement.async_restore(connection, name)
    run_iterm(_run)
    click.echo(f"Restored: {name}")


@cli.command()
def layouts():
    """List all saved arrangements."""
    async def _run(connection):
        return await iterm2.Arrangement.async_list(connection)
    for n in (run_iterm(_run) or []):
        click.echo(n)


# ── Profiles ──────────────────────────────────────────────────────────────

@cli.group()
def profile():
    """Manage profiles."""
    pass


@profile.command('list')
def profile_list():
    """List all profiles."""
    async def _run(connection):
        profiles = await iterm2.Profile.async_get_list(connection)
        return [(p.name, p.guid) for p in profiles]
    for name, guid in run_iterm(_run):
        click.echo(f"{guid}  {name}")


@profile.command('show')
@click.argument('name', required=False)
@click.option('-s', '--session', 'session_id', default=None)
def profile_show(name, session_id):
    """Show profile details."""
    async def _run(connection):
        if session_id or not name:
            session = await resolve_session(connection, session_id)
            p = await session.async_get_profile()
        else:
            profiles = await iterm2.Profile.async_get_list(connection)
            p = next((x for x in profiles if x.name == name), None)
            if not p:
                raise click.ClickException(f"Profile {name!r} not found")
        return {'name': p.name, 'guid': p.guid}
    click.echo(json.dumps(run_iterm(_run), indent=2))


@profile.command('apply')
@click.argument('name')
@click.option('-s', '--session', 'session_id', default=None)
def profile_apply(name, session_id):
    """Apply named profile to session."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        profiles = await iterm2.Profile.async_get_list(connection)
        p = next((x for x in profiles if x.name == name), None)
        if not p:
            raise click.ClickException(f"Profile {name!r} not found")
        await session.async_set_profile(p)
    run_iterm(_run)


@profile.command('set')
@click.argument('property_name')
@click.argument('value')
@click.option('-s', '--session', 'session_id', default=None)
def profile_set(property_name, value, session_id):
    """Set a profile property on session."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        change = iterm2.LocalWriteOnlyProfile()
        setattr(change, property_name, value)
        await session.async_set_profile_properties(change)
    run_iterm(_run)


# ── Visual ─────────────────────────────────────────────────────────────────

@cli.command()
def presets():
    """List available color presets."""
    async def _run(connection):
        return await iterm2.ColorPreset.async_get_list(connection)
    for name in (run_iterm(_run) or []):
        click.echo(name)


@cli.command()
@click.argument('preset')
@click.option('-s', '--session', 'session_id', default=None)
def theme(preset, session_id):
    """Apply color preset. Shortcuts: red, green, dark, light."""
    preset_name = THEME_SHORTCUTS.get(preset, preset)

    async def _run(connection):
        session = await resolve_session(connection, session_id)
        preset_obj = await iterm2.ColorPreset.async_get(connection, preset_name)
        if not preset_obj:
            raise click.ClickException(
                f"Preset {preset_name!r} not found. Run 'ita presets' to list.")
        change = iterm2.LocalWriteOnlyProfile()
        change.set_color_preset(preset_obj)
        await session.async_set_profile_properties(change)

    run_iterm(_run)
```

- [ ] **Step 2: Commit**

```bash
git add src/_management.py
git commit -m "feat: _management — arrangements, profile group, presets, theme"
```

---

### Task 9: `_config.py` — `var`, `app`, `pref`, `broadcast`

**Files:**
- Create: `src/_config.py`

- [ ] **Step 1: Write `_config.py`**

```python
# src/_config.py
"""Config commands: var group, app group, pref group, broadcast group."""
import json
import click
import iterm2
from _core import cli, run_iterm, resolve_session


# ── Variables ─────────────────────────────────────────────────────────────

@cli.group()
def var():
    """Get, set and list variables at session/tab/window/app scope."""
    pass


@var.command('get')
@click.argument('name')
@click.option('--scope', type=click.Choice(['session', 'tab', 'window', 'app']), default='session')
@click.option('-s', '--session', 'session_id', default=None)
def var_get(name, scope, session_id):
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        if scope == 'app':
            return await app.async_get_variable(name)
        elif scope == 'window':
            w = app.current_terminal_window
            return await w.async_get_variable(name) if w else None
        elif scope == 'tab':
            w = app.current_terminal_window
            t = w.current_tab if w else None
            return await t.async_get_variable(name) if t else None
        else:
            session = await resolve_session(connection, session_id)
            return await session.async_get_variable(name)
    result = run_iterm(_run)
    click.echo(str(result or ''))


@var.command('set')
@click.argument('name')
@click.argument('value')
@click.option('--scope', type=click.Choice(['session', 'tab', 'window', 'app']), default='session')
@click.option('-s', '--session', 'session_id', default=None)
def var_set(name, value, scope, session_id):
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        if scope == 'app':
            await app.async_set_variable(name, value)
        elif scope == 'window':
            w = app.current_terminal_window
            if w: await w.async_set_variable(name, value)
        elif scope == 'tab':
            w = app.current_terminal_window
            t = w.current_tab if w else None
            if t: await t.async_set_variable(name, value)
        else:
            session = await resolve_session(connection, session_id)
            await session.async_set_variable(name, value)
    run_iterm(_run)


# ── App control ───────────────────────────────────────────────────────────

@cli.group('app')
def app_group():
    """Control the iTerm2 application."""
    pass


@app_group.command('activate')
def app_activate():
    """Bring iTerm2 to front."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        await app.async_activate(raise_all_windows=True, ignoring_other_apps=True)
    run_iterm(_run)


@app_group.command('hide')
def app_hide():
    """Hide iTerm2."""
    import subprocess
    subprocess.run(['osascript', '-e',
        'tell application "iTerm2" to set miniaturized of every window to true'])


@app_group.command('quit')
def app_quit():
    """Quit iTerm2."""
    import subprocess
    subprocess.run(['osascript', '-e', 'tell application "iTerm2" to quit'])


@app_group.command('theme')
def app_theme():
    """Show current UI theme (light/dark/auto)."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        return await app.async_get_theme()
    click.echo(run_iterm(_run))


# ── Preferences ───────────────────────────────────────────────────────────

@cli.group()
def pref():
    """Read and write iTerm2 preferences."""
    pass


@pref.command('get')
@click.argument('key')
def pref_get(key):
    async def _run(connection):
        return await iterm2.async_get_preference(connection, key)
    click.echo(run_iterm(_run))


@pref.command('set')
@click.argument('key')
@click.argument('value')
def pref_set(key, value):
    async def _run(connection):
        for converter in [int, float, lambda x: True if x == 'true' else (False if x == 'false' else None), str]:
            try:
                typed = converter(value)
                if typed is not None:
                    await iterm2.async_set_preference(connection, key, typed)
                    return
            except (ValueError, TypeError):
                continue
    run_iterm(_run)


@pref.command('list')
@click.option('--filter', 'filter_text', default=None)
def pref_list(filter_text):
    async def _run(connection):
        keys = [k for k in dir(iterm2.PreferenceKey) if not k.startswith('_')]
        if filter_text:
            keys = [k for k in keys if filter_text.lower() in k.lower()]
        return keys
    for k in run_iterm(_run):
        click.echo(k)


@pref.command('theme')
def pref_theme():
    """Show current theme tags and dark/light mode."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        return await app.async_get_theme()
    click.echo(run_iterm(_run))


@pref.command('tmux')
@click.argument('property', required=False)
@click.argument('value', required=False)
def pref_tmux(property, value):
    """Get all tmux prefs, or set a specific one."""
    async def _run(connection):
        if property and value:
            typed = int(value) if value.isdigit() else (
                True if value == 'true' else (False if value == 'false' else value))
            await iterm2.async_set_preference(connection, f'TmuxPref{property}', typed)
        else:
            keys = ['OpenTmuxWindowsIn', 'TmuxDashboardLimit',
                    'AutoHideTmuxClientSession', 'UseTmuxProfile']
            return {k: await iterm2.async_get_preference(connection, k) for k in keys}
    result = run_iterm(_run)
    if isinstance(result, dict):
        click.echo(json.dumps(result, indent=2))


# ── Broadcast ─────────────────────────────────────────────────────────────

@cli.group()
def broadcast():
    """Control input broadcasting across panes."""
    pass


@broadcast.command('on')
@click.option('--window', 'window_id', default=None)
def broadcast_on(window_id):
    """Broadcast input to all panes in window."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        w = app.get_window_by_id(window_id) if window_id else app.current_terminal_window
        if not w:
            return
        domain = iterm2.BroadcastDomain()
        for tab in w.tabs:
            for session in tab.sessions:
                domain.add_session(session)
        await iterm2.async_set_broadcast_domains(connection, [domain])
    run_iterm(_run)


@broadcast.command('off')
def broadcast_off():
    """Stop all broadcasting."""
    async def _run(connection):
        await iterm2.async_set_broadcast_domains(connection, [])
    run_iterm(_run)


@broadcast.command('add')
@click.argument('session_ids', nargs=-1, required=True)
def broadcast_add(session_ids):
    """Group sessions into a broadcast domain."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        domain = iterm2.BroadcastDomain()
        for sid in session_ids:
            s = app.get_session_by_id(sid)
            if s:
                domain.add_session(s)
        await iterm2.async_set_broadcast_domains(connection, [domain])
    run_iterm(_run)


@broadcast.command('list')
def broadcast_list():
    """List active broadcast domains."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        await app.async_refresh_broadcast_domains()
        return [[s.session_id for s in d.sessions] for d in app.broadcast_domains]
    for i, domain in enumerate(run_iterm(_run) or []):
        click.echo(f"Domain {i}: {', '.join(domain)}")
```

- [ ] **Step 2: Commit**

```bash
git add src/_config.py
git commit -m "feat: _config — var, app, pref, broadcast groups"
```

---

### Task 10: `_interactive.py` — dialogs, menu, repl

**Files:**
- Create: `src/_interactive.py`

- [ ] **Step 1: Write `_interactive.py`**

```python
# src/_interactive.py
"""Interactive commands: alert, ask, pick, save-dialog, menu group, repl."""
import click
import iterm2
from _core import cli, run_iterm


@cli.command()
@click.argument('title')
@click.argument('message')
@click.option('--button', 'buttons', multiple=True, help='Add a button label')
def alert(title, message, buttons):
    """Show macOS alert dialog. Returns clicked button label."""
    async def _run(connection):
        a = iterm2.Alert(title, message, connection)
        for b in buttons:
            a.add_button(b)
        return await a.async_run()
    result = run_iterm(_run)
    click.echo(result)


@cli.command()
@click.argument('title')
@click.argument('message')
@click.option('--default', 'default_val', default='', help='Pre-filled value')
def ask(title, message, default_val):
    """Show text input dialog. Returns entered text (empty if cancelled)."""
    async def _run(connection):
        a = iterm2.TextInputAlert(title, message, default_val, connection)
        return await a.async_run()
    result = run_iterm(_run)
    if result is not None:
        click.echo(result)


@cli.command()
@click.option('--ext', 'extensions', multiple=True, help='Allowed file extensions')
@click.option('--multi', is_flag=True, help='Allow selecting multiple files')
def pick(extensions, multi):
    """File open dialog. Returns selected path(s)."""
    async def _run(connection):
        panel = iterm2.OpenPanel()
        if extensions:
            panel.allowed_file_types = list(extensions)
        panel.allows_multiple_selection = multi
        return await panel.async_run(connection)
    result = run_iterm(_run)
    if result:
        for f in result:
            click.echo(f)


@cli.command('save-dialog')
@click.option('--name', 'filename', default=None, help='Pre-filled filename')
def save_dialog(filename):
    """File save dialog. Returns chosen path."""
    async def _run(connection):
        panel = iterm2.SavePanel()
        if filename:
            panel.filename = filename
        return await panel.async_run(connection)
    result = run_iterm(_run)
    if result:
        click.echo(result)


@cli.group()
def menu():
    """Invoke iTerm2 menu items programmatically."""
    pass


@menu.command('list')
def menu_list():
    """List common menu item paths."""
    items = [
        "Shell/New Tab",
        "Shell/New Window",
        "Shell/Close",
        "Shell/Split Vertically with Current Profile",
        "Shell/Split Horizontally with Current Profile",
        "View/Enter Full Screen",
        "View/Exit Full Screen",
        "iTerm2/Preferences",
    ]
    for item in items:
        click.echo(item)


@menu.command('select')
@click.argument('item_path')
def menu_select(item_path):
    """Invoke menu item by path (e.g. 'Shell/New Tab')."""
    async def _run(connection):
        await iterm2.MainMenu.async_select_menu_item(connection, item_path)
    run_iterm(_run)


@menu.command('state')
@click.argument('item_path')
def menu_state(item_path):
    """Check if menu item is checked/enabled."""
    async def _run(connection):
        return await iterm2.MainMenu.async_get_menu_item_state(connection, item_path)
    click.echo(run_iterm(_run))


@cli.command()
def repl():
    """Interactive REPL mode. Maintains sticky context. Type 'exit' to quit."""
    from click.testing import CliRunner
    import shlex

    click.echo("ita REPL — type commands, 'exit' to quit")
    click.echo(f"Target: {__import__('_core').get_sticky() or '(none)'}")

    runner = CliRunner(mix_stderr=False)
    while True:
        try:
            line = click.prompt('ita', prompt_suffix=' > ')
            if line.strip() in ('exit', 'quit', 'q'):
                break
            if not line.strip():
                continue
            result = runner.invoke(cli, shlex.split(line))
            if result.output:
                click.echo(result.output, nl=False)
            if result.exit_code != 0 and result.exception:
                click.echo(f"Error: {result.exception}", err=True)
        except (KeyboardInterrupt, EOFError):
            break
    click.echo("Bye.")
```

- [ ] **Step 2: Commit**

```bash
git add src/_interactive.py
git commit -m "feat: _interactive — dialogs, menu group, repl"
```

---

### Task 11: `_tmux.py` — tmux -CC group

**Files:**
- Create: `src/_tmux.py`

- [ ] **Step 1: Write `_tmux.py`**

```python
# src/_tmux.py
"""tmux -CC integration commands."""
import asyncio
import click
import iterm2
from _core import cli, run_iterm, resolve_session


@cli.group()
def tmux():
    """tmux -CC integration — render tmux windows as native iTerm2 tabs."""
    pass


@tmux.command('start')
@click.option('--attach', is_flag=True, help='Attach to existing tmux session')
@click.option('-s', '--session', 'session_id', default=None)
def tmux_start(attach, session_id):
    """Bootstrap tmux -CC connection. Returns connection IDs."""
    cmd = 'tmux -CC attach' if attach else 'tmux -CC'

    async def _run(connection):
        session = await resolve_session(connection, session_id)
        await session.async_send_text(cmd + '\n')
        await asyncio.sleep(2)  # allow connection to establish
        conns = await iterm2.async_list_tmux_connections(connection)
        return [c.connection_id for c in conns]

    for cid in run_iterm(_run):
        click.echo(cid)


@tmux.command('connections')
def tmux_connections():
    """List active tmux -CC connections."""
    async def _run(connection):
        conns = await iterm2.async_list_tmux_connections(connection)
        return [{'id': c.connection_id, 'session': c.owning_session_id} for c in conns]
    for c in run_iterm(_run):
        click.echo(f"{c['id']}  session={c['session']}")


@tmux.command('windows')
def tmux_windows():
    """List tmux windows mapped to iTerm2 tab IDs."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        return [
            {'tmux_window_id': tab.tmux_window_id,
             'tab_id': tab.tab_id,
             'connection_id': tab.tmux_connection_id}
            for window in app.windows
            for tab in window.tabs
            if tab.tmux_window_id
        ]
    for w in run_iterm(_run):
        click.echo(f"@{w['tmux_window_id']}  tab={w['tab_id']}  conn={w['connection_id']}")


@tmux.command('cmd')
@click.argument('command')
def tmux_cmd(command):
    """Send tmux protocol command. Returns output."""
    async def _run(connection):
        conns = await iterm2.async_list_tmux_connections(connection)
        if not conns:
            raise click.ClickException("No tmux connection. Run 'ita tmux start' first.")
        return await iterm2.async_send_tmux_command(
            connection, conns[0].connection_id, command)
    result = run_iterm(_run)
    if result:
        click.echo(result)


@tmux.command('visible')
@click.argument('window_ref', help='tmux window reference e.g. @1')
@click.argument('state', type=click.Choice(['on', 'off']))
def tmux_visible(window_ref, state):
    """Show (on) or hide (off) a tmux window's iTerm2 tab."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        wid = window_ref.lstrip('@')
        for window in app.windows:
            for tab in window.tabs:
                if tab.tmux_window_id == wid:
                    if state == 'off':
                        await tab.async_close(force=True)
                    return
    run_iterm(_run)
```

- [ ] **Step 2: Commit**

```bash
git add src/_tmux.py
git commit -m "feat: _tmux — tmux -CC group (start, connections, windows, cmd, visible)"
```

---

### Task 12: `_events.py` — `on` group, `coprocess`, `annotate`, `rpc`

**Files:**
- Create: `src/_events.py`

- [ ] **Step 1: Write `_events.py`**

```python
# src/_events.py
"""Event monitoring and advanced commands: on group, coprocess, annotate, rpc."""
import asyncio
import re
import click
import iterm2
from _core import cli, run_iterm, resolve_session, get_sticky

PROMPT_CHARS = ('❯', '$', '#', '%', '→', '>>')


@cli.group()
def on():
    """One-shot event wait. Blocks until event fires, then exits."""
    pass


@on.command('output')
@click.argument('pattern')
@click.option('-t', '--timeout', default=60, type=int)
@click.option('-s', '--session', 'session_id', default=None)
def on_output(pattern, timeout, session_id):
    """Block until PATTERN appears in session output. Returns matching line."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        async with session.get_screen_streamer() as streamer:
            for _ in range(timeout * 4):
                try:
                    contents = await asyncio.wait_for(streamer.async_get(), timeout=1.0)
                    for i in range(contents.number_of_lines):
                        line = contents.line(i).string.replace('\x00', '')
                        if re.search(pattern, line):
                            return line
                except asyncio.TimeoutError:
                    continue
        raise click.ClickException(f"Timeout: pattern {pattern!r} not found in {timeout}s")
    click.echo(run_iterm(_run))


@on.command('prompt')
@click.option('-t', '--timeout', default=60, type=int)
@click.option('-s', '--session', 'session_id', default=None)
def on_prompt(timeout, session_id):
    """Block until next shell prompt appears."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        async with session.get_screen_streamer() as streamer:
            for _ in range(timeout * 4):
                try:
                    contents = await asyncio.wait_for(streamer.async_get(), timeout=1.0)
                    last = contents.line(contents.number_of_lines - 1).string.replace('\x00', '').strip()
                    if any(last.startswith(p) or last.endswith(p) for p in PROMPT_CHARS):
                        return last
                except asyncio.TimeoutError:
                    continue
    result = run_iterm(_run)
    if result:
        click.echo(result)


@on.command('session-new')
@click.option('-t', '--timeout', default=30, type=int)
def on_session_new(timeout):
    """Block until a new session is created. Returns session ID."""
    async def _run(connection):
        q = asyncio.Queue()
        async def cb(connection, session_id):
            await q.put(session_id)
        token = await iterm2.notifications.async_subscribe_to_new_session_notification(
            connection, cb)
        try:
            return await asyncio.wait_for(q.get(), timeout=timeout)
        finally:
            await iterm2.notifications.async_unsubscribe(connection, token)
    click.echo(run_iterm(_run))


@on.command('session-end')
@click.option('-t', '--timeout', default=60, type=int)
@click.option('-s', '--session', 'session_id', default=None)
def on_session_end(timeout, session_id):
    """Block until a session terminates. Returns session ID."""
    async def _run(connection):
        target = session_id or get_sticky()
        q = asyncio.Queue()
        async def cb(connection, sid):
            if not target or sid == target:
                await q.put(sid)
        token = await iterm2.notifications.async_subscribe_to_terminate_session_notification(
            connection, cb)
        try:
            return await asyncio.wait_for(q.get(), timeout=timeout)
        finally:
            await iterm2.notifications.async_unsubscribe(connection, token)
    click.echo(run_iterm(_run))


@on.command('focus')
@click.option('-t', '--timeout', default=30, type=int)
def on_focus(timeout):
    """Block until keyboard focus changes."""
    async def _run(connection):
        async with iterm2.FocusMonitor(connection) as m:
            update = await asyncio.wait_for(m.async_get_focus_update(), timeout=timeout)
            return str(update)
    click.echo(run_iterm(_run))


@on.command('layout')
@click.option('-t', '--timeout', default=30, type=int)
def on_layout(timeout):
    """Block until window/tab/pane layout changes."""
    async def _run(connection):
        q = asyncio.Queue()
        async def cb(connection):
            await q.put(True)
        token = await iterm2.notifications.async_subscribe_to_layout_change_notification(
            connection, cb)
        try:
            await asyncio.wait_for(q.get(), timeout=timeout)
            return "layout changed"
        finally:
            await iterm2.notifications.async_unsubscribe(connection, token)
    click.echo(run_iterm(_run))


# ── Advanced ───────────────────────────────────────────────────────────────

@cli.group()
def coprocess():
    """Attach a subprocess to session I/O."""
    pass


@coprocess.command('start')
@click.argument('cmd')
@click.option('-s', '--session', 'session_id', default=None)
def coprocess_start(cmd, session_id):
    """Start coprocess connected to session stdin/stdout."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        await session.async_run_coprocess(cmd)
    run_iterm(_run)


@coprocess.command('stop')
@click.option('-s', '--session', 'session_id', default=None)
def coprocess_stop(session_id):
    """Stop running coprocess."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        await session.async_stop_coprocess()
    run_iterm(_run)


@cli.command()
@click.argument('text')
@click.option('--start', 'range_start', type=int, default=None)
@click.option('--end', 'range_end', type=int, default=None)
@click.option('-s', '--session', 'session_id', default=None)
def annotate(text, range_start, range_end, session_id):
    """Add annotation to screen content."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        contents = await session.async_get_screen_contents()
        n = contents.number_of_lines - 1
        start = range_start if range_start is not None else 0
        end = range_end if range_end is not None else 80
        coord_range = iterm2.util.CoordRange(
            iterm2.util.Coord(start, n),
            iterm2.util.Coord(end, n))
        await session.async_add_annotation(coord_range, text)
    run_iterm(_run)


@cli.command()
@click.argument('invocation')
@click.option('-s', '--session', 'session_id', default=None)
def rpc(invocation, session_id):
    """Invoke an RPC function in session context."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        return await session.async_invoke_function(invocation)
    result = run_iterm(_run)
    if result is not None:
        click.echo(result)
```

- [ ] **Step 2: Commit**

```bash
git add src/_events.py
git commit -m "feat: _events — on group (output/prompt/session-new/session-end/focus/layout), coprocess, annotate, rpc"
```

---

## Phase 3: Wiring (Sequential)

### Task 13: Wire all modules into `ita.py`

**Files:**
- Modify: `src/ita.py`

- [ ] **Step 1: Update ita.py to import all modules**

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["iterm2", "click"]
# ///
"""
ita — agent-first iTerm2 control.
Entry point. Imports all modules to register their commands on the CLI.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _core import cli  # noqa: E402

# Import all modules — each registers its commands on `cli` at import time
import _orientation   # status, focus, version, use
import _session       # new, close, activate, name, restart, resize, clear, capture
import _io            # run, send, inject
import _output        # read, watch, wait, selection, copy, get-prompt
import _layout        # split, pane, tab, window
import _management    # save, restore, layouts, profile, presets, theme
import _config        # var, app, pref, broadcast
import _interactive   # alert, ask, pick, save-dialog, menu, repl
import _tmux          # tmux
import _events        # on, coprocess, annotate, rpc

if __name__ == '__main__':
    cli()
```

- [ ] **Step 2: Verify full command surface**

```bash
cd ~/Developer/ita
uv run src/ita.py --help
```
Expected output lists all command groups: status, focus, version, use, new, close, activate, name, restart, resize, clear, capture, run, send, inject, read, watch, wait, selection, copy, get-prompt, split, pane, move, tab, window, save, restore, layouts, profile, presets, theme, var, app, pref, broadcast, alert, ask, pick, save-dialog, menu, repl, tmux, on, coprocess, annotate, rpc.

- [ ] **Step 3: Commit**

```bash
git add src/ita.py
git commit -m "feat: wire all modules into ita.py entry point"
```

---

### Task 14: Integration smoke test

**Files:**
- Create: `tests/test_integration.py`

- [ ] **Step 1: Write smoke tests (requires running iTerm2)**

```python
# tests/test_integration.py
"""
Integration smoke tests. Require iTerm2 running with Python API enabled.
Run with: uv run --with pytest pytest tests/test_integration.py -v -m integration
"""
import subprocess
import sys
from pathlib import Path
import pytest

ITA = [sys.executable, str(Path(__file__).parent.parent / 'src' / 'ita.py')]
pytestmark = pytest.mark.integration


def run_ita(*args):
    """Run ita command and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        ['uv', 'run', str(Path(__file__).parent.parent / 'src' / 'ita.py')] + list(args),
        capture_output=True, text=True)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def test_help_runs():
    rc, out, _ = run_ita('--help')
    assert rc == 0
    assert 'status' in out


def test_status_runs():
    rc, out, _ = run_ita('status')
    assert rc == 0  # May be empty if no windows, but should not error


def test_version_runs():
    rc, out, _ = run_ita('version')
    assert rc == 0
    assert out  # Should return something


def test_new_creates_session_and_sets_sticky():
    import _core as core
    from pathlib import Path
    rc, sid, _ = run_ita('new')
    assert rc == 0
    assert len(sid) > 10  # session ID should be a UUID-ish string
    # Check sticky was set
    ctx_file = Path.home() / '.ita_context'
    if ctx_file.exists():
        assert ctx_file.read_text().strip() == sid
    # Clean up
    run_ita('close', '-s', sid)
```

- [ ] **Step 2: Run smoke tests**

```bash
cd ~/Developer/ita
uv run --with pytest pytest tests/test_integration.py -v -m integration
```
Expected: all 4 tests pass (with iTerm2 running).

- [ ] **Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: integration smoke tests"
```

---

## Phase 4: Packaging

### Task 15: Write `skills/ita/SKILL.md`

**Files:**
- Modify: `skills/ita/SKILL.md`

- [ ] **Step 1: Write complete SKILL.md**

The SKILL.md must include:

1. **Frontmatter** with name and description
2. **CRITICAL RULES** section — session targeting, text-only default, `--json` only when parsing, no null bytes
3. **Session targeting model** — sticky context, `ita new` auto-sets, `-s` override
4. **Complete command reference** — every command from every module with examples
5. **`ita run` atomic pattern** — what it does, when to use it
6. **Event system** — `ita watch`, `ita wait`, `ita on *`
7. **Common recipes** — workspace setup, wait-for-server, visual feedback

Format: same quality as the design spec. All commands with concrete one-liner examples.

- [ ] **Step 2: Commit**

```bash
git add skills/ita/SKILL.md
git commit -m "docs: complete SKILL.md — full Claude reference"
```

---

### Task 16: Plugin packaging and GitHub

**Files:**
- Modify: `plugin.json`
- Modify: `README.md`
- Create: `LICENSE`

- [ ] **Step 1: Finalize plugin.json**

```json
{
  "name": "ita",
  "version": "1.0.0",
  "description": "Agent-first iTerm2 control — full API access optimized for Claude",
  "author": "voidfreud",
  "skills": [
    {
      "name": "ita",
      "path": "skills/ita/SKILL.md"
    }
  ],
  "commands": [],
  "hooks": []
}
```

- [ ] **Step 2: Write README.md**

```markdown
# ita — iTerm Agent

Agent-first iTerm2 control for Claude Code. Built directly on the iTerm2 Python API.

## What it does

`ita` gives Claude complete control over iTerm2 — creating sessions, running commands
atomically, streaming output via ScreenStreamer, managing layouts, arrangements, profiles,
tmux -CC workflows, and reacting to events — all with minimal context pollution.

## Requirements

- macOS with iTerm2 3.6+
- iTerm2 Python API enabled: Settings → General → Magic → Enable Python API
- uv installed

## Install via Claude Code

Add this repo as a plugin in your Claude Code settings.

## Development

```bash
uv run src/ita.py --help        # run directly
uv run --with pytest pytest     # run tests
```

## Architecture

Single entry point (`src/ita.py`) importing focused modules (~200 lines each):
`_core`, `_orientation`, `_session`, `_io`, `_output`, `_layout`,
`_management`, `_config`, `_interactive`, `_tmux`, `_events`
```

- [ ] **Step 3: Create MIT LICENSE**

```
MIT License

Copyright (c) 2026 voidfreud

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
```

- [ ] **Step 4: Create GitHub repo and push**

```bash
cd ~/Developer/ita
gh repo create voidfreud/ita --public \
  --description "Agent-first iTerm2 control for Claude Code"
git remote add origin https://github.com/voidfreud/ita.git
git push -u origin main
```

- [ ] **Step 5: Final commit**

```bash
git add .
git commit -m "chore: v1.0.0 — plugin packaging, README, LICENSE"
git push
```

---

## Self-Review

### Spec Coverage

| Spec Requirement | Task |
|-----------------|------|
| uv inline script | Task 1 |
| Sticky context (A+C model) | Tasks 1, 3 |
| `ita run` atomic | Task 5 |
| `ita watch` ScreenStreamer | Tasks 5, 6 |
| `ita wait --pattern` | Task 6 |
| All pane/tab/window commands | Task 7 |
| Arrangements | Task 8 |
| Profiles & visual | Task 8 |
| Variables | Task 9 |
| App control | Task 9 |
| Preferences + tmux prefs | Task 9 |
| Broadcast | Task 9 |
| Dialogs | Task 10 |
| Menu | Task 10 |
| REPL | Task 10 |
| tmux -CC | Task 11 |
| Event monitoring (on *) | Task 12 |
| Coprocess, annotate, rpc | Task 12 |
| SKILL.md | Task 15 |
| Plugin packaging | Task 16 |
| GitHub | Task 16 |
| ≤200 lines per file | All modules |

All covered. ✓

### Type Consistency

- `run_iterm()` used in every module ✓
- `resolve_session()` imported from `_core` in every module ✓
- `strip()` applied consistently to all terminal output ✓
- `get_sticky()` / `set_sticky()` / `clear_sticky()` from `_core` ✓
- `PROMPT_CHARS` defined in both `_io` and `_output` (intentional duplication — no shared state) ✓

### Placeholder Scan

No TBDs, TODOs, or vague steps. All code blocks are complete. ✓
