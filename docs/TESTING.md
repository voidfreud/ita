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

Legend per class cell: `✓` covered with real assertions, `s` smoke-only (rc=0), `—` not applicable, blank = TODO.

97 commands total; 30 support `--json`.

### Orientation (`_orientation.py`)

| Command        | json | Happy | Edge | Error | Adv | State | Contract | Prop | Regr | Stress | Perf |
|----------------|------|-------|------|-------|-----|-------|----------|------|------|--------|------|
| `status`       | Y    | ✓     | ✓    |       | ✓   |       | ✓        |  —   |      |        |      |
| `focus`        | Y    | ✓     |      |       |     |       | ✓        |  —   |      |        |      |
| `version`      | N    | ✓     |  —   |  —    |  —  |  —    |          |  —   |      |  —     |  —   |
| `protect`      | N    | ✓     |      | ✓     |     | ✓     |          |  —   |      |        |      |
| `unprotect`    | N    | ✓     |      |       |     | ✓     |          |  —   |      |        |      |
| `session info` | Y    | ✓     |      |       |     | ✓     | ✓        |      |      |        |      |

### Session (`_session.py`)

| Command   | json | Happy | Edge | Error | Adv | State | Contract | Prop | Regr | Stress | Perf |
|-----------|------|-------|------|-------|-----|-------|----------|------|------|--------|------|
| `new`     | Y    | ✓     | ✓    | ✓     | ✓   | ✓     | ✓        | ✓    | ✓    | ✓      |      |
| `close`   | N    | ✓     | ✓    | ✓     | ✓   | ✓     | ✓        | ✓    | ✓    |        |      |
| `activate`| N    | s     | ✓    | ✓     |     |       |          |  —   |      |        |      |
| `name`    | N    | ✓     | ✓    |       |     | ✓     | ✓        | ✓    |      |        |      |
| `restart` | N    | s     | ✓    | ✓     |     |       | ✓        |  —   | ✓    |        |      |
| `resize`  | N    | ✓     | ✓    | ✓     |     |       | ✓        | ✓    |      |        |      |
| `clear`   | N    | s     | ✓    |       |     |       | ✓        |  —   |      |        |      |
| `capture` | N    | ✓     | ✓    |       |     |       | ✓        |      |      |        |      |

### Send / run (`_send.py`)

| Command  | json | Happy | Edge | Error | Adv | State | Contract | Prop | Regr | Stress | Perf |
|----------|------|-------|------|-------|-----|-------|----------|------|------|--------|------|
| `run`    | Y    | ✓     | ✓    | ✓     | ✓   | ✓     | ✓        | ✓    | ✓    | ✓      |      |
| `send`   | N    | ✓     | ✓    |       | ✓   | ✓     | ✓        | ✓    |      |        |      |
| `inject` | N    | ✓     | ✓    | ✓     |     | ✓     | ✓        | ✓    | ✓    |        |      |
| `key`    | N    | ✓     | ✓    | ✓     |     |       | ✓        | ✓    |      |        |      |

### Output / query (`_output.py`, `_query.py`, `_stream.py`)

| Command       | json | Happy | Edge | Error | Adv | State | Contract | Prop | Regr | Stress | Perf |
|---------------|------|-------|------|-------|-----|-------|----------|------|------|--------|------|
| `read`        | N    | ✓     | ✓    | ✓     | ✓   |       | ✓        | ✓    |      |        |      |
| `wait`        | Y    | ✓     |      | ✓     |     |       | ✓        |      |      |        |      |
| `selection`   | Y    | ✓     |      |       |     |       | ✓        |      |      |        |      |
| `copy`        | N    | s     |      | ✓     |     |       |          |  —   |      |        |      |
| `get-prompt`  | Y    | ✓     |      | ✓     |     |       | ✓        |  —   |      |        |      |
| `watch`       | Y    | ✓     | ✓    | ✓     |     |       | ✓        |      | ✓    |        |      |

### Lock (`_lock.py`)

| Command  | json | Happy | Edge | Error | Adv | State | Contract | Prop | Regr | Stress | Perf |
|----------|------|-------|------|-------|-----|-------|----------|------|------|--------|------|
| `lock`   | N    | ✓     |      | ✓     |     | ✓     |          |  —   |      |        |      |
| `unlock` | N    | ✓     |      | ✓     |     | ✓     | ✓        |  —   |      |        |      |

### Tab (`_tab.py`)

| Command        | json | Happy | Edge | Error | Adv | State | Contract | Prop | Regr | Stress | Perf |
|----------------|------|-------|------|-------|-----|-------|----------|------|------|--------|------|
| `tab new`      | N    | ✓     | ✓    | ✓     |     |       |          |  —   |      |        |      |
| `tab close`    | N    | ✓     |      | ✓     |     | ✓     |          |  —   |      |        |      |
| `tab activate` | N    |       |      | ✓     |     |       |          |  —   |      |        |      |
| `tab next`     | N    | ✓     |      |       |     | ✓     |          |  —   | ✓    |        |      |
| `tab prev`     | N    | ✓     |      |       |     |       |          |  —   | ✓    |        |      |
| `tab goto`     | Y    | ✓     | ✓    | ✓     |     |       |          |      |      |        |      |
| `tab list`     | Y    | ✓     |      |       |     |       | ✓        |  —   |      |        |      |
| `tab info`     | Y    | ✓     |      | ✓     |     |       | ✓        |      |      |        |      |
| `tab detach`   | N    | ✓     |      | ✓     |     |       |          |  —   |      |        |      |
| `tab move`     | N    |       |      |       |     |       |          |      |      |        |      |
| `tab profile`  | N    |       |      | ✓     |     |       |          |      |      |        |      |
| `tab title`    | N    | ✓     | ✓    |       |     | ✓     |          | ✓    |      |        |      |

### Window (`_layout.py`)

| Command              | json | Happy | Edge | Error | Adv | State | Contract | Prop | Regr | Stress | Perf |
|----------------------|------|-------|------|-------|-----|-------|----------|------|------|--------|------|
| `window new`         | N    | ✓     |      | ✓     |     |       |          |  —   |      |        |      |
| `window close`       | N    | ✓     | ✓    | ✓     |     | ✓     | ✓        |  —   |      |        |      |
| `window activate`    | N    | ✓     |      | ✓     |     |       |          |  —   |      |        |      |
| `window title`       | N    | ✓     | ✓    |       |     | ✓     |          | ✓    |      |        |      |
| `window fullscreen`  | N    | ✓     |      | ✓     |     | ✓     |          |  —   |      |        |      |
| `window frame`       | N    | ✓     | ✓    |       |     | ✓     |          | ✓    |      |        |      |
| `window list`        | Y    | ✓     |      |       |     |       | ✓        |  —   |      |        |      |

### Pane (`_pane.py`)

| Command | json | Happy | Edge | Error | Adv | State | Contract | Prop | Regr | Stress | Perf |
|---------|------|-------|------|-------|-----|-------|----------|------|------|--------|------|
| `split` | N    | ✓     | ✓    | ✓     |     | ✓     | ✓        |      |      |        |      |
| `pane`  | N    | ✓     |      | ✓     |     |       |          |      |      |        |      |
| `move`  | N    |       |      | ✓     |     | ✓     |          |      | ✓    |        |      |
| `swap`  | N    |       |      | ✓     |     | ✓     |          | ✓    |      |        |      |

### Config (`_config.py`)

| Command          | json | Happy | Edge | Error | Adv | State | Contract | Prop | Regr | Stress | Perf |
|------------------|------|-------|------|-------|-----|-------|----------|------|------|--------|------|
| `var get`        | Y    | ✓     | ✓    | ✓     |     | ✓     |          | ✓    | ✓    |        |      |
| `var set`        | Y    | ✓     | ✓    |       |     | ✓     |          | ✓    |      |        |      |
| `var list`       | Y    | ✓     |      |       |     |       | ✓        |  —   |      |        |      |
| `app version`    | N    | s     |      |       |     |       |          |  —   |      |        |      |
| `app activate`   | N    | ✓     |      |       |     |       |          |  —   |      |        |      |
| `app hide`       | N    | ✓     |      |       |     |       |          |  —   |      |        |      |
| `app quit`       | N    |       |      |       |     |       |          |  —   |      |        |      |
| `app theme`      | N    | ✓     |      |       |     |       |          |      |      |        |      |
| `pref get`       | N    | ✓     |      | ✓     |     |       |          |      |      |        |      |
| `pref set`       | Y    | ✓     | ✓    |       |     | ✓     | ✓        |      |      |        |      |
| `pref list`      | Y    | ✓     |      |       |     |       |          |  —   |      |        |      |
| `pref theme`     | N    | ✓     |      |       |     |       |          |      |      |        |      |
| `pref tmux`      | N    | ✓     |      | ✓     |     |       |          |      |      |        |      |
| `broadcast on`   | N    | ✓     |      | ✓     | ✓   | ✓     |          |  —   |      |        |      |
| `broadcast send` | N    | ✓     |      | ✓     | ✓   |       |          |      |      |        |      |
| `broadcast off`  | N    | ✓     |      |       |     | ✓     |          |  —   |      |        |      |
| `broadcast add`  | N    | ✓     |      | ✓     |     | ✓     |          |      |      |        |      |
| `broadcast set`  | N    | ✓     |      | ✓     |     | ✓     |          |      |      |        |      |
| `broadcast list` | Y    | ✓     |      |       |     |       | ✓        |  —   |      |        |      |

### Interactive (`_interactive.py`)

| Command       | json | Happy | Edge | Error | Adv | State | Contract | Prop | Regr | Stress | Perf |
|---------------|------|-------|------|-------|-----|-------|----------|------|------|--------|------|
| `alert`       | N    | ✓     | ✓    | ✓     |     |       | ✓        |  —   |      |        |      |
| `ask`         | N    | ✓     | ✓    | ✓     |     |       | ✓        |      |      |        |      |
| `pick`        | N    | ✓     | ✓    |       |     |       | ✓        |      |      |        |      |
| `save-dialog` | N    | ✓     | ✓    |       |     |       | ✓        |      |      |        |      |
| `menu list`   | Y    | ✓     | ✓    |       |     |       | ✓        |  —   |      |        |      |
| `menu select` | N    |       |      | ✓     |     |       |          |      |      |        |      |
| `menu state`  | Y    | ✓     |      | ✓     |     |       | ✓        | ✓    |      |        |      |
| `repl`        | N    | ✓     | ✓    | ✓     |     |       | ✓        |  —   |      |        |      |

### Management (`_management.py`)

| Command         | json | Happy | Edge | Error | Adv | State | Contract | Prop | Regr | Stress | Perf |
|-----------------|------|-------|------|-------|-----|-------|----------|------|------|--------|------|
| `profile list`  | Y    | ✓     | ✓    |       |     |       | ✓        |  —   |      |        |      |
| `profile show`  | N    | ✓     |      | ✓     |     | ✓     | ✓        |      |      |        |      |
| `profile get`   | N    | ✓     |      |       |     |       |          |      |      |        |      |
| `profile apply` | N    |       |      | ✓     |     | ✓     |          |      |      |        |      |
| `profile set`   | N    | ✓     |      | ✓     |     | ✓     |          | ✓    | ✓    |        |      |
| `presets`       | Y    | ✓     | ✓    |       |     | ✓     | ✓        |  —   |      |        |      |
| `theme`         | N    | ✓     |      | ✓     |     |       | ✓        |      | ✓    |        |      |

### Meta (`_meta.py`)

| Command    | json | Happy | Edge | Error | Adv | State | Contract | Prop | Regr | Stress | Perf |
|------------|------|-------|------|-------|-----|-------|----------|------|------|--------|------|
| `commands` | Y    | ✓     | ✓    |       |     |       | ✓        |  —   |      |        |      |
| `doctor`   | N    | ✓     | ✓    |       |     | ✓     | ✓        |  —   | ✓    |        |      |

### Events (`_events.py`)

| Command             | json | Happy | Edge | Error | Adv | State | Contract | Prop | Regr | Stress | Perf |
|---------------------|------|-------|------|-------|-----|-------|----------|------|------|--------|------|
| `on output`         | Y    | ✓     | ✓    |       |     |       | ✓        |      | ✓    |        |      |
| `on prompt`         | Y    | ✓     |      |       |     |       | ✓        |      |      |        |      |
| `on keystroke`      | Y    | ✓     |      | ✓     |     |       | ✓        |      |      |        |      |
| `on session-new`    | Y    | ✓     |      |       |     |       | ✓        |      |      |        |      |
| `on session-end`    | Y    | ✓     |      |       |     |       | ✓        |      | ✓    |        |      |
| `on focus`          | Y    | ✓     |      |       |     |       | ✓        |      | ✓    |        |      |
| `on layout`         | Y    | ✓     |      |       |     |       | ✓        |      |      |        |      |
| `coprocess start`   | N    | s     |      | ✓     |     |       |          |  —   |      |        |      |
| `coprocess stop`    | N    | s     |      | ✓     |     |       |          |  —   |      |        |      |
| `coprocess list`    | N    | ✓     |      |       |     |       |          |  —   |      |        |      |
| `annotate`          | N    | ✓     | ✓    | ✓     |     |       | ✓        |      |      |        |      |
| `rpc`               | N    |       |      | ✓     |     |       | ✓        |      |      |        |      |

### Layouts (`_layouts.py`)

| Command         | json | Happy | Edge | Error | Adv | State | Contract | Prop | Regr | Stress | Perf |
|-----------------|------|-------|------|-------|-----|-------|----------|------|------|--------|------|
| `save`          | N    | ✓     | ✓    | ✓     |     | ✓     |          |      |      |        |      |
| `restore`       | N    | ✓     | ✓    | ✓     |     | ✓     |          |      |      |        |      |
| `layouts list`  | N    | ✓     |      |       |     |       | ✓        |  —   | ✓    |        |      |

### tmux (`_tmux.py`)

| Command             | json | Happy | Edge | Error | Adv | State | Contract | Prop | Regr | Stress | Perf |
|---------------------|------|-------|------|-------|-----|-------|----------|------|------|--------|------|
| `tmux start`        | N    | ✓     |      |       |     | ✓     |          |  —   | ✓    |        |      |
| `tmux stop`         | N    |       | ✓    |       |     |       |          |  —   |      |        |      |
| `tmux connections`  | Y    | ✓     |      |       |     |       | ✓        |  —   |      |        |      |
| `tmux windows`      | Y    | ✓     |      |       |     |       | ✓        |  —   | ✓    |        |      |
| `tmux cmd`          | N    | ✓     |      | ✓     |     |       |          |      |      |        |      |
| `tmux visible`      | N    |       |      | ✓     |     |       |          |  —   |      |        |      |
| `tmux detach`       | N    |       |      | ✓     |     |       |          |  —   |      |        |      |
| `tmux kill-session` | N    |       |      | ✓     |     |       |          |  —   |      |        |      |

### Overview (`_overview.py`)

| Command    | json | Happy | Edge | Error | Adv | State | Contract | Prop | Regr | Stress | Perf |
|------------|------|-------|------|-------|-----|-------|----------|------|------|--------|------|
| `overview` | Y    | ✓     | ✓    |       |     |       | ✓        |      |      |        |      |

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
