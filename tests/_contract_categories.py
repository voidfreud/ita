"""Category map for CONTRACT §14 parametrized matrix.

Each ita command (space-separated path as emitted by `ita commands --json`)
maps to a list of categories. A command may hold more than one (e.g. `run`
is a mutator that can also stream with `--json-stream`).

Categories drive which §14 invariants apply:

    mutator    changes iTerm2 state; rules 1, 2, 3, 4, 5 apply
    readonly   reads only; rules 1, 2, 3, 5 (if it takes a target) apply
    streaming  live output (watch/stream/wait/run-stream); rules 1, 2, 6 apply
    meta       never talks to iTerm2 (--help, --version, commands); rules 1, 2

Rule 6 (readiness) is *deferred* to the integration lane per task #8.

Maintainers: when a new ita command lands, add it here. The parametrized
matrix in ``tests/test_contract_matrix.py`` consumes this dict directly,
so anything missing will surface as a test failure (see
``test_categorization_covers_surface``).
"""
from __future__ import annotations

# fmt: off
CATEGORIES: dict[str, list[str]] = {
	# ----- top-level orientation / mutators -----
	"activate":          ["mutator"],
	"alert":             ["mutator"],           # shows GUI dialog
	"annotate":          ["mutator"],
	"ask":               ["mutator"],
	"capture":           ["readonly"],
	"clear":             ["mutator"],
	"close":             ["mutator"],
	"commands":          ["meta", "readonly"],
	"copy":              ["mutator"],
	"doctor":            ["readonly"],
	"focus":             ["readonly"],
	"get-prompt":        ["readonly"],
	"inject":            ["mutator"],
	"key":               ["mutator"],
	"lock":              ["mutator"],
	"move":              ["mutator"],
	"name":              ["mutator"],
	"new":               ["mutator"],
	"overview":          ["readonly"],
	"pane":              ["mutator"],
	"pick":              ["mutator"],            # GUI dialog
	"protect":           ["mutator"],
	"read":              ["readonly"],
	"repl":              ["meta"],               # interactive; exempt per §16
	"resize":            ["mutator"],
	"restart":           ["mutator"],
	"restore":           ["mutator"],
	"rpc":               ["mutator"],
	"run":               ["mutator", "streaming"],
	"save":              ["mutator"],
	"save-dialog":       ["mutator"],
	"selection":         ["readonly"],
	"send":              ["mutator"],
	"split":             ["mutator"],
	"stabilize":         ["mutator"],
	"status":            ["readonly"],
	"swap":              ["mutator"],
	"theme":             ["readonly"],
	"unlock":            ["mutator"],
	"unprotect":         ["mutator"],
	"version":           ["meta"],
	"wait":              ["readonly", "streaming"],
	"watch":             ["readonly", "streaming"],

	# ----- app -----
	"app activate":      ["mutator"],
	"app hide":          ["mutator"],
	"app quit":          ["mutator"],
	"app theme":         ["readonly"],
	"app version":       ["readonly"],

	# ----- broadcast -----
	"broadcast add":     ["mutator"],
	"broadcast list":    ["readonly"],
	"broadcast off":     ["mutator"],
	"broadcast on":      ["mutator"],
	"broadcast send":    ["mutator"],
	"broadcast set":     ["mutator"],

	# ----- coprocess -----
	"coprocess list":    ["readonly"],
	"coprocess start":   ["mutator"],
	"coprocess stop":    ["mutator"],

	# ----- layouts (flattened as `layouts list`) -----
	"layouts list":      ["readonly"],

	# ----- menu -----
	"menu list":         ["readonly"],
	"menu select":       ["mutator"],
	"menu state":        ["readonly"],

	# ----- on (event subscriptions — streaming readonly) -----
	"on focus":          ["readonly", "streaming"],
	"on keystroke":      ["readonly", "streaming"],
	"on layout":         ["readonly", "streaming"],
	"on output":         ["readonly", "streaming"],
	"on prompt":         ["readonly", "streaming"],
	"on session-end":    ["readonly", "streaming"],
	"on session-new":    ["readonly", "streaming"],

	# ----- pref -----
	"pref get":          ["readonly"],
	"pref list":         ["readonly"],
	"pref set":          ["mutator"],
	"pref theme":        ["readonly"],
	"pref tmux":         ["readonly"],
	"presets":           ["readonly"],

	# ----- profile -----
	"profile apply":     ["mutator"],
	"profile get":       ["readonly"],
	"profile list":      ["readonly"],
	"profile set":       ["mutator"],
	"profile show":      ["readonly"],

	# ----- session -----
	"session info":      ["readonly"],

	# ----- tab -----
	"tab activate":      ["mutator"],
	"tab close":         ["mutator"],
	"tab detach":        ["mutator"],
	"tab goto":          ["mutator"],
	"tab info":          ["readonly"],
	"tab list":          ["readonly"],
	"tab move":          ["mutator"],
	"tab new":           ["mutator"],
	"tab next":          ["mutator"],
	"tab prev":          ["mutator"],
	"tab profile":       ["mutator"],
	"tab title":         ["mutator"],

	# ----- tmux -----
	"tmux cmd":          ["mutator"],
	"tmux connections":  ["readonly"],
	"tmux detach":       ["mutator"],
	"tmux kill-session": ["mutator"],
	"tmux start":        ["mutator"],
	"tmux stop":         ["mutator"],
	"tmux visible":      ["readonly"],
	"tmux windows":      ["readonly"],

	# ----- var -----
	"var get":           ["readonly"],
	"var list":          ["readonly"],
	"var set":           ["mutator"],

	# ----- window -----
	"window activate":   ["mutator"],
	"window close":      ["mutator"],
	"window frame":      ["mutator"],
	"window fullscreen": ["mutator"],
	"window list":       ["readonly"],
	"window new":        ["mutator"],
	"window title":      ["mutator"],
}
# fmt: on


# Commands that take a target session/tab/window (subject to rule 5: identity).
# Conservative: include everything that can resolve a target via -s / --target / positional.
TARGET_TAKERS: frozenset[str] = frozenset({
	"activate", "annotate", "capture", "clear", "close", "copy", "get-prompt",
	"inject", "key", "name", "protect", "read", "resize", "restart", "restore",
	"selection", "send", "split", "stabilize", "swap", "unprotect",
	"run", "wait", "watch",
	"coprocess start", "coprocess stop",
	"session info",
	"profile apply", "profile get", "profile set", "profile show",
	"tab activate", "tab close", "tab detach", "tab goto", "tab info",
	"tab move", "tab profile", "tab title",
	"var get", "var set",
	"window activate", "window close", "window frame", "window fullscreen",
	"window title",
	"on output", "on prompt", "on keystroke",
})


# Commands that accept caller-supplied filesystem paths (rule 4: path-trust).
PATH_TAKERS: frozenset[str] = frozenset({
	"run",           # --stdin <path>
	"save",          # output path
	"capture",       # output path
	"restore",       # input path
})


# Helpers ---------------------------------------------------------------------

def commands_with(category: str) -> list[str]:
	"""All command names whose category list contains *category*."""
	return sorted(n for n, cats in CATEGORIES.items() if category in cats)


def category_counts() -> dict[str, int]:
	out: dict[str, int] = {}
	for cats in CATEGORIES.values():
		for c in cats:
			out[c] = out.get(c, 0) + 1
	return out
