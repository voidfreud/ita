# Bug-bash wave 1 plan

Scoping plan for 15 standalone bugs. Output of wave-1 scoping pass; intended as
dispatch input for future per-module agents. No code changes here.

## Per-bug analysis

| #    | Severity         | Size | Primary file(s)          | Summary (1 line) |
|------|------------------|------|--------------------------|------------------|
| #228 | cosmetic         | XS   | `src/ita/_lock.py`       | `unlock --quiet` leaks non-success output; error/stale-lock paths use bare `click.echo`. |
| #231 | behaviour-wrong  | XS   | `src/ita/_query.py`      | `wait` text mode rc=0 on both match and timeout; no way to disambiguate without `--json`. |
| #233 | behaviour-wrong  | XS   | `src/ita/_tmux.py`       | `tmux stop` returns rc=0 on no-connection; contract question — should be rc!=0. |
| #234 | behaviour-wrong  | XS   | `src/ita/_send.py`       | `_has_shell_integration` fail-open on exception; hides real failures, `exit_code` silently null. |
| #247 | behaviour-wrong  | XS   | `src/ita/_events.py`     | `on prompt` timeout silently exits 0; coroutine falls off without raising. |
| #249 | behaviour-wrong  | S    | `src/ita/_config.py`     | `broadcast on` reports success but `broadcast list` shows empty — state not persisted. |
| #287 | behaviour-wrong  | XS   | `src/ita/_config.py`     | `var list` degrades silently when session scope unresolvable; needs rc!=0 + structured error. |
| #316 | behaviour-wrong  | S    | `src/ita/_events.py`     | 4 bare `except Exception: pass` blocks at lines 193/223/241/288 swallow all errors. |
| #317 | behaviour-wrong  | XS   | `src/ita/_send.py`       | `run` echo-row not-found warns but envelope/rc still success — false positive to agent. |
| #319 | data-loss-risk   | S    | `src/ita/_session.py`    | `async_restart` returns stale `old_id` when replacement lookup fails — agent holds dead ref. |
| #320 | security         | S    | `src/ita/_interactive.py`| REPL `shlex.split` without whitelist — injection risk on agent-controlled sessions. |
| #322 | behaviour-wrong  | XS   | `src/ita/_session.py`    | `INVALID_PROFILE_NAME` caught via `str(e)` match on generic `Exception` — swallows unrelated errors. |
| #324 | behaviour-wrong  | XS   | `src/ita/_send.py`       | `run --persist` has known output race, no runtime guard, no help-text warning. |
| #326 | behaviour-wrong  | M    | `src/ita/_send.py`       | `run` no-shell-integration path kills long commands after ~2s; no `--timeout` override. |
| #329 | behaviour-wrong  | XS   | `src/ita/_management.py` | `_profile_set` color regex matches unintended `*_color` properties; needs explicit whitelist. |

## Groupings (proposed sub-waves)

### Group A: `_send.py` (send/run command surface)
Bugs: #234, #317, #324, #326
Rationale: all four land in `_send.py` on related code paths (shell-integration
detection, `run`, `run --persist`, escalation ladder). Dispatching one agent
avoids merge conflicts on overlapping functions; #326 may touch the same
no-shell-integration block that #234 guards.
Suggested dispatch order: #326 (largest, structural: adds `--timeout`) → #234
(fail-open fix, may affect #326's path) → #317 (echo-row envelope) → #324
(persist guard/help text).

### Group B: `_events.py` (event subscription + `on prompt`)
Bugs: #247, #316
Rationale: both in `_events.py`; #316's bare-except cleanup likely overlaps the
timeout-silence code in #247 (line 61 vs 193/223/241/288). One agent avoids
thrashing exception handling twice.
Suggested dispatch order: #316 (sets the exception-handling pattern) → #247
(apply same pattern to timeout path).

### Group C: `_session.py` (session lifecycle / exception handling)
Bugs: #319, #322
Rationale: both in `_session.py`, both about exception handling around session
operations. #322's specific-exception refactor informs #319's "raise structured
error" fix.
Suggested dispatch order: #322 → #319.

### Group D: `_config.py` (config subcommands)
Bugs: #249, #287
Rationale: both in `_config.py`; #249 is `broadcast on` (line ~405), #287 is
`var list` (line ~158). Different subcommands but same module — one agent, no
collision with other groups.
Suggested dispatch order: #287 (simple rc-fix, fast warm-up) → #249 (likely
deeper: state persistence bug).

### Group E: `_lock.py` (quiet-mode cleanup)
Bugs: #228
Rationale: solo, trivial; route all echo paths through quiet-aware helper.

### Group F: `_query.py` (wait)
Bugs: #231
Rationale: solo; `wait` text-mode rc contract fix.

### Group G: `_tmux.py` (tmux contract)
Bugs: #233
Rationale: solo; depends on contract decision (rc!=0 on no-connection vs. keep
silent-pass). Flag for Alex before coding.

### Group H: `_interactive.py` (REPL)
Bugs: #320
Rationale: solo security fix; subcommand whitelist in REPL loop.

### Group I: `_management.py` (profile set)
Bugs: #329
Rationale: solo; tighten color-property regex → explicit whitelist.

## Parallelization plan

All groups touch disjoint files, so in principle every group is
parallelizable:

- **Parallelizable set (all file-disjoint):** A (`_send.py`), B (`_events.py`),
  C (`_session.py`), D (`_config.py`), E (`_lock.py`), F (`_query.py`),
  G (`_tmux.py`), H (`_interactive.py`), I (`_management.py`).
- **Caveat — shared test infrastructure:** if groups touch common fixtures
  (CLI runner, envelope helpers, shared golden files), serialize the
  test-harness-touching PRs. Safer: merge-serialize A and B first (highest
  surface area), then run C/D/E/F/G/H/I as a parallel fan-out.
- **No group requires solo runtime isolation** on source files; #233 (Group G)
  is the only one that may need a design decision before dispatch.

## Priority recommendation

Top 3 to ship first (by severity × blast radius):

1. **#320** — security: REPL shell injection. Only security-tagged bug in the
   wave; agent-controlled input reaching `shlex.split` → shell is the highest
   blast radius. Ship first even though REPL is lower-traffic than `run`.
2. **#319** — data-loss-risk: `async_restart` returning stale `old_id` causes
   the agent to silently operate on a dead session. Any subsequent
   `send`/`run` against that id is lost work from the agent's POV.
3. **#326** — behaviour-wrong, highest-traffic path: `run` kills legitimate
   long commands at ~2s with no override. This is the common path for every
   agent without shell integration; unblocks `make`, `pip install`, tests.

Runner-up: #316 (four silent-failure blocks in `_events.py`) — broad
invisible-failure surface, fix is mechanical, ship alongside top 3 if capacity.

## Surprises / notes

- **#233 needs a design call, not just a fix.** The issue body explicitly asks
  whether rc=0 on no-connection is the intended contract. Agent should surface
  the question rather than assume.
- **Group A (`_send.py`) is the hot zone** — 4 of 15 bugs land there. Worth
  sequencing carefully; a single agent handling all four avoids repeated
  merge conflict resolution on the escalation ladder / shell-integration
  branch.
