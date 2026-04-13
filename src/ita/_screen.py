# src/_screen.py
"""Screen / output helpers: prompt detection, null-byte strip, line reading.

Single source of truth for `_is_prompt_line` (CONTRACT §9). Every command that
needs to decide "is this line a shell prompt?" calls this function, not its
own heuristic.
"""
import os
import re

import iterm2

# Default prompt chars (CONTRACT §9). User extensions via ITA_PROMPT_CHARS.
_DEFAULT_PROMPT_CHARS = ('$', '%', '#', '>', '❯', '›')


def _prompt_chars() -> tuple[str, ...]:
	"""Prompt characters in effect: defaults + ITA_PROMPT_CHARS extensions.

	ITA_PROMPT_CHARS is read per-call so tests / user env changes take effect
	without process restart. Empty / whitespace extensions are ignored."""
	extra = os.environ.get('ITA_PROMPT_CHARS', '') or ''
	# Extensions are a raw string — each codepoint is one prompt char.
	return _DEFAULT_PROMPT_CHARS + tuple(c for c in extra if not c.isspace())


# Legacy export kept for call sites that still import it (e.g. _send.py trim).
PROMPT_CHARS = _DEFAULT_PROMPT_CHARS
_SENTINEL_RE = re.compile(r'^: ita-[0-9a-f]+;')


def _is_prompt_line(s: str) -> bool:
	"""True iff s is a shell-prompt line with no content (CONTRACT §9, #327, #331).

	A prompt line is the shell's prompt rendering — a prompt character either
	alone or preceded by user/host/cwd decoration separated by whitespace
	(e.g. `$`, `~ ❯`, `user@host %`). Content that happens to end in a prompt
	char glued to non-whitespace (e.g. `price: 5%`, `regex: ^foo$`) is
	CONTENT, not a prompt — stripping it would erase real data (#331). Echo
	remnants like `$ ls` also have non-whitespace after the prompt char and
	are rejected (#327).

	Rules:
	- Strip NUL, strip trailing whitespace.
	- Empty → False.
	- Stripped string equals a prompt char → True (e.g. `$`).
	- Stripped string ends with `<whitespace><prompt_char>` → True
	  (e.g. `~ ❯`, `user@host:/ %`).
	- Otherwise → False (content, echo remnants, regular output).
	"""
	t = s.replace('\x00', '').rstrip()
	if not t:
		return False
	for p in _prompt_chars():
		if t == p:
			return True
		# prompt char preceded by whitespace = shell prompt decoration.
		if t.endswith(p) and len(t) > len(p) and t[-len(p) - 1].isspace():
			return True
	return False


def strip(text: str) -> str:
	"""Remove null bytes from terminal output."""
	return text.replace('\x00', '')


def last_non_empty_index(contents) -> int:
	"""Last non-empty line index in a ScreenContents, or -1 if blank.

	number_of_lines is grid height, not content height — the bottom rows are
	usually empty whitespace, so callers must scan backward to find content.
	"""
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
	Callers filter ita sentinel rows themselves.
	"""
	if not include_scrollback:
		contents = await session.async_get_screen_contents()
		result = [strip(contents.line(i).string) for i in range(contents.number_of_lines)]
	else:
		async with iterm2.Transaction(session.connection):
			info = await session.async_get_line_info()
			total = info.mutable_area_height + info.scrollback_buffer_height
			# first_line must be >= overflow; async_get_contents returns
			# however many lines are actually available. Clamp first to total
			# so small scrollback / fresh sessions can't yield a bad range.
			first = min(info.overflow, total)
			lines = await session.async_get_contents(first, total)
		result = [strip(line.string) for line in lines]
	while result and not result[-1].strip():
		result.pop()
	return result
