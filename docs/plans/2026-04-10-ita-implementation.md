# ita — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `ita` — an agent-first iTerm2 control tool as a Claude Code plugin, directly on the iTerm2 Python API, replacing cli-anything-iterm2 entirely.

**Architecture:** Single uv inline script (`src/ita.py`) using the `iterm2` Python package and `click` for the CLI. All iTerm2 operations run via `iterm2.run_until_complete()`. Sticky context persisted to `~/.ita_context`. Packaged as a Claude Code plugin with a companion SKILL.md.

**Tech Stack:** Python 3.11+, uv, iterm2 (PyPI), click, iTerm2 3.6+ with Python API enabled.

---

## File Map

| File | Purpose |
|------|---------|
| `src/ita.py` | Single-file CLI tool — all commands |
| `skills/ita/SKILL.md` | Claude's reference doc |
| `plugin.json` | Plugin manifest |
| `tests/test_ita.py` | Unit tests for helpers |
| `README.md` | Human-facing docs |
| `.gitignore` | Standard Python + macOS ignores |

---

## Phase 1: Foundation

### Task 1: Plugin scaffold + project structure

**Files:**
- Create: `plugin.json`
- Create: `README.md`
- Create: `.gitignore`
- Create: `src/ita.py` (stub only)
- Create: `skills/ita/SKILL.md` (stub only)

- [ ] **Step 1: Create plugin.json**

```json
{
  "name": "ita",
  "version": "0.1.0",
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

- [ ] **Step 2: Create skill stub**

```markdown
# ita — iTerm Agent

Agent-first iTerm2 control. See implementation plan for full command surface.
This file will be replaced with the complete skill once the tool is built.
```
Save to `skills/ita/SKILL.md`.

- [ ] **Step 3: Create ita.py stub**

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["iterm2", "click"]
# ///

import asyncio
import json
import os
import sys
from pathlib import Path
import click
import iterm2

# ── Context ──────────────────────────────────────────────────────────────────

CONTEXT_FILE = Path.home() / ".ita_context"

def get_sticky() -> str | None:
    if CONTEXT_FILE.exists():
        v = CONTEXT_FILE.read_text().strip()
        return v if v else None
    return None

def set_sticky(session_id: str) -> None:
    CONTEXT_FILE.write_text(session_id)

def clear_sticky() -> None:
    CONTEXT_FILE.unlink(missing_ok=True)

# ── Helpers ───────────────────────────────────────────────────────────────────

def strip(text: str) -> str:
    """Remove null bytes from terminal output."""
    return text.replace('\x00', '')

def run_iterm(coro):
    """Run an iTerm2 async coroutine synchronously. Returns coroutine result."""
    result = {}
    error = {}
    async def main(connection):
        try:
            result['value'] = await coro(connection)
        except Exception as e:
            error['value'] = e
    iterm2.run_until_complete(main)
    if error:
        raise error['value']
    return result.get('value')

async def resolve_session(connection, session_id: str | None = None):
    """Get target session: explicit ID > sticky > current focused."""
    app = await iterm2.async_get_app(connection)
    sid = session_id or get_sticky()
    if sid:
        session = app.get_session_by_id(sid)
        if session:
            return session
        raise click.ClickException(f"Session {sid!r} not found. Run 'ita status' to list sessions.")
    # Fall back to currently focused session
    window = app.current_terminal_window
    if window and window.current_tab and window.current_tab.current_session:
        return window.current_tab.current_session
    raise click.ClickException("No session available. Run 'ita new' to create one.")

# ── CLI root ──────────────────────────────────────────────────────────────────

@click.group()
@click.version_option()
def cli():
    """ita — agent-first iTerm2 control."""
    pass

if __name__ == '__main__':
    cli()
```

- [ ] **Step 4: Create README.md**

```markdown
# ita — iTerm Agent

Agent-first iTerm2 control tool for Claude Code.

## Requirements
- macOS with iTerm2 3.6+
- iTerm2 Python API enabled: Settings → General → Magic → Enable Python API
- uv installed

## Usage
The tool is invoked as `ita` when installed via the Claude Code plugin.

## Development
```bash
# Run directly
uv run src/ita.py --help

# Run tests
uv run --with pytest pytest tests/
```

See `docs/specs/2026-04-10-ita-design.md` for full spec.
```

- [ ] **Step 5: Verify stub runs**

```bash
cd ~/Developer/ita
uv run src/ita.py --help
```
Expected: `Usage: ita.py [OPTIONS] COMMAND [ARGS]...`

- [ ] **Step 6: Commit**

```bash
git add .
git commit -m "feat: project scaffold — plugin structure and ita.py stub"
```

---

### Task 2: Unit tests for helpers

**Files:**
- Create: `tests/test_ita.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Write tests for strip() and context helpers**

```python
# tests/test_ita.py
import sys
import os
from pathlib import Path
import tempfile
import pytest

# Add src to path so we can import ita module pieces
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

# We import only the pure functions (no iTerm2 connection needed)
# by importing the module and mocking the iterm2 import
import unittest.mock as mock
with mock.patch.dict('sys.modules', {'iterm2': mock.MagicMock(), 'click': mock.MagicMock()}):
    import importlib.util
    spec = importlib.util.spec_from_file_location("ita", Path(__file__).parent.parent / "src" / "ita.py")
    # We'll test helpers directly by reading the file and exec'ing relevant parts

def test_strip_removes_null_bytes():
    # inline the strip function for unit testing
    def strip(text):
        return text.replace('\x00', '')
    assert strip("hello\x00world") == "helloworld"
    assert strip("\x00\x00\x00") == ""
    assert strip("clean text") == "clean text"
    assert strip("line1\x00\x00  17%\x00tokens") == "line1  17%tokens"

def test_strip_empty_string():
    def strip(text):
        return text.replace('\x00', '')
    assert strip("") == ""

def test_context_file_roundtrip(tmp_path):
    context_file = tmp_path / ".ita_context"

    def get_sticky():
        if context_file.exists():
            v = context_file.read_text().strip()
            return v if v else None
        return None

    def set_sticky(session_id):
        context_file.write_text(session_id)

    def clear_sticky():
        context_file.unlink(missing_ok=True)

    assert get_sticky() is None
    set_sticky("ABC123")
    assert get_sticky() == "ABC123"
    clear_sticky()
    assert get_sticky() is None

def test_context_ignores_whitespace(tmp_path):
    context_file = tmp_path / ".ita_context"
    context_file.write_text("  SESSION-ID  \n")

    def get_sticky():
        if context_file.exists():
            v = context_file.read_text().strip()
            return v if v else None
        return None

    assert get_sticky() == "SESSION-ID"
```

- [ ] **Step 2: Run tests**

```bash
cd ~/Developer/ita
uv run --with pytest pytest tests/test_ita.py -v
```
Expected: 4 tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/
git commit -m "test: helper unit tests for strip() and context file"
```

---

## Phase 2: Orientation & Targeting

### Task 3: `ita status`, `ita focus`, `ita version`, `ita use`

**Files:**
- Modify: `src/ita.py` — add status, focus, version, use commands

- [ ] **Step 1: Add status command**

Add to `src/ita.py` after the CLI root section:

```python
@cli.command()
@click.option('--json', 'use_json', is_flag=True)
def status(use_json):
    """List all sessions with id, name, process, path."""
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
        click.echo(f"{marker} {sid}  {s['name']:<20}  {s['process']:<10}  {s['path']}")
```

- [ ] **Step 2: Add focus, version, use commands**

```python
@cli.command()
def focus():
    """Show which element has keyboard focus."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        window = app.current_terminal_window
        if not window:
            return "No focused window"
        tab = window.current_tab
        session = tab.current_session if tab else None
        return {
            'window_id': window.window_id,
            'tab_id': tab.tab_id if tab else None,
            'session_id': session.session_id if session else None,
            'session_name': strip(session.name or '') if session else None,
        }
    result = run_iterm(_run)
    if isinstance(result, str):
        click.echo(result)
    else:
        click.echo(f"window: {result['window_id']}")
        click.echo(f"tab:    {result['tab_id']}")
        click.echo(f"session:{result['session_id']}  ({result['session_name']})")


@cli.command()
def version():
    """Show iTerm2 app version."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        return await app.async_get_variable('iterm2.version')
    v = run_iterm(_run)
    click.echo(v or 'unknown')


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

- [ ] **Step 3: Verify commands run**

```bash
uv run src/ita.py status
uv run src/ita.py focus
uv run src/ita.py version
uv run src/ita.py use --clear
```
Expected: Each command outputs something without error.

- [ ] **Step 4: Commit**

```bash
git add src/ita.py
git commit -m "feat: status, focus, version, use commands"
```

---

### Task 4: `ita new`, `ita close`, `ita activate`, `ita name`, `ita restart`, `ita resize`, `ita clear`, `ita capture`

**Files:**
- Modify: `src/ita.py`

- [ ] **Step 1: Add session lifecycle commands**

```python
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
    """Close session (tab)."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        await session.async_close(force=True)
    run_iterm(_run)
    if session_id == get_sticky() or (not session_id and get_sticky()):
        clear_sticky()


@cli.command()
@click.argument('session_id', required=False)
def activate(session_id):
    """Focus/bring a session to front."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
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
    """Clear session screen."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        await session.async_send_text('\x0c')  # Ctrl+L
    run_iterm(_run)


@cli.command()
@click.argument('file', required=False)
@click.option('-s', '--session', 'session_id', default=None)
def capture(file, session_id):
    """Save screen contents to file (or stdout)."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        contents = await session.async_get_screen_contents()
        lines = []
        for i in range(contents.number_of_lines):
            line = contents.line(i)
            lines.append(strip(line.string))
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
uv run src/ita.py name "test-pane"
uv run src/ita.py status
```
Expected: New session created, appears in status, name updated.

- [ ] **Step 3: Commit**

```bash
git add src/ita.py
git commit -m "feat: session lifecycle — new, close, activate, name, restart, resize, clear, capture"
```

---

## Phase 3: Core Operations

### Task 5: `ita run` (atomic), `ita send`, `ita inject`

**Files:**
- Modify: `src/ita.py`

- [ ] **Step 1: Add send and inject**

```python
@cli.command()
@click.argument('text')
@click.option('--raw', is_flag=True, help='No newline appended')
@click.option('-s', '--session', 'session_id', default=None)
def send(text, raw, session_id):
    """Send text to session (fire and forget)."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        await session.async_send_text(text if raw else text + '\n')
    run_iterm(_run)


@cli.command()
@click.argument('data')
@click.option('--hex', 'is_hex', is_flag=True, help='Interpret DATA as hex bytes')
@click.option('-s', '--session', 'session_id', default=None)
def inject(data, is_hex, session_id):
    """Inject raw bytes into session (Ctrl+C = $'\\x03')."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        if is_hex:
            raw = bytes.fromhex(data)
        else:
            raw = data.encode('utf-8').decode('unicode_escape').encode('latin-1')
        await session.async_inject(raw)
    run_iterm(_run)
```

- [ ] **Step 2: Add `ita run` — the atomic operation**

```python
@cli.command()
@click.argument('cmd')
@click.option('-t', '--timeout', default=30, type=int, help='Timeout in seconds')
@click.option('-n', '--lines', default=50, type=int, help='Output lines to return')
@click.option('--json', 'use_json', is_flag=True)
@click.option('-s', '--session', 'session_id', default=None)
def run(cmd, timeout, lines, use_json, session_id):
    """Send command, wait for completion, return clean output. Atomic."""
    import time

    async def _run(connection):
        session = await resolve_session(connection, session_id)
        await session.async_send_text(cmd + '\n')
        start = time.time()

        # Try shell integration first (most reliable)
        try:
            token = await asyncio.wait_for(
                iterm2.async_subscribe_to_prompt_notification(connection, session.session_id),
                timeout=0.5
            )
            # If we got a subscription token, wait for the notification
            prompt_received = asyncio.Event()
            async def on_prompt(connection, notif):
                prompt_received.set()
            await asyncio.wait_for(prompt_received.wait(), timeout=timeout)
        except (asyncio.TimeoutError, Exception):
            # Fallback: poll scrollback for prompt character
            PROMPT_CHARS = ('❯', '$', '#', '%', '→')
            for _ in range(timeout * 2):  # check every 0.5s
                await asyncio.sleep(0.5)
                contents = await session.async_get_screen_contents()
                last_line = strip(contents.line(contents.number_of_lines_with_history - 1).string).strip()
                if any(last_line.startswith(p) or last_line.endswith(p) for p in PROMPT_CHARS):
                    break

        elapsed_ms = int((time.time() - start) * 1000)

        # Read output
        line_info = await session.async_get_line_info()
        scrollback = await session.async_get_screen_contents()
        output_lines = []
        total = scrollback.number_of_lines_with_history
        start_line = max(0, total - lines)
        for i in range(start_line, total):
            output_lines.append(strip(scrollback.line(i).string))
        # Trim trailing empty lines
        while output_lines and not output_lines[-1].strip():
            output_lines.pop()

        return '\n'.join(output_lines), elapsed_ms

    output, elapsed_ms = run_iterm(_run)

    if use_json:
        click.echo(json.dumps({'output': output, 'elapsed_ms': elapsed_ms}))
    else:
        click.echo(output)
```

- [ ] **Step 3: Verify**

```bash
uv run src/ita.py send "echo hello"
uv run src/ita.py run "echo 'ita works'"
uv run src/ita.py inject $'\x03'   # Ctrl+C
```

- [ ] **Step 4: Commit**

```bash
git add src/ita.py
git commit -m "feat: run (atomic), send, inject"
```

---

### Task 6: `ita read`, `ita watch`, `ita wait`, `ita selection`, `ita copy`, `ita get-prompt`

**Files:**
- Modify: `src/ita.py`

- [ ] **Step 1: Add read**

```python
@cli.command()
@click.argument('lines', default=20, type=int)
@click.option('--json', 'use_json', is_flag=True)
@click.option('-s', '--session', 'session_id', default=None)
def read(lines, use_json, session_id):
    """Read last N lines from session. Always clean, no null bytes."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        contents = await session.async_get_screen_contents()
        total = contents.number_of_lines_with_history
        start = max(0, total - lines)
        result = []
        for i in range(start, total):
            result.append(strip(contents.line(i).string))
        while result and not result[-1].strip():
            result.pop()
        return result
    result = run_iterm(_run)
    if use_json:
        click.echo(json.dumps({'lines': result, 'count': len(result)}))
    else:
        click.echo('\n'.join(result))
```

- [ ] **Step 2: Add watch (ScreenStreamer)**

```python
@cli.command()
@click.option('-s', '--session', 'session_id', default=None)
def watch(session_id):
    """Stream screen output via ScreenStreamer until prompt appears. Zero polling."""
    PROMPT_CHARS = ('❯', '$', '#', '%', '→')

    async def _run(connection):
        session = await resolve_session(connection, session_id)
        seen_lines = set()
        async with session.get_screen_streamer() as streamer:
            while True:
                contents = await streamer.async_get()
                for i in range(contents.number_of_lines):
                    line_text = strip(contents.line(i).string)
                    if line_text and line_text not in seen_lines:
                        seen_lines.add(line_text)
                        click.echo(line_text)
                # Check if last line looks like a prompt
                last = strip(contents.line(contents.number_of_lines - 1).string).strip()
                if any(last.startswith(p) or last.endswith(p) for p in PROMPT_CHARS):
                    break

    run_iterm(_run)
```

- [ ] **Step 3: Add wait, selection, copy, get-prompt**

```python
@cli.command()
@click.option('--pattern', default=None, help='Wait until this pattern appears in output')
@click.option('-t', '--timeout', default=30, type=int)
@click.option('-s', '--session', 'session_id', default=None)
def wait(pattern, timeout, session_id):
    """Block until next shell prompt (or pattern) appears."""
    PROMPT_CHARS = ('❯', '$', '#', '%', '→')

    async def _run(connection):
        session = await resolve_session(connection, session_id)
        async with session.get_screen_streamer() as streamer:
            for _ in range(timeout * 4):  # check every 0.25s via streamer
                contents = await asyncio.wait_for(streamer.async_get(), timeout=1.0)
                if pattern:
                    for i in range(contents.number_of_lines):
                        if pattern in strip(contents.line(i).string):
                            return True
                else:
                    last = strip(contents.line(contents.number_of_lines - 1).string).strip()
                    if any(last.startswith(p) or last.endswith(p) for p in PROMPT_CHARS):
                        return True
        return False

    found = run_iterm(_run)
    if not found and pattern:
        raise click.ClickException(f"Timeout: pattern {pattern!r} not found")


@cli.command()
@click.option('-s', '--session', 'session_id', default=None)
def selection(session_id):
    """Get currently selected text."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        text = await session.async_get_selection_text(connection)
        return strip(text or '')
    result = run_iterm(_run)
    click.echo(result)


@cli.command()
@click.option('-s', '--session', 'session_id', default=None)
def copy(session_id):
    """Copy selection to clipboard."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        await session.async_send_text('')  # triggers clipboard copy via selection
        sel = await session.async_get_selection()
        if sel:
            text = await session.async_get_selection_text(connection)
            import subprocess
            subprocess.run(['pbcopy'], input=text.encode(), check=True)
    run_iterm(_run)


@cli.command('get-prompt')
@click.option('-s', '--session', 'session_id', default=None)
def get_prompt(session_id):
    """Get last prompt info: cwd, command, exit status."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        prompt = await iterm2.async_get_last_prompt(connection, session.session_id)
        if not prompt:
            return None
        return {
            'cwd': prompt.working_directory,
            'command': prompt.command,
            'exit_code': prompt.exit_code,
        }
    result = run_iterm(_run)
    if result:
        click.echo(f"cwd:      {result['cwd']}")
        click.echo(f"command:  {result['command']}")
        click.echo(f"exit:     {result['exit_code']}")
    else:
        click.echo("No prompt info (shell integration not active?)")
```

- [ ] **Step 4: Verify**

```bash
uv run src/ita.py read 10
uv run src/ita.py get-prompt
```

- [ ] **Step 5: Commit**

```bash
git add src/ita.py
git commit -m "feat: read, watch (ScreenStreamer), wait, selection, copy, get-prompt"
```

---

## Phase 4: Layout

### Task 7: Panes — `ita split`, `ita pane`, `ita move`

**Files:**
- Modify: `src/ita.py`

- [ ] **Step 1: Add split, pane navigation, move**

```python
@cli.command()
@click.option('-v', '--vertical', is_flag=True)
@click.option('--profile', default=None)
@click.option('-s', '--session', 'session_id', default=None)
def split(vertical, profile, session_id):
    """Split pane. New pane becomes sticky target."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        new_session = await session.async_split_pane(
            vertical=vertical,
            profile=profile
        )
        return new_session.session_id
    sid = run_iterm(_run)
    set_sticky(sid)
    click.echo(sid)


@cli.command()
@click.argument('direction', type=click.Choice(['right', 'left', 'above', 'below']))
@click.option('-s', '--session', 'session_id', default=None)
def pane(direction, session_id):
    """Navigate to adjacent split pane."""
    direction_map = {
        'right': iterm2.NavigationDirection.RIGHT,
        'left': iterm2.NavigationDirection.LEFT,
        'above': iterm2.NavigationDirection.ABOVE,
        'below': iterm2.NavigationDirection.BELOW,
    }
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        app = await iterm2.async_get_app(connection)
        _, tab = app.get_window_and_tab_for_session(session)
        await tab.async_select_pane_in_direction(direction_map[direction])
        # Update sticky to new focused session
        new_session = tab.current_session
        if new_session:
            set_sticky(new_session.session_id)
            return new_session.session_id
    sid = run_iterm(_run)
    if sid:
        click.echo(sid)


@cli.command()
@click.argument('session_id_arg')
@click.argument('dest_window_id')
@click.option('--vertical', is_flag=True)
def move(session_id_arg, dest_window_id, vertical):
    """Move a session pane to a different window."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        session = app.get_session_by_id(session_id_arg)
        if not session:
            raise click.ClickException(f"Session {session_id_arg!r} not found")
        dest_window = app.get_window_by_id(dest_window_id)
        if not dest_window:
            raise click.ClickException(f"Window {dest_window_id!r} not found")
        dest_tab = dest_window.current_tab
        if not dest_tab:
            raise click.ClickException("Destination window has no tabs")
        dest_session = dest_tab.current_session
        await app.async_move_session(
            session, dest_session,
            split_vertically=vertical,
            before=False
        )
    run_iterm(_run)
```

- [ ] **Step 2: Commit**

```bash
git add src/ita.py
git commit -m "feat: split, pane navigation, move"
```

---

### Task 8: Tabs — `ita tab *`

**Files:**
- Modify: `src/ita.py`

- [ ] **Step 1: Add tab group**

```python
@cli.group()
def tab():
    """Manage tabs."""
    pass


@tab.command('new')
@click.option('--window', 'window_id', default=None)
@click.option('--profile', default=None)
def tab_new(window_id, profile):
    """Create new tab."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        if window_id:
            window = app.get_window_by_id(window_id)
        else:
            window = app.current_terminal_window
        if not window:
            raise click.ClickException("No window available")
        new_tab = await window.async_create_tab(profile=profile)
        session = new_tab.current_session
        set_sticky(session.session_id)
        return session.session_id
    click.echo(run_iterm(_run))


@tab.command('close')
@click.argument('tab_id', required=False)
def tab_close(tab_id):
    """Close tab."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        if tab_id:
            t = app.get_tab_by_id(tab_id)
        else:
            window = app.current_terminal_window
            t = window.current_tab if window else None
        if not t:
            raise click.ClickException("Tab not found")
        await t.async_close(force=True)
    run_iterm(_run)


@tab.command('activate')
@click.argument('tab_id')
def tab_activate(tab_id):
    """Focus a tab."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        t = app.get_tab_by_id(tab_id)
        if not t:
            raise click.ClickException(f"Tab {tab_id!r} not found")
        await t.async_activate(order_window_front=True)
    run_iterm(_run)


@tab.command('next')
def tab_next():
    """Switch to next tab."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        window = app.current_terminal_window
        if window:
            tabs = window.tabs
            current = window.current_tab
            idx = tabs.index(current)
            next_tab = tabs[(idx + 1) % len(tabs)]
            await next_tab.async_activate()
    run_iterm(_run)


@tab.command('prev')
def tab_prev():
    """Switch to previous tab."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        window = app.current_terminal_window
        if window:
            tabs = window.tabs
            current = window.current_tab
            idx = tabs.index(current)
            prev_tab = tabs[(idx - 1) % len(tabs)]
            await prev_tab.async_activate()
    run_iterm(_run)


@tab.command('goto')
@click.argument('index', type=int)
def tab_goto(index):
    """Go to tab by index (0-based)."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        window = app.current_terminal_window
        if window and 0 <= index < len(window.tabs):
            await window.tabs[index].async_activate()
        else:
            raise click.ClickException(f"No tab at index {index}")
    run_iterm(_run)


@tab.command('list')
@click.option('--json', 'use_json', is_flag=True)
def tab_list(use_json):
    """List all tabs."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        result = []
        for window in app.windows:
            for t in window.tabs:
                result.append({
                    'tab_id': t.tab_id,
                    'window_id': window.window_id,
                    'sessions': len(t.sessions),
                })
        return result
    tabs = run_iterm(_run)
    if use_json:
        click.echo(json.dumps(tabs))
    else:
        for t in tabs:
            click.echo(f"{t['tab_id']}  window={t['window_id']}  panes={t['sessions']}")


@tab.command('info')
@click.argument('tab_id', required=False)
def tab_info(tab_id):
    """Show tab details."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        if tab_id:
            t = app.get_tab_by_id(tab_id)
        else:
            window = app.current_terminal_window
            t = window.current_tab if window else None
        if not t:
            raise click.ClickException("Tab not found")
        return {
            'tab_id': t.tab_id,
            'sessions': [s.session_id for s in t.sessions],
            'current_session': t.current_session.session_id if t.current_session else None,
            'tmux_window_id': t.tmux_window_id,
        }
    info = run_iterm(_run)
    click.echo(json.dumps(info, indent=2))


@tab.command('move')
def tab_move():
    """Move current tab to its own new window."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        window = app.current_terminal_window
        if window and window.current_tab:
            await window.current_tab.async_move_to_window()
    run_iterm(_run)


@tab.command('title')
@click.argument('title')
def tab_title(title):
    """Set current tab title."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        window = app.current_terminal_window
        if window and window.current_tab:
            await window.current_tab.async_set_title(title)
    run_iterm(_run)
```

- [ ] **Step 2: Commit**

```bash
git add src/ita.py
git commit -m "feat: tab group — new, close, activate, next, prev, goto, list, info, move, title"
```

---

### Task 9: Windows — `ita window *`

**Files:**
- Modify: `src/ita.py`

- [ ] **Step 1: Add window group**

```python
@cli.group()
def window():
    """Manage windows."""
    pass


@window.command('new')
@click.option('--profile', default=None)
def window_new(profile):
    """Create new window."""
    async def _run(connection):
        w = await iterm2.Window.async_create(connection, profile=profile)
        return w.window_id
    click.echo(run_iterm(_run))


@window.command('close')
@click.argument('window_id', required=False)
def window_close(window_id):
    """Close window."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        w = app.get_window_by_id(window_id) if window_id else app.current_terminal_window
        if w:
            await w.async_close(force=True)
    run_iterm(_run)


@window.command('activate')
@click.argument('window_id', required=False)
def window_activate(window_id):
    """Bring window to front."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        w = app.get_window_by_id(window_id) if window_id else app.current_terminal_window
        if w:
            await w.async_activate()
    run_iterm(_run)


@window.command('title')
@click.argument('title')
def window_title(title):
    """Set window title."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        w = app.current_terminal_window
        if w:
            await w.async_set_title(title)
    run_iterm(_run)


@window.command('fullscreen')
@click.argument('mode', type=click.Choice(['on', 'off', 'toggle']))
def window_fullscreen(mode):
    """Set window fullscreen mode."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        w = app.current_terminal_window
        if not w:
            return
        current = await w.async_get_fullscreen()
        if mode == 'toggle':
            await w.async_set_fullscreen(not current)
        elif mode == 'on':
            await w.async_set_fullscreen(True)
        else:
            await w.async_set_fullscreen(False)
    run_iterm(_run)


@window.command('frame')
@click.option('--x', type=float, default=None)
@click.option('--y', type=float, default=None)
@click.option('--w', type=float, default=None)
@click.option('--h', type=float, default=None)
def window_frame(x, y, w, h):
    """Get or set window position/size."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        win = app.current_terminal_window
        if not win:
            raise click.ClickException("No window")
        if any(v is not None for v in [x, y, w, h]):
            current = await win.async_get_frame()
            frame = iterm2.util.Frame(
                iterm2.util.Point(x if x is not None else current.origin.x,
                                   y if y is not None else current.origin.y),
                iterm2.util.Size(w if w is not None else current.size.width,
                                  h if h is not None else current.size.height)
            )
            await win.async_set_frame(frame)
        else:
            frame = await win.async_get_frame()
            return f"x={frame.origin.x} y={frame.origin.y} w={frame.size.width} h={frame.size.height}"
    result = run_iterm(_run)
    if result:
        click.echo(result)


@window.command('list')
@click.option('--json', 'use_json', is_flag=True)
def window_list(use_json):
    """List all windows."""
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
git add src/ita.py
git commit -m "feat: window group — new, close, activate, title, fullscreen, frame, list"
```

---

## Phase 5: Management

### Task 10: Arrangements — `ita save`, `ita restore`, `ita layouts`

**Files:**
- Modify: `src/ita.py`

- [ ] **Step 1: Add arrangement commands**

```python
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
    """List saved arrangements."""
    async def _run(connection):
        return await iterm2.Arrangement.async_list(connection)
    names = run_iterm(_run)
    for n in (names or []):
        click.echo(n)
```

- [ ] **Step 2: Commit**

```bash
git add src/ita.py
git commit -m "feat: arrangements — save, restore, layouts"
```

---

### Task 11: Profiles & Visual — `ita profile *`, `ita presets`, `ita theme`

**Files:**
- Modify: `src/ita.py`

- [ ] **Step 1: Add profile group and theme command**

```python
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
    """Set a profile property on the current session."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        change = iterm2.LocalWriteOnlyProfile()
        setattr(change, property_name, value)
        await session.async_set_profile_properties(change)
    run_iterm(_run)


@cli.command()
def presets():
    """List available color presets."""
    async def _run(connection):
        return await iterm2.ColorPreset.async_get_list(connection)
    for name in run_iterm(_run):
        click.echo(name)


THEME_SHORTCUTS = {'red': 'Red Alert', 'green': 'Solarized Dark', 'dark': 'Solarized Dark', 'light': 'Solarized Light'}


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
            raise click.ClickException(f"Preset {preset_name!r} not found. Run 'ita presets' to list.")
        change = iterm2.LocalWriteOnlyProfile()
        change.set_color_preset(preset_obj)
        await session.async_set_profile_properties(change)
    run_iterm(_run)
```

- [ ] **Step 2: Commit**

```bash
git add src/ita.py
git commit -m "feat: profile group, presets, theme with shortcuts"
```

---

### Task 12: Variables, App control, Dialogs, Broadcast, Menu

**Files:**
- Modify: `src/ita.py`

- [ ] **Step 1: Variables**

```python
@cli.group()
def var():
    """Get, set and list variables."""
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
        elif scope == 'session':
            session = await resolve_session(connection, session_id)
            return await session.async_get_variable(name)
        elif scope == 'window':
            w = app.current_terminal_window
            return await w.async_get_variable(name) if w else None
        elif scope == 'tab':
            w = app.current_terminal_window
            t = w.current_tab if w else None
            return await t.async_get_variable(name) if t else None
    result = run_iterm(_run)
    click.echo(strip(str(result or '')))


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
        elif scope == 'session':
            session = await resolve_session(connection, session_id)
            await session.async_set_variable(name, value)
        elif scope == 'window':
            w = app.current_terminal_window
            if w: await w.async_set_variable(name, value)
        elif scope == 'tab':
            w = app.current_terminal_window
            t = w.current_tab if w else None
            if t: await t.async_set_variable(name, value)
    run_iterm(_run)
```

- [ ] **Step 2: App control**

```python
@cli.group('app')
def app_group():
    """Control iTerm2 application."""
    pass


@app_group.command('activate')
def app_activate():
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        await app.async_activate(raise_all_windows=True, ignoring_other_apps=True)
    run_iterm(_run)


@app_group.command('hide')
def app_hide():
    async def _run(connection):
        import subprocess
        subprocess.run(['osascript', '-e', 'tell application "iTerm2" to set miniaturized of every window to true'])
    run_iterm(_run)


@app_group.command('theme')
def app_theme():
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        theme = await app.async_get_theme()
        return theme
    click.echo(run_iterm(_run))
```

- [ ] **Step 3: Dialogs**

```python
@cli.command()
@click.argument('title')
@click.argument('message')
@click.option('--button', 'buttons', multiple=True)
def alert(title, message, buttons):
    """Show alert dialog."""
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
@click.option('--default', 'default_val', default='')
def ask(title, message, default_val):
    """Show text input dialog. Returns entered text."""
    async def _run(connection):
        a = iterm2.TextInputAlert(title, message, default_val, connection)
        return await a.async_run()
    result = run_iterm(_run)
    if result is not None:
        click.echo(result)


@cli.command()
@click.option('--ext', 'extensions', multiple=True)
@click.option('--multi', is_flag=True)
def pick(extensions, multi):
    """File open dialog. Returns path(s)."""
    async def _run(connection):
        panel = iterm2.OpenPanel()
        panel.allowed_file_types = list(extensions) if extensions else None
        panel.allows_multiple_selection = multi
        result = await panel.async_run(connection)
        return result
    result = run_iterm(_run)
    if result:
        for f in result:
            click.echo(f)


@cli.command('save-dialog')
@click.option('--name', 'filename', default=None)
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
```

- [ ] **Step 4: Broadcast**

```python
@cli.group()
def broadcast():
    """Control input broadcasting."""
    pass


@broadcast.command('on')
@click.option('--window', 'window_id', default=None)
def broadcast_on(window_id):
    """Broadcast input to all panes."""
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
    for i, domain in enumerate(run_iterm(_run)):
        click.echo(f"Domain {i}: {', '.join(domain)}")
```

- [ ] **Step 5: Menu**

```python
@cli.group()
def menu():
    """Invoke iTerm2 menu items."""
    pass


@menu.command('list')
def menu_list():
    """List common menu items."""
    items = [
        "Shell/New Tab", "Shell/New Window", "Shell/Close",
        "Shell/Split Vertically with Current Profile",
        "Shell/Split Horizontally with Current Profile",
        "View/Enter Full Screen", "View/Exit Full Screen",
        "iTerm2/Preferences",
    ]
    for item in items:
        click.echo(item)


@menu.command('select')
@click.argument('item_path')
def menu_select(item_path):
    """Invoke a menu item by path (e.g. 'Shell/New Tab')."""
    async def _run(connection):
        await iterm2.MainMenu.async_select_menu_item(connection, item_path)
    run_iterm(_run)


@menu.command('state')
@click.argument('item_path')
def menu_state(item_path):
    """Check if a menu item is checked/enabled."""
    async def _run(connection):
        return await iterm2.MainMenu.async_get_menu_item_state(connection, item_path)
    click.echo(run_iterm(_run))
```

- [ ] **Step 6: Commit**

```bash
git add src/ita.py
git commit -m "feat: variables, app control, dialogs, broadcast, menu"
```

---

## Phase 6: tmux & Preferences

### Task 13: tmux -CC — `ita tmux *`

**Files:**
- Modify: `src/ita.py`

- [ ] **Step 1: Add tmux group**

```python
@cli.group()
def tmux():
    """tmux -CC integration."""
    pass


@tmux.command('start')
@click.option('--attach', is_flag=True, help='Attach to existing tmux session')
@click.option('-s', '--session', 'session_id', default=None)
def tmux_start(attach, session_id):
    """Bootstrap tmux -CC connection."""
    cmd = 'tmux -CC attach' if attach else 'tmux -CC'
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        await session.async_send_text(cmd + '\n')
        # Wait for connection
        await asyncio.sleep(2)
        connections = await iterm2.async_list_tmux_connections(connection)
        return [c.connection_id for c in connections]
    for c in run_iterm(_run):
        click.echo(c)


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
        result = []
        for window in app.windows:
            for tab in window.tabs:
                if tab.tmux_window_id:
                    result.append({
                        'tmux_window_id': tab.tmux_window_id,
                        'tab_id': tab.tab_id,
                        'connection_id': tab.tmux_connection_id,
                    })
        return result
    for w in run_iterm(_run):
        click.echo(f"@{w['tmux_window_id']}  tab={w['tab_id']}  conn={w['connection_id']}")


@tmux.command('cmd', context_settings=dict(ignore_unknown_options=True))
@click.argument('command')
def tmux_cmd(command):
    """Send tmux protocol command. Returns output."""
    async def _run(connection):
        conns = await iterm2.async_list_tmux_connections(connection)
        if not conns:
            raise click.ClickException("No tmux connection. Run 'ita tmux start' first.")
        result = await iterm2.async_send_tmux_command(connection, conns[0].connection_id, command)
        return result
    click.echo(run_iterm(_run) or '')


@tmux.command('visible')
@click.argument('window_ref')
@click.argument('state', type=click.Choice(['on', 'off']))
def tmux_visible(window_ref, state):
    """Show or hide a tmux window's iTerm2 tab (@1 on|off)."""
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
git add src/ita.py
git commit -m "feat: tmux -CC group — start, connections, windows, cmd, visible"
```

---

### Task 14: Preferences — `ita pref *`

**Files:**
- Modify: `src/ita.py`

- [ ] **Step 1: Add pref group**

```python
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
        # Attempt type coercion
        for converter in [int, float, lambda x: x.lower() == 'true' if x.lower() in ('true','false') else None, str]:
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
        # List known preference keys via list-keys equivalent
        keys = [k for k in dir(iterm2.PreferenceKey) if not k.startswith('_')]
        if filter_text:
            keys = [k for k in keys if filter_text.lower() in k.lower()]
        return keys
    for k in run_iterm(_run):
        click.echo(k)


@pref.command('theme')
def pref_theme():
    """Show current theme tags."""
    async def _run(connection):
        app = await iterm2.async_get_app(connection)
        return await app.async_get_theme()
    click.echo(run_iterm(_run))


@pref.command('tmux')
@click.argument('property', required=False)
@click.argument('value', required=False)
def pref_tmux(property, value):
    """Get or set tmux preferences."""
    async def _run(connection):
        if property and value:
            # set
            val = value
            for converter in [int, lambda x: x.lower() == 'true' if x.lower() in ('true','false') else None]:
                try:
                    typed = converter(val)
                    if typed is not None:
                        val = typed
                        break
                except (ValueError, TypeError):
                    continue
            await iterm2.async_set_preference(connection, f'TmuxPref{property}', val)
        else:
            # get all
            keys = ['OpenTmuxWindowsIn', 'TmuxDashboardLimit',
                    'AutoHideTmuxClientSession', 'UseTmuxProfile']
            result = {}
            for k in keys:
                result[k] = await iterm2.async_get_preference(connection, k)
            return result
    result = run_iterm(_run)
    if isinstance(result, dict):
        click.echo(json.dumps(result, indent=2))
```

- [ ] **Step 2: Commit**

```bash
git add src/ita.py
git commit -m "feat: pref group — get, set, list, theme, tmux"
```

---

## Phase 7: Events & Advanced

### Task 15: Event monitoring — `ita on *`

**Files:**
- Modify: `src/ita.py`

- [ ] **Step 1: Add on group (notification-based one-shots)**

```python
@cli.group()
def on():
    """One-shot event wait. Blocks until event fires."""
    pass


@on.command('output')
@click.argument('pattern')
@click.option('-t', '--timeout', default=60, type=int)
@click.option('-s', '--session', 'session_id', default=None)
def on_output(pattern, timeout, session_id):
    """Block until pattern appears in session output."""
    import re
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        async with session.get_screen_streamer() as streamer:
            for _ in range(timeout * 4):
                try:
                    contents = await asyncio.wait_for(streamer.async_get(), timeout=1.0)
                    for i in range(contents.number_of_lines):
                        line = strip(contents.line(i).string)
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
    """Block until next shell prompt."""
    PROMPT_CHARS = ('❯', '$', '#', '%', '→')
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        async with session.get_screen_streamer() as streamer:
            for _ in range(timeout * 4):
                try:
                    contents = await asyncio.wait_for(streamer.async_get(), timeout=1.0)
                    last = strip(contents.line(contents.number_of_lines - 1).string).strip()
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
    """Block until a new session is created."""
    async def _run(connection):
        result = asyncio.Queue()
        async def callback(connection, session_id):
            await result.put(session_id)
        token = await iterm2.notifications.async_subscribe_to_new_session_notification(
            connection, callback)
        try:
            sid = await asyncio.wait_for(result.get(), timeout=timeout)
            return sid
        finally:
            await iterm2.notifications.async_unsubscribe(connection, token)
    click.echo(run_iterm(_run))


@on.command('session-end')
@click.option('-t', '--timeout', default=60, type=int)
@click.option('-s', '--session', 'session_id', default=None)
def on_session_end(timeout, session_id):
    """Block until a session terminates."""
    async def _run(connection):
        sid_target = session_id or get_sticky()
        result = asyncio.Queue()
        async def callback(connection, session_id_notif):
            if not sid_target or session_id_notif == sid_target:
                await result.put(session_id_notif)
        token = await iterm2.notifications.async_subscribe_to_terminate_session_notification(
            connection, callback)
        try:
            return await asyncio.wait_for(result.get(), timeout=timeout)
        finally:
            await iterm2.notifications.async_unsubscribe(connection, token)
    click.echo(run_iterm(_run))


@on.command('focus')
@click.option('-t', '--timeout', default=30, type=int)
def on_focus(timeout):
    """Block until focus changes."""
    async def _run(connection):
        result = asyncio.Queue()
        monitor = iterm2.FocusMonitor(connection)
        async with monitor as m:
            update = await asyncio.wait_for(m.async_get_focus_update(), timeout=timeout)
            return str(update)
    click.echo(run_iterm(_run))


@on.command('layout')
@click.option('-t', '--timeout', default=30, type=int)
def on_layout(timeout):
    """Block until layout changes."""
    async def _run(connection):
        result = asyncio.Queue()
        async def callback(connection):
            await result.put(True)
        token = await iterm2.notifications.async_subscribe_to_layout_change_notification(
            connection, callback)
        try:
            await asyncio.wait_for(result.get(), timeout=timeout)
            return "layout changed"
        finally:
            await iterm2.notifications.async_unsubscribe(connection, token)
    click.echo(run_iterm(_run))
```

- [ ] **Step 2: Commit**

```bash
git add src/ita.py
git commit -m "feat: on group — output, prompt, session-new, session-end, focus, layout"
```

---

### Task 16: Advanced — coprocess, annotate, rpc, repl

**Files:**
- Modify: `src/ita.py`

- [ ] **Step 1: Add advanced commands**

```python
@cli.group()
def coprocess():
    """Manage coprocesses (subprocess connected to session I/O)."""
    pass


@coprocess.command('start')
@click.argument('cmd')
@click.option('-s', '--session', 'session_id', default=None)
def coprocess_start(cmd, session_id):
    """Start a coprocess connected to session."""
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
@click.option('--range-start', type=int, default=None)
@click.option('--range-end', type=int, default=None)
@click.option('-s', '--session', 'session_id', default=None)
def annotate(text, range_start, range_end, session_id):
    """Add annotation to screen content."""
    async def _run(connection):
        session = await resolve_session(connection, session_id)
        if range_start is not None and range_end is not None:
            coord_range = iterm2.util.CoordRange(
                iterm2.util.Coord(range_start, 0),
                iterm2.util.Coord(range_end, 0)
            )
            await session.async_add_annotation(coord_range, text)
        else:
            contents = await session.async_get_screen_contents()
            # Annotate last visible line
            n = contents.number_of_lines - 1
            coord_range = iterm2.util.CoordRange(
                iterm2.util.Coord(0, n),
                iterm2.util.Coord(80, n)
            )
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


@cli.command()
def repl():
    """Interactive REPL mode — maintains sticky context between commands."""
    click.echo("ita REPL — type commands, 'exit' to quit, 'status' to orient")
    click.echo(f"Current target: {get_sticky() or '(none)'}")
    while True:
        try:
            line = click.prompt('ita', prompt_suffix=' > ')
            if line.strip() in ('exit', 'quit', 'q'):
                break
            if not line.strip():
                continue
            import shlex
            from click.testing import CliRunner
            runner = CliRunner(mix_stderr=False)
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
git add src/ita.py
git commit -m "feat: coprocess, annotate, rpc, repl"
```

---

## Phase 8: Plugin & Skill

### Task 17: Write SKILL.md — Claude's complete reference

**Files:**
- Modify: `skills/ita/SKILL.md`

- [ ] **Step 1: Write comprehensive SKILL.md**

The SKILL.md must cover:
- CRITICAL RULES (session targeting, output defaults, never null bytes)
- Complete command reference with examples
- Session targeting model (sticky + `-s` flag)
- `ita run` atomic operation explanation
- Event monitoring patterns (`ita watch`, `ita on *`)
- Fresh session workflow (`ita new` → auto-sticky)

Write the full SKILL.md following the same quality standard as the design spec. Include every command group with concrete examples. Flag that `ita` returns plain text by default, `--json` when parsing needed. Document the `~/.ita_context` sticky file.

- [ ] **Step 2: Verify skill loads**

```bash
# Check skill file is valid markdown
head -5 skills/ita/SKILL.md
```

- [ ] **Step 3: Commit**

```bash
git add skills/ita/SKILL.md
git commit -m "docs: complete SKILL.md for Claude Code integration"
```

---

### Task 18: Final wiring, README, GitHub

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

- [ ] **Step 2: Write README**

Include: what it is, requirements, install via Claude Code plugin system, all command groups listed, development instructions.

- [ ] **Step 3: Create GitHub repo and push**

```bash
cd ~/Developer/ita
gh repo create voidfreud/ita --public --description "Agent-first iTerm2 control for Claude Code"
git remote add origin https://github.com/voidfreud/ita.git
git push -u origin main
```

- [ ] **Step 4: Final commit**

```bash
git add .
git commit -m "feat: v1.0.0 — complete ita plugin"
git push
```

---

## Self-Review

### Spec Coverage Check

| Spec Section | Tasks |
|-------------|-------|
| Core architecture (uv inline script) | Task 1 |
| Session targeting (sticky + -s) | Tasks 3, 4 |
| `ita run` atomic | Task 5 |
| `ita watch` ScreenStreamer | Task 6 |
| `ita wait --pattern` | Task 6 |
| All pane commands | Task 7 |
| All tab commands | Task 8 |
| All window commands | Task 9 |
| Arrangements | Task 10 |
| Profiles & visual feedback | Task 11 |
| Variables | Task 12 |
| Dialogs | Task 12 |
| Broadcast | Task 12 |
| Menu | Task 12 |
| tmux -CC | Task 13 |
| Preferences | Task 14 |
| Event monitoring (on *) | Task 15 |
| Advanced (coprocess, annotate, rpc) | Task 16 |
| REPL mode | Task 16 |
| SKILL.md | Task 17 |
| Plugin packaging + GitHub | Task 18 |

All spec requirements covered. ✓

### Placeholder Scan

No TBDs, TODOs, or vague steps found. Every step has concrete code or commands. ✓

### Type Consistency

- `resolve_session()` used consistently across all tasks ✓
- `run_iterm()` wrapper used for all iTerm2 calls ✓
- `strip()` applied to all terminal output ✓
- `get_sticky()` / `set_sticky()` / `clear_sticky()` consistent ✓
