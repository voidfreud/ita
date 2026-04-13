# src/_screen.py
"""Screen / output helpers: prompt detection, null-byte strip, line reading.

Single source of truth for `_is_prompt_line` (CONTRACT §9). Every command that
needs to decide "is this line a shell prompt?" calls this function, not its
own heuristic.
"""
import re

import iterm2

PROMPT_CHARS = ('❯', '$', '#', '%', '→', '>>')
_SENTINEL_RE = re.compile(r'^: ita-[0-9a-f]+;')


def _is_prompt_line(s: str) -> bool:
	"""True if s looks like a shell prompt line with no meaningful content
	(e.g. '~ ❯', '$', '% ', '~ ❯ :'). Catches both fully-rendered prompts and
	echo remnants where only the prompt + command-separator punctuation survived.
	"""
	t = s.strip()
	if not t:
		return False
	if t in PROMPT_CHARS:
		return True
	if any(t.startswith(p + ' ') for p in PROMPT_CHARS):
		return True
	if any(t.endswith(' ' + p) for p in PROMPT_CHARS):
		return True
	# Line contains a prompt char AND its non-prompt residue is only punctuation /
	# whitespace (e.g. '~ ❯ :' — echo row remnant with the `: ita-tag;` truncated).
	if any(p in t for p in PROMPT_CHARS):
		residue = t
		for p in PROMPT_CHARS:
			residue = residue.replace(p, '')
		if not residue.strip(' ~./:;'):
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
