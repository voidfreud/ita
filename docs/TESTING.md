# ita Testing Charter

This document is the contract for the test suite. It defines **what we test**, **how we categorize it**, **what fixtures exist**, and **what third-party tools we lean on**. It exists so that parallel contributors (human or agent) can add tests in any module without re-deciding architecture each time.

Scope of this document: scaffolding only. It sets the frame; individual test files are filled in per module in follow-up PRs. See issue #136 for the execution plan.

---

## 1. Goals

1. Every `@cli.command` is exercised across the **test-class matrix** below — missing cells are explicit TODOs, not silent gaps.
2. Existing tests are preserved and re-categorized (via markers), not discarded.
3. Tests **challenge** the code: adversarial, property-driven, concurrency-aware.
4. Every closed bug issue maps to a regression test tagged with its issue number.
5. Cross-cutting contracts (`--json` parity, `--quiet`, exit codes, output hygiene) are verified once, centrally.
6. CI lanes are separable: fast lane on every push; integration / stress / adversarial on slower schedules.

Non-goals: 100% line coverage as the metric; rewriting every existing test; GUI-level testing of iTerm2 itself; stabilizing async races (tag `xfail_flaky` and file a bug instead).

**Integration lane takes over iTerm2 during execution.** Real windows/tabs spawn, focus moves, "Quit iTerm?" dialogs can surface, tests may follow you across virtual desktops. Run on an idle machine / dedicated VM / ssh session. Do not run while using the computer. Mitigations in progress: #379 (fixtures --background), #380 (named test tabs), #381 (quit dialog), #382 (cross-desktop), #383 (leak cleanup).

---

## 2. Test-class matrix

Every `@cli.command` is exercised across these classes. A cell that doesn't apply (e.g. `property` for a no-arg command) is marked `N/A`; a cell not yet written is `TODO`.

| Class         | What it verifies                                                                                                       | Marker        |
|---------------|------------------------------------------------------------------------------------------------------------------------|---------------|
| Happy path    | Documented behavior works on typical input                                                                             | _(default)_   |
| Edge          | Empty / huge / unicode / whitespace / 40-session app / already-closed session / session at prompt vs mid-command       | `edge`        |
| Error         | Missing args, wrong types, nonexistent session/profile, permission denied, session protected, shell-integration absent | `error`       |
| Adversarial   | Concurrent writes, stale UUID mid-op, partial broadcast domain, race on `--reuse`, iTerm2 disconnect mid-call          | `adversarial` |
| State         | Idempotency; close really closes; protect persists across invocations; restart preserves UUID semantics                | `state`       |
| Contract      | `--json` schema parity, `--quiet` behavior, exit codes, no bare `Error: 1`, no `\x00`/ANSI/BEL leakage                 | `contract`    |
| Property      | Hypothesis-driven fuzz over IDs, names, commands, timeouts, hex payloads; assert invariants, not values                | `property`    |
| Regression    | One named test per closed bug, tagged with issue number                                                                | `regression`  |
| Stress        | N sessions × M commands in parallel; leak detection; memory ceiling                                                    | `stress`      |
| Performance   | Per-command latency budgets (p50 / p99)                                                                                | `perf`        |

Existing markers preserved: `integration`, `known_broken`, `xfail_flaky`.

---

## 3. Marker registry

Canonical definitions live in `pyproject.toml` under `[tool.pytest.ini_options] markers`. Any test using an unregistered marker should fail `pytest --strict-markers`.

| Marker         | Auto-skip? | Notes                                                              |
|----------------|-----------|--------------------------------------------------------------------|
| `integration`  | yes, if iTerm2 / API unreachable | Live iTerm2 required                     |
| `stress`       | yes, same  | Slow; weekly or on-demand                                          |
| `perf`         | yes, same  | Benchmarks; nightly                                                |
| `adversarial`  | no         | Runs on PRs touching write paths                                   |
| `regression`   | no         | Every push — guards history                                        |
| `contract`     | no         | Cross-cutting; fast                                                |
| `property`     | no         | Hypothesis; fast profile on push, thorough profile nightly         |
| `edge`         | no         | Included in fast lane                                              |
| `error`        | no         | Included in fast lane                                              |
| `state`        | no         | Included in fast lane                                              |
| `known_broken` | xfail      | Documents unfixed bug                                              |
| `xfail_flaky`  | xfail      | Async/race — file a bug, do not fix here                           |

---

## 4. Fixture contracts (`tests/conftest.py`)

Existing fixtures stay. All fixtures below are implemented in `tests/conftest.py` (thin re-exports from `tests/fixtures/`).

| Fixture                 | Scope    | Contract                                                                              |
|-------------------------|----------|---------------------------------------------------------------------------------------|
| `session`               | function | Fresh iTerm2 session; guaranteed teardown; tracks leaks                               |
| `shared_session`        | module   | Reusable read-only session across tests (faster happy-path reads)                     |
| `sweep_leaked_sessions` | session  | Pre/post sweep of orphaned test sessions                                              |
| `ita` / `ita_ok`        | —        | Subprocess helpers; `ita_ok` asserts rc=0 and returns stdout                          |
| `session_factory`       | function | Create N sessions in parallel for stress tests                          |
| `broadcast_domain`      | function | Setup + teardown of a broadcast-on group                                |
| `protected_session`     | function | Session with protect-on, parametrized with/without `--force`            |
| `clean_iterm`           | session  | Baseline snapshot + post-test diff; assert no orphan tabs/windows       |
| `hypothesis_profiles`   | —        | Fast CI profile (few examples) vs thorough nightly profile              |

**Rule:** no test spins up its own session outside fixtures. All lifecycle goes through the registry so `sweep_leaked_sessions` can detect leaks.

### 4.1 Cleanup is unmissable (#341)

A leaky test suite once opened ~500 sessions and crashed the host. Cleanup is **non-negotiable** and must work even when a test crashes mid-creation.

| Layer | Mechanism | Purpose |
|---|---|---|
| 1 | Per-test `addfinalizer` in every fixture that creates iTerm2 state | Normal-path teardown |
| 2 | `try/finally` inside `session_factory` and any fixture creating > 1 object | Crash-during-create still triggers cleanup of partials |
| 3 | Module-level `atexit` hook in `tests/conftest.py` that closes every `ita-test-*` session | Belt-and-braces; runs even on signal/timeout |
| 4 | **Hard-ceiling sentinel** — between tests, count `ita-test-*` sessions; if > 50, abort the entire pytest run with a loud error | Catastrophic-leak circuit breaker |
| 5 | Every test fixture creates objects in *existing* windows by default (tabs over windows) so an orphan tab is cheaper than an orphan window | Reduce per-leak blast radius |

**Naming convention:** every test-created object is prefixed `ita-test-` so cleanup can identify them deterministically. Naming is mandatory per CONTRACT §2.

**Window-leak audit:** if a test creates a session in a new window, the *window* leaks too (orphan windows are worse than orphan tabs). Prefer tab-creation tests; use `--allow-window-close` only when the window is genuinely test-owned and you also pass `--allow-window-close` on cleanup.

**Failure mode:** if you suspect a leak, run `ita status --json | jq '[.[] | select(.session_name | startswith("ita-test-"))] | length'`. Anything > 0 outside an active test run is a leak; `ita close --where session_name~=ita-test- --all-or-nothing -y --allow-window-close` clears them.

---

## 5. Cross-cutting contracts (`tests/test_contracts.py`)

A single parametrized file iterates every command and asserts:

- **`--json` parity** (#142): commands listed as `--json`-capable emit valid JSON with a stable schema (schema dict lives alongside the test).
- **`--quiet` behavior** (#139): when supported, success paths produce zero stdout; errors still go to stderr.
- **Exit codes**: `0` on success, non-zero on failure; no bare `Error: 1`.
- **Output hygiene**: no `\x00`, no ANSI leakage in non-TTY, no BEL (#135).
- **`-s NAME` / `-s UUID-prefix`**: both forms resolve identically.
- **Protection**: every write command (`run`, `send`, `key`, `inject`, `close`, `clear`, `restart`) refuses a protected session without `--force`.

The command inventory (§8) is the source of truth for what gets iterated.

---

## 6. Third-party tools — complement, don't replace

ita's first-party contract tests stay first-class. Third-party tools fill specific niches where they do a job we'd otherwise do badly by hand.

| Tool                 | Role                                                                                     | Added via                             |
|----------------------|------------------------------------------------------------------------------------------|---------------------------------------|
| **pytest**           | Runner (already in use)                                                                  | `dev` extra                           |
| **hypothesis**       | Property-based fuzz for IDs, names, payloads, timeouts (already in use)                  | `dev` extra                           |
| **pytest-cov**       | Line + branch coverage; CI artifact; per-module density table in this doc                | `dev` extra                           |
| **pytest-xdist**     | Parallel test execution for the fast lane and stress matrix                              | `dev` extra                           |
| **pytest-timeout**   | Global timeout guard — prevents hangs in adversarial / stress lanes                      | `dev` extra                           |
| **pytest-benchmark** | `perf` lane latency budgets (per-command p50 / p99)                                      | `dev` extra                           |
| **jsonschema**       | Validate `--json` output against schemas in the contract lane                            | `dev` extra                           |
| **hyperfine**        | External latency benchmarks where pytest-benchmark's in-process timing is misleading     | system binary (doc-only dep)          |
| **ruff**             | Lint/format — keeps test files consistent (not a test tool but part of the CI lane)      | `dev` extra                           |

**Principle:** a third-party tool enters the stack when it replaces hand-rolled infrastructure we'd otherwise maintain (parallel runners, coverage, schema validation). It does **not** enter to produce tests we should be writing ourselves — adversarial scenarios, effect assertions, regression guards remain hand-written, because they encode domain knowledge a generic tool can't infer.

Any tool added here gets a one-line justification in the table and is wired into `pyproject.toml`'s `dev` extra.

---

## 7. CI lanes

Wiring is deferred to a follow-up PR; the contract is fixed now so tests can be written against it.

| Lane          | Selector                                                            | Trigger             |
|---------------|---------------------------------------------------------------------|---------------------|
| Fast          | `pytest -m "not integration and not stress and not perf"`           | Every push          |
| Integration   | `pytest -m "integration"`                                           | Nightly             |
| Stress        | `pytest -m "stress"`                                                | Weekly / on-demand  |
| Adversarial   | `pytest -m "adversarial"`                                           | PRs touching writes |
| Regression    | `pytest -m "regression"`                                            | Every push          |
| Perf          | `pytest -m "perf" --benchmark-only`                                 | Nightly             |

Coverage report (`pytest --cov=src --cov-report=xml`) is attached as a CI artifact.

### 7.2 Flake cadence

Run `python scripts/flake_check.py` **quarterly** (or after any test-stability incident).
The script re-runs every test tagged `xfail_flaky` 20 times and buckets results:

- **True race** (0 % < pass rate < 100 %) — keep the marker, open or update a tracking issue.
- **Stable xfail** (0 % pass) — the test never passes; remove it or replace with a `known_broken` stub.
- **False flake** (100 % pass) — the flakiness is gone; remove the `xfail_flaky` marker.

Each tagged test must be triaged at least once per quarter.
A CI job (`flaky-staleness` in `.github/workflows/ci.yml`) fails if any `xfail_flaky` test hasn't been touched in the last 6 months, enforcing the cadence automatically.

### 7.1 Budget table (perf lane)

Budgets are enforced in `tests/test_perf.py`. A violation causes `rc != 0` in the `perf` lane.
`p99` over 20 samples is effectively the maximum value for that run; this is acceptable as a gate.

| Command                          | p50 budget | p99 budget | Notes                                              |
|----------------------------------|------------|------------|----------------------------------------------------|
| `ita status --json`              | < 100 ms   | < 300 ms   |                                                    |
| `ita version`                    | < 50 ms    | —          | No iTerm2 API call expected; violation = candidate bug |
| `ita run 'echo hi' -s <session>` | < 500 ms   | < 1.5 s    |                                                    |
| `ita var get foo -s <session>`   | < 200 ms   | < 600 ms   |                                                    |
| `ita send 'x' -s <session>`      | < 200 ms   | —          |                                                    |
| `ita new` (create + register)    | < 1 s      | < 2.5 s    |                                                    |
| `ita tab list --json`            | < 200 ms   | —          |                                                    |

---

## 8. Command inventory (matrix tracker)

Source of truth: `src/_*.py`. Regenerate this table from a script when commands are added or removed — do not hand-edit drift.

Legend per class cell: `✓` covered with real assertions, `s` smoke-only (rc=0), `—` not applicable, `g` = no-coverage (tracked as gap in §8.2). `C` = covered by `tests/test_contract_matrix.py` parametrized matrix (all commands in `tests/_contract_categories.py`).

110 leaf commands total (every node walked from `ita commands --json` whose own `commands` list is empty); 30 support `--json`. The number matches `len(CATEGORIES)` in `tests/_contract_categories.py` and is enforced by `tests/test_contract_matrix.py::test_categorization_covers_surface`.

### Orientation (`_orientation.py`)

| Command        | json | Happy | Edge | Error | Adv | State | Contract | Prop | Regr | Stress | Perf |
|----------------|------|-------|------|-------|-----|-------|----------|------|------|--------|------|
| `status`       | Y    | ✓     | ✓    | g     | ✓   | g     | ✓        |  —   | g    | g      | g    |
| `focus`        | Y    | ✓     | g    | g     | g   | g     | ✓        |  —   | g    | g      | g    |
| `version`      | N    | ✓     |  —   |  —    |  —  |  —    | C        |  —   | g    |  —     |  —   |
| `protect`      | N    | ✓     | g    | ✓     | g   | ✓     | C        |  —   | g    | g      | g    |
| `unprotect`    | N    | ✓     | g    | g     | g   | ✓     | C        |  —   | g    | g      | g    |
| `session info` | Y    | ✓     | g    | g     | g   | ✓     | ✓        | g    | g    | g      | g    |

### Session (`_session.py`)

| Command   | json | Happy | Edge | Error | Adv | State | Contract | Prop | Regr | Stress | Perf |
|-----------|------|-------|------|-------|-----|-------|----------|------|------|--------|------|
| `new`     | Y    | ✓     | ✓    | ✓     | ✓   | ✓     | ✓        | ✓    | ✓    | ✓      | g    |
| `close`   | N    | ✓     | ✓    | ✓     | ✓   | ✓     | ✓        | ✓    | ✓    | g      | g    |
| `activate`| N    | s     | ✓    | ✓     | g   | g     | C        |  —   | g    | g      | g    |
| `name`    | N    | ✓     | ✓    | g     | g   | ✓     | ✓        | ✓    | g    | g      | g    |
| `restart` | N    | s     | ✓    | ✓     | g   | g     | ✓        |  —   | ✓    | g      | g    |
| `resize`  | N    | ✓     | ✓    | ✓     | g   | g     | ✓        | ✓    | g    | g      | g    |
| `clear`   | N    | s     | ✓    | g     | g   | g     | ✓        |  —   | g    | g      | g    |
| `capture` | N    | ✓     | ✓    | g     | g   | g     | ✓        | g    | g    | g      | g    |

### Send / run (`_send.py`)

| Command  | json | Happy | Edge | Error | Adv | State | Contract | Prop | Regr | Stress | Perf |
|----------|------|-------|------|-------|-----|-------|----------|------|------|--------|------|
| `run`    | Y    | ✓     | ✓    | ✓     | ✓   | ✓     | ✓        | ✓    | ✓    | ✓      | g    |
| `send`   | N    | ✓     | ✓    | g     | ✓   | ✓     | ✓        | ✓    | g    | g      | g    |
| `inject` | N    | ✓     | ✓    | ✓     | g   | ✓     | ✓        | ✓    | ✓    | g      | g    |
| `key`    | N    | ✓     | ✓    | ✓     | g   | g     | ✓        | ✓    | g    | g      | g    |

### Output / query (`_output.py`, `_query.py`, `_stream.py`)

| Command       | json | Happy | Edge | Error | Adv | State | Contract | Prop | Regr | Stress | Perf |
|---------------|------|-------|------|-------|-----|-------|----------|------|------|--------|------|
| `read`        | N    | ✓     | ✓    | ✓     | ✓   | g     | ✓        | ✓    | g    | g      | g    |
| `wait`        | Y    | ✓     | g    | ✓     | g   | g     | ✓        | g    | g    | g      | g    |
| `selection`   | Y    | ✓     | g    | g     | g   | g     | ✓        | g    | g    | g      | g    |
| `copy`        | N    | s     | g    | ✓     | g   | g     | C        |  —   | g    | g      | g    |
| `get-prompt`  | Y    | ✓     | g    | ✓     | g   | g     | ✓        |  —   | g    | g      | g    |
| `watch`       | Y    | ✓     | ✓    | ✓     | g   | g     | ✓        | g    | ✓    | g      | g    |

### Lock (`_lock.py`)

| Command  | json | Happy | Edge | Error | Adv | State | Contract | Prop | Regr | Stress | Perf |
|----------|------|-------|------|-------|-----|-------|----------|------|------|--------|------|
| `lock`   | N    | ✓     | g    | ✓     | g   | ✓     | C        |  —   | g    | g      | g    |
| `unlock` | N    | ✓     | g    | ✓     | g   | ✓     | ✓        |  —   | g    | g      | g    |

### Tab (`_tab.py`)

| Command        | json | Happy | Edge | Error | Adv | State | Contract | Prop | Regr | Stress | Perf |
|----------------|------|-------|------|-------|-----|-------|----------|------|------|--------|------|
| `tab new`      | N    | ✓     | ✓    | ✓     | g   | g     | C        |  —   | g    | g      | g    |
| `tab close`    | N    | ✓     | g    | ✓     | g   | ✓     | C        |  —   | g    | g      | g    |
| `tab activate` | N    | g     | g    | ✓     | g   | g     | C        |  —   | g    | g      | g    |
| `tab next`     | N    | ✓     | g    | g     | g   | ✓     | C        |  —   | ✓    | g      | g    |
| `tab prev`     | N    | ✓     | g    | g     | g   | g     | C        |  —   | ✓    | g      | g    |
| `tab goto`     | Y    | ✓     | ✓    | ✓     | g   | g     | C        | g    | g    | g      | g    |
| `tab list`     | Y    | ✓     | g    | g     | g   | g     | ✓        |  —   | g    | g      | g    |
| `tab info`     | Y    | ✓     | g    | ✓     | g   | g     | ✓        | g    | g    | g      | g    |
| `tab detach`   | N    | ✓     | g    | ✓     | g   | g     | C        |  —   | g    | g      | g    |
| `tab move`     | N    | g     | g    | g     | g   | g     | C        | g    | g    | g      | g    |
| `tab profile`  | N    | g     | g    | ✓     | g   | g     | C        | g    | g    | g      | g    |
| `tab title`    | N    | ✓     | ✓    | g     | g   | ✓     | C        | ✓    | g    | g      | g    |

### Window (`_layout.py`)

| Command              | json | Happy | Edge | Error | Adv | State | Contract | Prop | Regr | Stress | Perf |
|----------------------|------|-------|------|-------|-----|-------|----------|------|------|--------|------|
| `window new`         | N    | ✓     | g    | ✓     | g   | g     | C        |  —   | g    | g      | g    |
| `window close`       | N    | ✓     | ✓    | ✓     | g   | ✓     | ✓        |  —   | g    | g      | g    |
| `window activate`    | N    | ✓     | g    | ✓     | g   | g     | C        |  —   | g    | g      | g    |
| `window title`       | N    | ✓     | ✓    | g     | g   | ✓     | C        | ✓    | g    | g      | g    |
| `window fullscreen`  | N    | ✓     | g    | ✓     | g   | ✓     | C        |  —   | g    | g      | g    |
| `window frame`       | N    | ✓     | ✓    | g     | g   | ✓     | C        | ✓    | g    | g      | g    |
| `window list`        | Y    | ✓     | g    | g     | g   | g     | ✓        |  —   | g    | g      | g    |

### Pane (`_pane.py`)

| Command | json | Happy | Edge | Error | Adv | State | Contract | Prop | Regr | Stress | Perf |
|---------|------|-------|------|-------|-----|-------|----------|------|------|--------|------|
| `split` | N    | ✓     | ✓    | ✓     | g   | ✓     | ✓        | g    | g    | g      | g    |
| `pane`  | N    | ✓     | g    | ✓     | g   | g     | C        | g    | g    | g      | g    |
| `move`  | N    | g     | g    | ✓     | g   | ✓     | C        | g    | ✓    | g      | g    |
| `swap`  | N    | g     | g    | ✓     | g   | ✓     | C        | ✓    | g    | g      | g    |

### Config (`_config.py`)

| Command          | json | Happy | Edge | Error | Adv | State | Contract | Prop | Regr | Stress | Perf |
|------------------|------|-------|------|-------|-----|-------|----------|------|------|--------|------|
| `var get`        | Y    | ✓     | ✓    | ✓     | g   | ✓     | C        | ✓    | ✓    | g      | g    |
| `var set`        | Y    | ✓     | ✓    | g     | g   | ✓     | C        | ✓    | g    | g      | g    |
| `var list`       | Y    | ✓     | g    | g     | g   | g     | ✓        |  —   | g    | g      | g    |
| `app version`    | N    | s     | g    | g     | g   | g     | C        |  —   | g    | g      | g    |
| `app activate`   | N    | ✓     | g    | g     | g   | g     | C        |  —   | g    | g      | g    |
| `app hide`       | N    | ✓     | g    | g     | g   | g     | C        |  —   | g    | g      | g    |
| `app quit`       | N    | g     | g    | g     | g   | g     | C        |  —   | g    | g      | g    |
| `app theme`      | N    | ✓     | g    | g     | g   | g     | C        | g    | g    | g      | g    |
| `pref get`       | N    | ✓     | g    | ✓     | g   | g     | C        | g    | g    | g      | g    |
| `pref set`       | Y    | ✓     | ✓    | g     | g   | ✓     | ✓        | g    | g    | g      | g    |
| `pref list`      | Y    | ✓     | g    | g     | g   | g     | C        |  —   | g    | g      | g    |
| `pref theme`     | N    | ✓     | g    | g     | g   | g     | C        | g    | g    | g      | g    |
| `pref tmux`      | N    | ✓     | g    | ✓     | g   | g     | C        | g    | g    | g      | g    |
| `broadcast on`   | N    | ✓     | g    | ✓     | ✓   | ✓     | C        |  —   | g    | g      | g    |
| `broadcast send` | N    | ✓     | g    | ✓     | ✓   | g     | C        | g    | g    | g      | g    |
| `broadcast off`  | N    | ✓     | g    | g     | g   | ✓     | C        |  —   | g    | g      | g    |
| `broadcast add`  | N    | ✓     | g    | ✓     | g   | ✓     | C        | g    | g    | g      | g    |
| `broadcast set`  | N    | ✓     | g    | ✓     | g   | ✓     | C        | g    | g    | g      | g    |
| `broadcast list` | Y    | ✓     | g    | g     | g   | g     | ✓        |  —   | g    | g      | g    |

### Interactive (`_interactive.py`)

| Command       | json | Happy | Edge | Error | Adv | State | Contract | Prop | Regr | Stress | Perf |
|---------------|------|-------|------|-------|-----|-------|----------|------|------|--------|------|
| `alert`       | N    | ✓     | ✓    | ✓     | g   | g     | ✓        |  —   | g    | g      | g    |
| `ask`         | N    | ✓     | ✓    | ✓     | g   | g     | ✓        | g    | g    | g      | g    |
| `pick`        | N    | ✓     | ✓    | g     | g   | g     | ✓        | g    | g    | g      | g    |
| `save-dialog` | N    | ✓     | ✓    | g     | g   | g     | ✓        | g    | g    | g      | g    |
| `menu list`   | Y    | ✓     | ✓    | g     | g   | g     | ✓        |  —   | g    | g      | g    |
| `menu select` | N    | g     | g    | ✓     | g   | g     | C        | g    | g    | g      | g    |
| `menu state`  | Y    | ✓     | g    | ✓     | g   | g     | ✓        | ✓    | g    | g      | g    |
| `repl`        | N    | ✓     | ✓    | ✓     | g   | g     | ✓        |  —   | g    | g      | g    |

### Management (`_management.py`)

| Command         | json | Happy | Edge | Error | Adv | State | Contract | Prop | Regr | Stress | Perf |
|-----------------|------|-------|------|-------|-----|-------|----------|------|------|--------|------|
| `profile list`  | Y    | ✓     | ✓    | g     | g   | g     | ✓        |  —   | g    | g      | g    |
| `profile show`  | N    | ✓     | g    | ✓     | g   | ✓     | ✓        | g    | g    | g      | g    |
| `profile get`   | N    | ✓     | g    | g     | g   | g     | C        | g    | g    | g      | g    |
| `profile apply` | N    | g     | g    | ✓     | g   | ✓     | C        | g    | g    | g      | g    |
| `profile set`   | N    | ✓     | g    | ✓     | g   | ✓     | C        | ✓    | ✓    | g      | g    |
| `presets`       | Y    | ✓     | ✓    | g     | g   | ✓     | ✓        |  —   | g    | g      | g    |
| `theme`         | N    | ✓     | g    | ✓     | g   | g     | ✓        | g    | ✓    | g      | g    |

### Meta (`_meta.py`)

| Command    | json | Happy | Edge | Error | Adv | State | Contract | Prop | Regr | Stress | Perf |
|------------|------|-------|------|-------|-----|-------|----------|------|------|--------|------|
| `commands` | Y    | ✓     | ✓    | g     | g   | g     | ✓        |  —   | g    | g      | g    |
| `doctor`   | N    | ✓     | ✓    | g     | g   | ✓     | ✓        |  —   | ✓    | g      | g    |

### Events (`_events.py`)

| Command             | json | Happy | Edge | Error | Adv | State | Contract | Prop | Regr | Stress | Perf |
|---------------------|------|-------|------|-------|-----|-------|----------|------|------|--------|------|
| `on output`         | Y    | ✓     | ✓    | g     | g   | g     | ✓        | g    | ✓    | g      | g    |
| `on prompt`         | Y    | ✓     | g    | g     | g   | g     | ✓        | g    | g    | g      | g    |
| `on keystroke`      | Y    | ✓     | g    | ✓     | g   | g     | ✓        | g    | g    | g      | g    |
| `on session-new`    | Y    | ✓     | g    | g     | g   | g     | ✓        | g    | g    | g      | g    |
| `on session-end`    | Y    | ✓     | g    | g     | g   | g     | ✓        | g    | ✓    | g      | g    |
| `on focus`          | Y    | ✓     | g    | g     | g   | g     | ✓        | g    | ✓    | g      | g    |
| `on layout`         | Y    | ✓     | g    | g     | g   | g     | ✓        | g    | g    | g      | g    |
| `coprocess start`   | N    | s     | g    | ✓     | g   | g     | C        |  —   | g    | g      | g    |
| `coprocess stop`    | N    | s     | g    | ✓     | g   | g     | C        |  —   | g    | g      | g    |
| `coprocess list`    | N    | ✓     | g    | g     | g   | g     | C        |  —   | g    | g      | g    |
| `annotate`          | N    | ✓     | ✓    | ✓     | g   | g     | ✓        | g    | g    | g      | g    |
| `rpc`               | N    | g     | g    | ✓     | g   | g     | ✓        | g    | g    | g      | g    |

### Layouts (`_layouts.py`)

| Command         | json | Happy | Edge | Error | Adv | State | Contract | Prop | Regr | Stress | Perf |
|-----------------|------|-------|------|-------|-----|-------|----------|------|------|--------|------|
| `save`          | N    | ✓     | ✓    | ✓     | g   | ✓     | C        | g    | g    | g      | g    |
| `restore`       | N    | ✓     | ✓    | ✓     | g   | ✓     | C        | g    | g    | g      | g    |
| `layouts list`  | N    | ✓     | g    | g     | g   | g     | ✓        |  —   | ✓    | g      | g    |

### tmux (`_tmux.py`)

| Command             | json | Happy | Edge | Error | Adv | State | Contract | Prop | Regr | Stress | Perf |
|---------------------|------|-------|------|-------|-----|-------|----------|------|------|--------|------|
| `tmux start`        | N    | ✓     | g    | g     | g   | ✓     | C        |  —   | ✓    | g      | g    |
| `tmux stop`         | N    | g     | ✓    | g     | g   | g     | C        |  —   | g    | g      | g    |
| `tmux connections`  | Y    | ✓     | g    | g     | g   | g     | ✓        |  —   | g    | g      | g    |
| `tmux windows`      | Y    | ✓     | g    | g     | g   | g     | ✓        |  —   | ✓    | g      | g    |
| `tmux cmd`          | N    | ✓     | g    | ✓     | g   | g     | C        | g    | g    | g      | g    |
| `tmux visible`      | N    | g     | g    | ✓     | g   | g     | C        |  —   | g    | g      | g    |
| `tmux detach`       | N    | g     | g    | ✓     | g   | g     | C        |  —   | g    | g      | g    |
| `tmux kill-session` | N    | g     | g    | ✓     | g   | g     | C        |  —   | g    | g      | g    |

### Overview (`_overview.py`)

| Command    | json | Happy | Edge | Error | Adv | State | Contract | Prop | Regr | Stress | Perf |
|------------|------|-------|------|-------|-----|-------|----------|------|------|--------|------|
| `overview` | Y    | ✓     | ✓    | g     | g   | g     | ✓        | g    | g    | g      | g    |

---

## 8.2 Known gaps

Cells marked `g` above are not currently backed by a verifiable test-file mapping. Coverage may in fact exist in the command-specific integration test (e.g. `tests/test_tab.py`, `tests/test_window.py`, `tests/test_send.py`) but the §8 inventory was filled conservatively — only cells where the test-file → column mapping is direct and obvious are marked `✓`/`s`/`C`; everything else is tracked here as a documentation gap rather than a claim of test absence.

**File-to-column mapping (reference for future fills):**

- **Contract** column → `tests/test_contract_matrix.py` (parametrized over every command in `tests/_contract_categories.py`; rules 1/2/3/5 for all, rule 4 for mutators via `tests/test_invariant_mutators_honor_protection.py`).
- **Adv** column → `tests/test_adversarial.py`, `tests/test_adversarial_concurrency.py`, `tests/test_adversarial_malformed.py`, `tests/test_fault_injection.py`.
- **State** column → `tests/test_session_state.py`, `tests/test_send_state.py`, `tests/test_state_machine.py`, `tests/test_protection_lock.py`.
- **Prop** column → `tests/test_session_property.py`, `tests/test_send_state.py` (Hypothesis `@given` tests).
- **Regr** column → `tests/test_regression.py`, `tests/test_new_regressions.py`, `tests/test_smoke_149_152.py`, `tests/test_bugs.py`, issue-specific files (`test_focus_naming_342.py`, `test_inject_utf8_229.py`, `test_run_stdin_traversal_325.py`, `test_signals.py`, `test_resolver.py`, `test_window_safety.py`, `test_priority_30.py`, `test_create_race.py`, `test_snapshot.py`).
- **Stress** column → `tests/test_stress.py`, `tests/test_repaint_stress.py`, `tests/test_create_race.py`.
- **Perf** column → `tests/test_perf.py` (benchmark-gated; no per-command p50/p99 yet — every row is a real gap).
- **Happy/Edge/Error** columns → command-specific integration files named after the module (`test_session.py`, `test_tab.py`, `test_window.py`, `test_pane.py`, `test_send.py`, `test_output.py`, `test_query.py`, `test_stream.py`, `test_interactive.py`, `test_management.py`, `test_meta.py`, `test_events.py`, `test_tmux.py`, `test_layouts.py`, `test_layout.py`, `test_orientation.py`, `test_overview.py`, `test_config.py`, `test_broadcast.py`, `test_lock.py`, `test_stabilize.py`, plus `test_integration.py` for cross-module smoke).

**Most common gap patterns:**

- **Perf column: every command** — `tests/test_perf.py` has framework but no per-command coverage.
- **Stress column: nearly every command** — only `new`, `run` currently stress-covered.
- **Adv column: read-only and config commands** — adversarial work concentrated on `new`/`close`/`run`/`send`/`read`/`broadcast`.
- **State column: read-only commands** — by design (no state to assert); many of these `g` should probably be `—`.
- **Regr column: commands without a filed issue** — commands never regressed.
- **tmux subcommands** — whole module lacks happy-path tests for `tmux stop`, `tmux visible`, `tmux detach`, `tmux kill-session`.

Converting `g` to `✓`/`s` requires a single-pass verification of each command-specific test file; not done here to avoid unverified claims. Track as a follow-up: audit `test_tab.py`, `test_window.py`, `test_config.py` etc. for blank-cell fill candidates.

---

## 8.1 Mutation testing

**What it is.** Mutation testing automatically injects small code faults (e.g. flipping `>` to `>=`, deleting a `return`) and re-runs the suite. A mutant that survives — i.e. no test turns red — signals a test gap: the code changed but no assertion noticed.

**How to interpret results.** Survived mutants are weak-test signals, not bugs. Prioritise fixing tests around logic that is security- or correctness-critical; surviving mutants in logging or display code are low priority.

**Tooling.** `mutmut` is wired as an optional CI lane (`.github/workflows/ci.yml` job `mutation`). It targets `src/` and runs the fast suite (excludes `integration`, `stress`, `perf`, `fault_injection`). The cache is uploaded as a CI artifact so diffs can be compared between runs.

**Trigger.** `workflow_dispatch` only — run manually via GitHub Actions UI. Do not run on every push; a full mutation pass takes tens of minutes to hours depending on codebase size.

**Cadence.** Quarterly one-shot, or before a significant refactor. Review survived mutants, add targeted assertions, rerun to confirm kill rate improves.

**Local run (optional).** `uv run mutmut run --simple-output` then `uv run mutmut results`. Expect a long wait.

---

## 9. Contribution rules

1. **New command → all applicable matrix classes before merge.** Happy + at least one error + roundtrip/effect where meaningful + JSON schema if `--json` supported. Smoke-only is not acceptable.
2. **Bug fix → a `regression` test.** Name it `test_issue_<n>_...` and add `@pytest.mark.regression`.
3. **Adversarial finding → a new test tagged `adversarial` and, if it currently fails, also `known_broken` with the bug issue link in the docstring.** File the bug, don't just silence it.
4. **Every test uses a registered marker** (or none). `pytest --strict-markers` is enforced.
5. **Don't spin up sessions outside fixtures.** Use `session` / `shared_session` / (planned) `session_factory`.
6. **Update the §8 inventory** in the same PR that adds or removes a command. Drift is a review blocker.

---

## 10. Execution plan (from issue #136)

1. ✅ **Lead PR (this one)**: inventory, `docs/TESTING.md`, pyproject markers. No new tests.
2. **Parallel test-build wave**: one worktree agent per `src/_*.py` module, each fills its column of the matrix. This doc is the contract.
3. **Adversarial pass**: dedicated agent(s) write the "try to break it" layer using hypothesis + manual scenarios.
4. **Validation pass**: full suite vs main; tag flakes `xfail_flaky`; file bugs for real regressions; commit coverage report.
5. **Ongoing**: every PR adds its own regression test tagged with the issue/PR number.
