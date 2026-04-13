# ita — CONTRACT

> **Status:** Draft 1. This document is the north star. Every open PR must cite a section here; every change to ita's observable surface must amend this file in the same PR. If a rule isn't in this document, it isn't a rule.

Schema version: **`ita/1`**.

---

## §1 Audience & non-goals

ita is an **agent-only** CLI. The sole intended user is an AI agent (Claude or similar) driving iTerm2 as a direct extension.

**Non-goals — will not be designed for, will not accept PRs for:**
- Human-friendly REPL, interactive wizards, colorised help.
- Alias proliferation (one canonical name per verb; no short/long/legacy aliases).
- Implicit "current" session/tab/window fallbacks.
- UI behaviour beyond what iTerm2 itself provides.
- Localisation of messages. All output is ASCII-safe English.

When agent convenience and human convenience conflict, agent wins.

---

## §2 Identity & resolution

Every session, tab, window, tmux session, and broadcast domain is referenced **explicitly**. There is no implicit "current".

- A session reference is one of: full iTerm2 UUID, a user-set name, or an 8+ character case-insensitive UUID prefix.
- Resolution rules:
  1. Exact UUID match wins.
  2. Exact name match wins.
  3. 8+ char prefix match wins iff exactly one session matches; else error `not-found` (rc=2) or `ambiguous` (rc=6).
  4. Silent fallback to "the focused session" is forbidden.
- Collisions (two sessions sharing a name) are errors, never silently disambiguated.
- Tab / window / tmux / broadcast-domain references follow the same rule: explicit id or name, never implicit.

Resolver shape (session and tab): exact id → exact name/title → 8+ char
case-insensitive id prefix → error. Anything shorter than 8 characters that
isn't an exact id/name match is `not-found` (rc=2), never a "short-prefix"
best-effort. Two or more matches at any stage are `bad-args` (rc=6). Name
comparison reads the *fresh* name variable, not the app-snapshot cache
(#289). The canonical iteration set is `app.terminal_windows`; hotkey and
hidden windows are intentionally excluded (#297). The tab resolver mirrors
this shape: exact tab_id → integer index (current window) → exact title →
8+ char tab_id prefix (#224). Substring / fuzzy matching is forbidden.

Issues codified: #289 (racy cached names), #299 (windows iterable unification), #297, #304, #224.

---

## §3 Output contract

- `stdout` carries **payload only**: the requested data, nothing else.
- `stderr` carries everything diagnostic: warnings, notes, success confirmations, error reasons.
- `--json` mode: stdout is **always valid JSON**, even on error. A malformed `--json` stream is a P0 bug.
- `--quiet` silences *success-path stderr* (the `success_echo` channel). It does not silence warnings or errors.
- `--json-stream` (for streaming commands): stdout is newline-delimited JSON; each line is one event; final event carries the envelope (§4). See §11.
- **Forbidden on stdout, in any mode:**
  - ANSI escape sequences when stdout is not a TTY.
  - NUL (`\x00`), BEL (`\x07`), raw control bytes.
  - Python tracebacks (raw or formatted). Tracebacks are `stderr`-only and only when `ITA_DEBUG=1`.

Issues codified: #296, #318, #331, #327.

---

## §4 Envelope

Every `--json` mutator (any command that changes iTerm2 state) emits a single JSON object on stdout with the following shape:

```json
{
  "schema": "ita/1",
  "ok": true,
  "op": "run",
  "target": {"session": "<uuid>", "name": "<name>"},
  "state_before": "ready",
  "state_after": "ready",
  "elapsed_ms": 123,
  "warnings": [],
  "error": null,
  "data": {}
}
```

- `schema` — this document's version. Bumped on breaking change.
- `ok` — `true` iff exit code 0.
- `op` — the command name (stable, hyphenated form, e.g. `"tab-new"`).
- `target` — resolved identity of the primary object acted on, or `null`.
- `state_before` / `state_after` — session state from §7. Mutators that change session state MUST populate both.
- `elapsed_ms` — wall time of the command.
- `warnings` — list of structured warning objects `{code, reason}`. Empty list, not `null`.
- `error` — `null` on success. On failure: `{code: <exit-code-symbol>, reason: <one-line>}`. See §6.
- `data` — command-specific payload. Schema defined per command in its help text and `ita commands --json` output.

**Read-only** commands (`status`, `overview`, `get-prompt`, `read`) MAY omit the envelope and return their payload directly — but they MUST still be valid JSON in `--json` mode.

**Inner-process exit codes (Phase 3 envelope-exit-taxonomy clarification).** Commands that wrap a foreign process (`run`, `run --stdin`) report **two** exit codes that must not be conflated:
- `data.exit_code` — the inner command's own rc (may be `null` when shell integration is missing, per #144).
- The envelope's top-level `error` + ita's process exit code — ita's own success/failure per §6.
ita exits `0` whenever the wrapping ran cleanly, even if `data.exit_code != 0`. Operational failures of ita itself (timeout, locked, not-found, …) raise `ItaError` and produce `ok=false` + the §6-mapped exit code in **both** plain and `--json` modes (§14.3). Plain-mode `run` legacy behaviour (propagating the inner rc, exiting `124` on timeout) is preserved during the pilot migration and will be aligned to §6 in a follow-up PR.

**Schema evolution:** additive field changes bump no version. Removing a field or changing a type bumps the major schema (`ita/2`). Breaking changes require a migration note in this file.

Issues codified: #266, #323, #260.

---

## §5 Protocol posture

**Decision:** ita's CLI *is* the protocol. It will not grow a JSON-RPC or MCP wrapper unless a concrete consumer need emerges.

- Every command declares: name, typed inputs (via Click), output schema (§4), exit codes (§6), and side-effects (in `--help`).
- `ita commands --json` (in `_meta.py`) is the machine-readable index of the surface.
- Agents invoke ita by shelling out; state persists in files (`~/.ita_protected`, `~/.ita_writelock`) and in iTerm2 itself. There is no long-lived ita daemon.

This decision is recorded so it does not get re-debated. To revisit, open an RFC issue referencing this section.

---

## §6 Exit codes

Mode-independent: identical in plain, `--json`, and `--json-stream` output.

| Code | Symbol | Meaning |
|---|---|---|
| `0` | `ok` | Success. |
| `2` | `not-found` | Session / tab / window / domain not found or no longer exists. |
| `3` | `protected` | Target is protected; caller did not pass `--force-protected`. |
| `4` | `timeout` | Operation exceeded `--timeout` or internal deadline. |
| `5` | `locked` | Another process holds the write lock on this session. |
| `6` | `bad-args` | Invalid input: malformed filter, ambiguous prefix, type mismatch. |
| `7` | `api-unreachable` | iTerm2 Python API connection refused or dropped. |
| `8` | `no-shell-integration` | Command required shell integration; session lacks it. |

Exit codes 1, 9+ are reserved. `1` is only used for uncaught Python exceptions (P0 bug if it appears in normal paths).

The #290 regression (plain-mode returned `0` on timeout while `--json` returned `4`) is prohibited; the taxonomy is enforced by `test_contracts.py`.

Issues codified: #266, #290.

---

## §7 Session state machine

Every session has exactly one state at any time:

| State | Meaning |
|---|---|
| `creating` | Session exists in iTerm2 but shell/API not yet stable. |
| `ready` | Shell alive, prompt visible, writable, shell integration detected. |
| `busy` | A foreground command is running; no prompt. |
| `waiting_prompt` | Shell running but no detectable prompt (e.g. paused TUI). |
| `no_shell_integration` | Shell alive, writable, but shell integration not installed. |
| `timed_out` | Last operation exceeded its deadline; state may be indeterminate. |
| `locked` | Write lock held by another process. |
| `dead` | Session no longer exists in iTerm2. |

- Every command that returns session info includes the current `state`.
- `ita status --json -s <id>` is the cheap canonical lookup.
- Transitions are derived, not stored; `_readiness._probe` is the source of truth.

**Canonical derivation.** `ita._state.derive_state(app, session)` is the single
implementation. Callers MUST use it — no command may reimplement the decision
tree locally. This keeps the state enum observably consistent across
`status`, `session info`, `overview`, and every future surface.

**`timed_out` is caller-set, never derived.** `derive_state` only reports the
*current* state of a session; it never returns `timed_out`. Commands that
hit their own deadline set `state_after = "timed_out"` on the envelope
explicitly (per §8). A subsequent `derive_state` call re-observes whatever
state the session is now in (often `busy` or `ready`).

**Enum stability.** The eight state strings are stable schema. Adding a new
state, renaming one, or changing the priority order is a breaking change
and requires bumping the envelope schema to `ita/2` (per §15).

Issues codified: #267, #288.

---

## §8 Readiness

- Every **create-then-return** operation (`session new`, `tab new`, `window new`, `restart`) calls the canonical `wait_until_ready()` helper before returning, unless `--no-wait` is passed.
- The helper is `_readiness.stabilize`. It polls `_probe` until the requested flag set is satisfied or the timeout elapses.
- Default required flags: `shell_alive`, `writable`. Opt-in flags: `prompt_visible`, `shell_integration_active`, `jobName_populated`.
- On timeout: envelope `error.code = "timeout"`, `state_after = "timed_out"`, exit code `4`.

Issues codified: #257, #268 (closed — promoted into this contract).

---

## §9 Prompt detection

Exactly one function owns prompt detection: `_core._is_prompt_line` (to live in `_screen.py` after the Phase 2 split).

**Rules:**
- A line is a prompt iff, after stripping NUL and trailing whitespace, it ends with one of the configured prompt characters (`$`, `%`, `#`, `>`, `❯`, `›`, plus user extensions via `ITA_PROMPT_CHARS`).
- UTF-8 glyphs are safe: detection operates on decoded codepoints, not bytes.
- Echo remnants (a command line echoed back by the shell) are NOT prompts. Detection must reject lines containing a prompt char followed by non-whitespace content.
- Empty lines are not prompts.

Regressions against this rule live under `@pytest.mark.regression` in `test_contracts.py`.

Issues codified: #288, #327, #331.

---

## §10 Protection & locking

**Protection** = the session is off-limits to write operations unless `--force-protected` is passed. Stored in `~/.ita_protected`.

**Write lock** = at most one process may send keystrokes / run commands / mutate a session at any time. Stored in `~/.ita_writelock`, keyed on `(session_id, pid, cookie)`. **Parent-PID-based ownership is forbidden** (regression guard for closed #282).

Invariants enforced on every write path, including bulk paths (`broadcast`, `close --all`, `tab detach`, multi-session `run`):

1. **Every mutator** checks protection before acquiring the lock.
2. **Every mutator** acquires the write lock (via `session_writelock` context manager) before issuing an iTerm2 mutation.
3. **Readers are concurrent**: read-only commands (`status`, `read`, `get-prompt`, `overview`, `watch`, `stream`, `wait`) do not acquire the lock.
4. **Writers are exclusive**: only one process may hold the write lock for a given session at a time. Conflicting attempts fail with rc=5.
5. **Stale locks** (dead PID, mismatched cookie) are reclaimed on acquire under `fcntl.LOCK_EX`.
6. **`--force` is split into two flags** (resolves overload #294):
   - `--force-protected` — bypass the protection check.
   - `--force-lock` — reclaim an active lock from another live process. Use with caution; logged to `stderr`.

Bulk operations are **set-merge, not replace** (#258, #285, #220). A session belonging to multiple broadcast domains receives each message exactly once.

**`--force-protected` vs `--force-lock` (resolves #294):**

The legacy `--force` flag is deprecated and emits a one-line deprecation warning to stderr the first time it is used in a process. It is kept as an alias that sets BOTH new flags simultaneously.

| Flag | Bypasses | Does NOT bypass |
| --- | --- | --- |
| `--force-protected` | protection check (`~/.ita_protected` membership) | write-lock |
| `--force-lock` | write-lock held by another live process | protection check |
| `--force` (deprecated) | both, with warning | — |

The two flags are **orthogonal**: passing only `--force-protected` against a session held by another ita invocation still fails with `rc=5 locked`; passing only `--force-lock` against a protected session still fails with `rc=3 protected`. Neither flag implies the other.

**Bulk ops are gated per-target.** `session close --all`, `session clear --where`, and `broadcast send` each iterate members and run `check_protected` + `session_writelock` for every target. A protected member in a fleet is skipped and reported in the per-member result array (never silently included). A locked member surfaces `rc=5` for that member and the bulk envelope reports it via `warnings[]` / the per-member record; the orchestrator's own lock is not a substitute for per-member locking (#283, #258).

Issues codified: #283, #258, #294, #321, #282 (closed), #220, #285, #279, #284.

---

## §11 Streaming & Monitor-compatibility

Commands with live output: `watch`, `stream`, `wait`, and `run --timeout` when the timeout is long enough to be worth tailing.

With `--json-stream`:
- stdout is newline-delimited JSON, one event per line, flushed per event.
- Each event has `{"type": "<frame|prompt|timeout|...>", "ts_ms": <int>, ...}`.
- The **final** line on stdout is always the envelope (§4), marking command completion.
- No partial lines; no interleaving of non-JSON noise on stdout.

This shape is designed so Claude Code's `Monitor` tool (or any line-oriented consumer) can tail the stream reliably. Any regression that produces mid-line output, unclosed events, or a missing terminal envelope is a P0 bug.

Without `--json-stream`, streaming commands behave as before — plain text on stdout, framing advisory only.

Issues codified: #296 (streaming facet).

---

## §12 Confirmation

- No interactive prompt is ever shown unless `--confirm` is explicitly passed.
- Destructive operations (`close`, `close --all`, `unprotect`, `restart`, `kill`, `tab close`, `window close`, `layouts delete`) default to **refuse** when called without one of:
  - `-y / --yes` (proceed),
  - `--dry-run` (describe, don't act; exit 0),
  - `--confirm` (prompt; only usable from a TTY).
- `confirm_or_skip` is the single gate function. Agent callers pass `-y`.

This restores the intended #246 behaviour.

---

## §13 Bulk-op semantics

- **Set-merge**, never replace: adding to a broadcast domain, tab, or tag set never silently drops prior members.
- **No duplicate delivery**: a session belonging to two broadcast domains receives a broadcast message once, not twice.
- **Partial failure is reported, not hidden**: `warnings[]` lists each failed member; envelope `ok` reflects overall success (`ok=false` if any member failed and `--all-or-nothing` was passed; otherwise `ok=true` with warnings).

Issues codified: #258, #285, #220.

---

## §14 The six agent-critical invariants

Iterated by `tests/test_contracts.py` over every command in `ita commands --json`.

1. **Never lie to the caller.** No command reports success when its effect didn't happen. No envelope has `ok=true` with `error != null`.
2. **No stdout pollution.** Stdout obeys §3 in every mode. No ANSI in non-TTY, no NUL, no traceback.
3. **Exit code matches envelope.** `ok=true ⇔ rc=0`. `ok=false ⇔ rc ∈ §6 \ {0}`. Identical across plain and JSON modes.
4. **Protection and lock are never bypassed silently.** Every mutator is gated. Bulk paths enumerated and tested.
5. **Identity is explicit.** No command succeeds against an implicitly-resolved target. Ambiguous prefix = rc=6.
6. **Readiness is honoured.** Create-then-return commands don't return before the session is `ready` (or the caller passed `--no-wait`).

Issues codified: #292.

---

## §15 Versioning & schema stability

- The **package version** (`pyproject.toml` == `plugin.json`) follows semver.
- The **envelope schema** (`"schema"` field) is independent. Additive changes keep `ita/1`; breaking changes advance to `ita/2` and this file gains a migration note.
- Version bumps happen in a single PR touching both manifests. No drift tolerated.
- Current target: **`0.7.0`** (aligning pyproject up to plugin.json); schema `ita/1`.

---

## §16 Out-of-scope

PRs that add any of the following will be closed with a pointer here:

- Human-interactive REPL or wizard modes.
- Auto-detection of "the current session" beyond what `--target` / `-s` provides.
- Colorised or decorated help output.
- Short or legacy aliases for existing commands.
- Localised or translated strings.
- A long-lived daemon or background watcher process.
- MCP/JSON-RPC wrapper layers (see §5).
- Wrappers around iTerm2 features that already have a native iTerm2 UI with no agent-workflow benefit.

---

## Appendix A — issue → section index

| Issue | Section |
|---|---|
| #220, #258, #285 | §10, §13 |
| #246 | §12 |
| #248, #286 | §3 |
| #256 | Phase 2 (packaging) — not a CONTRACT clause |
| #257 | §8 |
| #259 | this document |
| #260, #266, #323 | §4 |
| #265 | §1 |
| #267 | §7 |
| #268 (closed) | §8 |
| #282 (closed) | §10 |
| #283, #294, #321 | §10 |
| #284 | §10 |
| #288 | §7, §9 |
| #289, #297, #299, #304 | §2 |
| #290 | §6 |
| #292 | §14 |
| #296 | §3, §11 |
| #316, #318, #322 | §3, §4 |
| #327, #331 | §3, §9 |

---

## Appendix B — amendment procedure

1. Every PR that changes ita's observable surface amends this file in the same commit.
2. Breaking changes (exit codes removed, envelope fields removed or retyped, state names removed) bump the schema version and add a migration note under the relevant section.
3. Closed issues that encoded a decision are summarised in `docs/DECISIONS.md` with a pointer back to the section here that governs the area.
