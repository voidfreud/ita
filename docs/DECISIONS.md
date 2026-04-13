# DECISIONS

One-liner digest of closed issues that encoded an architectural decision. The ita repo is the source of truth for current behaviour; this file is here so future contributors (human or agent) don't re-litigate choices that were already made with reasons.

Rules:
- One line per decision. Link to the originating issue. Cite the governing `docs/CONTRACT.md` section.
- Only closed issues where a **decision** was made get entries. Pure bug fixes without architectural lesson are skipped — `git log` is authoritative for those.
- Ordered by issue number (descending = newest first).
- To revisit any decision: open an RFC issue referencing this file and the governing CONTRACT section.

---

## Entries

- **#332** (merged 2026-04-13): PR adopting `docs/CONTRACT.md` — [CONTRACT.md §1–§16](CONTRACT.md).
- **#282**: write lock must be keyed on `(session_id, pid, cookie)`, never on `getppid()`. Same-parent invocations otherwise shared ownership. → [§10](CONTRACT.md#10-protection--locking).
- **#268**: `wait_until_ready()` / `stabilize` is the canonical readiness primitive. Promoted into the contract. → [§8](CONTRACT.md#8-readiness).
- **#259**: `docs/CONTRACT.md` adopted as the executable north-star; every subsequent PR amends it. → [§1](CONTRACT.md#1-audience--non-goals).
- **#250**: `ita new` (and peers) must not return before shell metadata is stable. No `--no-wait` as the default. → [§8](CONTRACT.md#8-readiness).
- **#246**: destructive commands go through `confirm_or_skip`. No interactive prompt unless `--confirm`; agent callers pass `-y`. → [§12](CONTRACT.md#12-confirmation).
- **#236**: write lock is per-session, never per-app. Bulk operations must acquire per-target. → [§10](CONTRACT.md#10-protection--locking), [§13](CONTRACT.md#13-bulk-op-semantics).
- **#227**: parent-PID ownership for unlock is forbidden. Replaced by `(session_id, pid, cookie)` tuple check. → [§10](CONTRACT.md#10-protection--locking).
- **#218**: every mutator must call `check_protected()` *before* acquiring the lock. → [§10](CONTRACT.md#10-protection--locking).
- **#133**: no implicit "current session" anywhere. `ita use`, `~/.ita_context`, and all focus-fallback logic deleted. → [§2](CONTRACT.md#2-identity--resolution).

<!-- Append new entries at the top of this list, keeping the format above. -->
