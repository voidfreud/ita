# src/_filter.py
"""Filter-expression parsing for the `--where KEY=VALUE` option family.

Used by `ita status`, `ita overview`, and any command that filters over a
record set. Single source of truth for the operator grammar.
"""
import click


def parse_filter(expr: str) -> tuple[str, str, str]:
	"""Parse a --where expression into (key, op, value).

	Operators (longest-first so ~=/!= don't get swallowed by =):
	  KEY~=VALUE  → starts-with
	  KEY!=VALUE  → not-equal
	  KEY=VALUE   → exact match

	Raises ClickException for invalid format.
	"""
	for op in ('~=', '!=', '='):
		if op in expr:
			key, value = expr.split(op, 1)
			key = key.strip()
			if not key:
				break
			return key, op, value.strip()
	raise click.ClickException(
		f"Invalid filter format: {expr!r}. Use KEY=VALUE, KEY~=PREFIX, or KEY!=VALUE."
	)


def match_filter(record: dict, key: str, op: str, value: str) -> bool:
	"""Test whether a record (dict of session properties) matches a parsed filter."""
	field = str(record.get(key, '')).strip()
	value = value.strip()
	if op == '=':
		return field == value
	if op == '!=':
		return field != value
	if op == '~=':
		return field.startswith(value)
	return False
