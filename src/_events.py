# src/_events.py
"""Event monitoring and advanced commands: on group, coprocess, annotate, rpc."""
import asyncio
import re
import click
import iterm2
from _core import cli, run_iterm, resolve_session, get_sticky, strip, PROMPT_CHARS, last_non_empty_index


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
                    last_idx = last_non_empty_index(contents)
                    if last_idx < 0:
                        continue
                    last = strip(contents.line(last_idx).string).strip()
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
        n = last_non_empty_index(contents)
        if n < 0:
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
