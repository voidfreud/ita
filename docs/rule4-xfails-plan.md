# Rule-4 xfails mini-wave plan (issue #362)

28 target-taking mutators are marked xfail by
`tests/test_contract_matrix.py::test_rule4_mutator_honors_protection`
because they don't call `check_protected` on their resolved target. This
plan groups them by source file so future agents can each take one group
without colliding, and ranks the file-disjoint groups for parallel
dispatch.

Source of truth for the list: `_RULE4_WIRED` (currently ~5 entries) vs
`RULE4_TARGETED_MUTATORS = sorted(set(MUTATORS) & TARGET_TAKERS)` in
`tests/test_contract_matrix.py`. Mapping below was derived by AST/name
search across `src/ita/*.py`.

## Per-mutator analysis

| Command            | Source file                  | Blast  | Notes                                                            |
|--------------------|------------------------------|--------|------------------------------------------------------------------|
| activate           | src/ita/_session.py          | medium | focus change; visible state mutation, no data movement           |
| name               | src/ita/_session.py          | medium | rename session                                                   |
| resize             | src/ita/_session.py          | medium | rows/cols mutation; can clobber user layout but reversible       |
| split              | src/ita/_pane.py             | high   | adds a child pane to a protected target — hard to undo cleanly   |
| swap               | src/ita/_pane.py             | high   | swaps pane positions; reorders user-visible layout               |
| tab-activate       | src/ita/_tab.py              | medium | focus change at tab level                                        |
| tab-close          | src/ita/_tab.py              | high   | destructive — closes a tab                                       |
| tab-detach         | src/ita/_tab.py              | high   | moves tab to a new window — moves data per spec                  |
| tab-goto           | src/ita/_tab.py              | medium | focus change                                                     |
| tab-move           | src/ita/_tab.py              | medium | reorder; visible mutation                                        |
| tab-profile        | src/ita/_tab.py              | medium | applies profile to all sessions in a tab                         |
| tab-title          | src/ita/_tab.py              | medium | rename tab                                                       |
| window-activate    | src/ita/_layout.py           | medium | focus change at window level                                     |
| window-close       | src/ita/_layout.py           | high   | destructive — closes a window                                    |
| window-frame       | src/ita/_layout.py           | medium | geometry change                                                  |
| window-fullscreen  | src/ita/_layout.py           | medium | toggles window state                                             |
| window-title       | src/ita/_layout.py           | medium | rename window                                                    |
| restore            | src/ita/_layouts.py          | high   | reapplies a saved layout — can rearrange protected targets       |
| profile-apply      | src/ita/_management.py       | medium | applies a named profile to a session                             |
| profile-set        | src/ita/_management.py       | medium | sets a single profile key on a session                           |
| protect            | src/ita/_orientation.py      | medium | flips protection on; meta-mutation but should still gate         |
| unprotect          | src/ita/_orientation.py      | high   | flips protection off — security-sensitive by definition          |
| stabilize          | src/ita/_readiness.py        | medium | waits and may nudge a target into ready state                    |
| copy               | src/ita/_query.py            | low    | copies selection to clipboard; a target-side read-with-effect    |
| annotate           | src/ita/_events.py           | low    | adds an annotation; cosmetic                                     |
| coprocess-start    | src/ita/_events.py           | medium | spawns a coprocess attached to the target session                |
| coprocess-stop     | src/ita/_events.py           | medium | tears down a coprocess                                           |
| var-set            | src/ita/_config.py           | low    | sets a user variable on a session                                |

Counts: 7 high, 17 medium, 4 low.

## Groupings by file (proposed sub-waves)

### Group A: src/ita/_tab.py
Mutators: tab-activate, tab-close, tab-detach, tab-goto, tab-move, tab-profile, tab-title
Blast: 2 high (tab-close, tab-detach), 5 medium
Largest single-file group; tab is the natural blast-radius boundary.

### Group B: src/ita/_layout.py
Mutators: window-activate, window-close, window-frame, window-fullscreen, window-title
Blast: 1 high (window-close), 4 medium

### Group C: src/ita/_session.py
Mutators: activate, name, resize
Blast: 0 high, 3 medium

### Group D: src/ita/_pane.py
Mutators: split, swap
Blast: 2 high, 0 medium

### Group E: src/ita/_orientation.py
Mutators: protect, unprotect
Blast: 1 high (unprotect), 1 medium
Special-case: these mutate the protection bit itself. `unprotect` MUST
require the lease/force gate; `protect` should still be gated for
auditability but is the safer of the pair.

### Group F: src/ita/_management.py
Mutators: profile-apply, profile-set
Blast: 0 high, 2 medium

### Group G: src/ita/_events.py — DEFERRED (do not dispatch yet)
Mutators: annotate, coprocess-start, coprocess-stop
Blast: 0 high, 2 medium, 1 low
File is currently being refactored by another agent. Hold this group
until the events refactor lands; otherwise merge conflicts are
guaranteed.

### Group H: src/ita/_layouts.py
Mutators: restore
Blast: 1 high

### Group I: src/ita/_readiness.py
Mutators: stabilize
Blast: 0 high, 1 medium

### Group J: src/ita/_query.py
Mutators: copy
Blast: 0 high, 0 medium, 1 low

### Group K: src/ita/_config.py
Mutators: var-set
Blast: 0 high, 0 medium, 1 low

### Agent prompt template (per group)
> For each command in this group: locate its Click command in the source
> file, resolve the target via the existing `resolve_session` /
> `resolve_tab` / `resolve_window` helper, then call `check_protected`
> on the resolved target BEFORE any iTerm2-side mutation (after
> resolution but before send). Add the command name to `_RULE4_WIRED` in
> `tests/test_contract_matrix.py`. Run
> `uv run --extra dev pytest tests/test_contract_matrix.py -q` and
> confirm the corresponding xfail flips to xpass→pass (the
> parametrization will fail loudly if `_RULE4_WIRED` lists a command
> that still doesn't call `check_protected`). One commit per group.
> HANDS OFF `_send.py` and `_events.py`.

## Parallelization plan

File-disjoint and safe to dispatch concurrently right now:
- A (_tab.py)
- B (_layout.py)
- C (_session.py)
- D (_pane.py)
- E (_orientation.py)
- F (_management.py)
- H (_layouts.py)
- I (_readiness.py)
- J (_query.py)
- K (_config.py)

All of these touch `tests/test_contract_matrix.py` (the `_RULE4_WIRED`
frozenset). That's the only shared file across groups, and it's an
append-only set literal — trivial three-way merge. If concurrency
anxiety is high, serialize the `_RULE4_WIRED` edit into a final
"collect" commit instead of per-group; the source-file edits are
genuinely disjoint.

Serialize / hold:
- G (_events.py) — blocked by ongoing events refactor; dispatch only
  after that lands.

## Priority recommendation

Top-3 to ship first by blast x frequency:

1. **Group E — unprotect / protect (`_orientation.py`)** — `unprotect`
   is the gate that turns the whole protection system off for a target.
   Until it itself respects `check_protected`, an attacker / runaway
   agent can disarm a session in one call. Highest security payoff for
   two commands in one tiny file.
2. **Group A — `_tab.py` (7 commands incl. tab-close, tab-detach)** —
   biggest single-file win. Tab-close and tab-detach are the most
   destructive everyday mutators and they share resolution helpers, so
   one agent fixes all seven with near-identical edits.
3. **Group D — split / swap (`_pane.py`)** — only two commands but both
   high-blast (geometry-altering, hard to undo on a protected pane), and
   the file is small and isolated. Cheap, high-value.

## Surprises

- Every one of the 28 commands maps to exactly one source file with no
  ambiguity — clean grouping, no cross-file mutators.
- The only shared edit point across groups is the `_RULE4_WIRED`
  frozenset in the contract-matrix test; source-side edits are fully
  disjoint, so the parallelism story is unusually clean.
