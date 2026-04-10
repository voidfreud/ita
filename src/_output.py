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
