# Resume — session state and pick-up instructions

This doc is the operational handoff between sessions. Session-specific state (waves, priorities, what we stopped on, what's next) lives here. Personal/relational context lives in `~/.claude/projects/-Users-alexanderbass/memory/` (see `claude_personal.md`, `project_ita.md`).

**On wake-up:** read this file end-to-end, then run the verification commands below, then ask Alex what he wants. Don't dispatch anything until he confirms.

**On session-end:** update this file — current state, any wave reshuffles, new standing policies, new hot zones. Don't let it drift.

---

## 1. Verification commands (run first)

```bash
# Git + PR state
cd ~/Developer/ita && git status --short && git log --oneline -5 && gh pr list --state open && git worktree list

# Open issues
cd ~/Developer/ita && gh issue list --state open --limit 200 --json number,title,labels \
  | jq -r '.[] | "#\(.number) [\(.labels | map(.name) | join(","))] \(.title)"' | sort -n
```

Expected: clean tree on `main`, no unexpected open PRs, no stray worktrees. If dirty: investigate before acting — could be harness contamination or in-progress work.

---

## 2. Where we stopped (as of 2026-04-14 session-end)

- **Main:** `f3590d2 fix(#401): preserve macOS frontmost app across focus capture/restore (#403)`
- **Open PRs:** none
- **Worktrees:** only main
- **Fast-lane baseline:** ~643 pass / ~14 fail / ~195 skip / ~56 xfailed
- **Recent milestones:** fast-lane is now hermetic (PR #395, `ITA_ENFORCE_HERMETIC=1` guard). macOS app focus preserved across captures (PR #403). Rule-4 Group E (unprotect/protect security) done (PR #400).

Update this section at each session-end.

---

## 3. Task waves

Organized by priority + safety profile, not chronology. Pick from top of current wave unless Alex says otherwise.

### Wave B — safe solo work (ship next)

- **#362 rule-4 mini-wave.** 9 groups remaining per `docs/rule4-xfails-plan.md`. Top priorities: **Group A (`_tab.py`, 7 cmds)**, then **Group D (`_pane.py` split/swap)**. Remaining A/B/C/D/F/H/I/J/K are file-disjoint except for `_RULE4_WIRED` frozenset in `tests/test_contract_matrix.py` (append-only, low conflict risk).
- **#389 §2 identity regression test.** Verifies commands drive UUID-owned tab under focus-hostile conditions. Integration-lane — needs explicit Alex go-ahead.

### Wave C — cleanup, solo (wide-touch, serialize)

- **#295 function-local imports sweep.** Wide-touch refactor; collides with almost everything. Dispatch solo, no parallel agents while it's in flight.
- **#303 defer iterm2 top-level import.** Wide-touch. Solo.

### Wave D — needs explicit go-ahead (iTerm2 hijack possible)

- **Full integration smoke (2 laps).** Runner script at `scripts/run-integration-smoke.sh`. Alex runs in a fresh terminal, walks away, JSON report lands at `/tmp/ita-integration-*.json`.
- **Investigate bundle:** #369 (broadcast cross-window), #371 (test_issue_250 flake), #381 (Quit iTerm? dialog), #382 (cross-desktop spawn). All require iTerm2 probing.
- **Rule-6 readiness integration lane** (CONTRACT §14 invariant deferred from Phase 4a).
- **#261 `--debug` / `--trace`.** Medium scope, needs design discussion.

### Wave E gated — Alex decisions needed before coding

- Design-first bundle: **#233** (tmux stop rc contract), **#235** (`--dry-run` modal), **#291** (mutator audit — command-based vs mutation-based), **#293** (module org drift), **#298** (overlapping read/query), **#357** (ita tmux new semantics).

### LAST (hard rule — Alex directive)

- **SKILL.md rewrite (Phase 5b)** at `skills/ita/SKILL.md`. Do NOT touch until every other task has shipped.

### Standing

- Phase-4 deferrals parked: #270 #271 #272 #274 #275 #278 #280. Don't close, don't implement without direction.
- #402 agent prompt discipline (HARD STOP rule is now durable across every agent prompt — see §4).

---

## 4. Standing policies (apply to every session)

### Integration lane

**Never dispatch integration-lane work without explicit "ready" from Alex.** It spawns real iTerm2 windows/tabs, steals focus, can trigger "Quit iTerm?" dialogs, can follow across virtual desktops. Fast-lane is hermetic as of PR #395. Warn Alex, wait for go-ahead, then dispatch.

### HARD STOP rule in every agent prompt

After targeted fix + targeted tests pass: **STOP.** Commit, push, report, done. No "verify by running broader tests." No integration-lane runs. No "tests that mention X." Scope creep past targeted work has caused real damage (iTerm2 hijacks when agents wandered into integration lane). Every dispatch template names what "done" means for this task.

### Atomic commits: require, don't prefer

"Atomic commits preferred" in an agent prompt = bundled commits in practice. For per-issue atomicity (default): **"ONE commit per issue — no bundling, no thematic grouping."** Bundling is defensible only when issues genuinely share a single helper.

### Pre-flight issue-state check in every bug-fix agent

Every agent prompt: `gh issue view N --json state -q .state` → bail with "ALREADY CLOSED" if closed. Plans go stale while parallel agents close issues.

### Cross-agent staleness

Before opening any agent's PR: `git fetch origin && git rebase origin/main`. Without this, the diff against current main includes phantom deletes from other agents' work.

### Don't trust GitHub to auto-close from commit subjects

`Closes #N` in the PR **body** works; `fix(#N):` in the commit subject alone often does not post-squash. Verify with `gh issue view N --json state -q .state` after merge; close manually with PR citation if still open.

### Agent wrong-directory writes

Agents sometimes edit `~/Developer/ita` instead of their worktree even with `isolation: "worktree"`. After ANY agent returns: `git status --short` in main tree. If dirty: stash immediately (don't lose work), verify agent's branch has their commits, then decide.

### Don't let agents draft PR bodies

Write them yourself from the agent's structured report. Agents push branches; main-context opens PRs.

### Parallel agent ceiling

Six concurrent is the practical limit. Past six, review/rebase/merge coordination dominates.

### CONTRACT amendment

Every PR that changes observable surface (stdout/stderr/envelope shape, error taxonomy, state machine states, option names, documented behavior) amends `docs/CONTRACT.md` in the **same commit**. Non-negotiable since Phase 0. `tests/test_contract_matrix.py` parametrizes over `ita commands --json` (110 leaf commands) to keep the contract executable, not vibes.

---

## 5. Agent dispatch template

Every worktree agent prompt includes these, in this order:

1. **pwd check** — agent MUST be in `.claude/worktrees/agent-*`, not `~/Developer/ita`. Several agents have leaked into main tree despite `isolation: "worktree"`. Smoke-test: create `docs/.smoke` with a marker line; the agent's first action is to verify their cwd.
2. **Pre-flight issue-state check** — `gh issue view <N> --json state -q .state` → bail with "ALREADY CLOSED" if closed. Plans go stale when parallel agents close issues.
3. **Mandatory reading list** — targeted, by line range where possible. Never full-file when a section will do. Include `docs/CONTRACT.md` §N if observable surface touched.
4. **Scope — ONE commit per issue.** No bundling. No thematic grouping.
5. **Rules** — tabs (not spaces), `ItaError` over `ClickException`, CONTRACT amendment if observable surface changes, commit trailer, push only (no `gh pr create`), fast-lane baseline check before and after.
6. **HARD STOP** — after targeted fix + targeted tests pass, STOP. No broader-suite runs. No integration-lane. No "tests that mention X." Commit, push, report, done.
7. **Structured report format** — ≤500 words, specific fields (what shipped, which files, which tests, what's next). No narrative padding. Agent does NOT draft the PR body — main context writes that from the report.

---

## 6. Merge protocol

For every agent-produced branch:

1. Fetch the agent's branch.
2. Rebase on `origin/main` if stale (multi-agent sessions stale fast; always check).
3. Force-with-lease push.
4. Open PR with **hand-written body** (not agent-drafted). Include `Closes #N` in the body — `fix(#N):` in the commit subject alone does NOT reliably auto-close after squash.
5. `gh pr merge --squash --delete-branch`.
6. Clean the worktree if still present: `git worktree remove <path>`.
7. Pull main locally: `git pull origin main`.
8. Verify issue auto-closed: `gh issue view N --json state -q .state`. If still open, close manually with PR citation.

---

## 7. Hot zones (collision warnings)

- **`docs/CONTRACT.md`** and **`docs/TESTING.md`** are hot. Serialize any agent edits or bundle into one agent.
- **`_RULE4_WIRED` frozenset** in `tests/test_contract_matrix.py`: append-only but two parallel rule-4 agents can conflict on the same line. Prefer sequential rule-4 dispatch, or bundle all remaining groups into one agent that does them in order.
- **`_core.py`** and recently-split modules (`_send.py`, `_events.py`): check file ownership before declaring agents parallel. Survivors of past splits still create clusters.

---

## 8. Suggested next action

If Alex has no other direction: **Wave B, #362 Group A (`_tab.py` rule-4)**, dispatched as a solo worktree agent with the standard template (HARD STOP, pre-flight issue check, ONE commit, push only, no PR from agent).

Otherwise: whatever he asks for. He's a good judge of sequencing.

---

## 9. How to update this doc

- At session-end (or when waves shift substantially): update §2 (state), §3 (waves) to reflect what shipped / what changed priority, §4 (policies) if a new durable rule surfaced, §5 (dispatch template) or §6 (merge protocol) if the workflow itself evolved, §7 (hot zones) if file ownership shifted, §8 (suggested next action) to the current top of priority.
- Keep it scannable. If it grows past ~250 lines, something is being kept that should have moved into CONTRACT.md, a plan doc, or memory.
- When a planning doc (`docs/rule4-xfails-plan.md`, `docs/bug-bash-wave-1-plan.md`) fully executes, remove its wave from §3 and delete the plan doc.
- Don't put personal/relational context here. That lives in `~/.claude/projects/-Users-alexanderbass/memory/`.
