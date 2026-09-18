# GridWise — Code Review Log

Running record of `/code-review` findings. Every entry below is a separate review pass. Each pass starts by
re-checking every open finding from the previous pass (still present / fixed / superseded), then lists anything new.
This file is a review log, not a task tracker — the authoritative build status stays in
[IMPLEMENTATION_TRACKER.md](IMPLEMENTATION_TRACKER.md).

## How to read this file

- Findings are numbered `R<review>-<n>` (review pass, ordinal within that pass) and keep that ID forever, even
  across passes, so they can be cross-referenced.
- **Status** values: `OPEN` (not fixed), `FIXED` (verified fixed in a later pass), `WONTFIX` (deliberately not
  fixed, with a reason), `STALE` (the surrounding code changed enough that the finding no longer applies).
- Each pass has a **Carried over from previous passes** subsection reporting the fate of every prior open finding,
  and a **New findings** subsection for anything found for the first time.

---

## Review 1 — 2026-09-18 (after P3, directive compiler)

Scope: full-repo `/code-review` at the point `aa526c3` (P3 — directive compiler) was the latest commit.

### Carried over from previous passes

None — this is the first review pass.

### New findings

#### R1-1 — `compile_directives()` and `derive_envelope()` disagree under `SOLAR_OVERLAP_POLICY=last_wins`

- **Status:** FIXED — fix verified present by direct inspection 2026-09-18 (see "Verification log" below).
  Not yet re-confirmed by a full `/code-review` pass; Review 2 should still re-check it.
- **File:** [app/optimizer/compile_directives.py:250](app/optimizer/compile_directives.py#L250) (compiler side),
  `app/validation/replay.py:132` (`derive_envelope()`, replay side)
- **Severity:** High — undermines the P2/P3 independence guarantee documented in `IMPLEMENTATION_TRACKER.md` D-09
  and verified in the README's P3 section ("the compiler and P2's independently-written `derive_envelope()` agree
  on all five constraint arrays across all 44 reference cases").
- **Summary:** `compile_directives()` sorts directives by `note_index` before resolving overlapping
  `solar_reduction` factors (`sorted(directives, key=lambda item: item.note_index)` at line 105 →
  the overlap-resolution logic around line 250). `derive_envelope()` in `replay.py` iterates the directive list in
  whatever order it was given, with no sort. Under `SOLAR_OVERLAP_POLICY=last_wins`, "last" means something
  different to each function — last by `note_index` vs. last by list position — so they can resolve to different
  `effective_solar` values for the same input.
- **Failure scenario:** Two `solar_reduction` directives on hour 10 — `note_index=0` factor `0.8`,
  `note_index=1` factor `0.3` — supplied to both functions in reverse list order `[note_index=1, note_index=0]`.
  With `SOLAR_OVERLAP_POLICY=last_wins`: `compile_directives()` (sorts by `note_index` first) resolves to factor
  `0.3`; `derive_envelope()` (trusts list order) resolves to factor `0.8`. Reproduced empirically:
  `effective_solar[10] = 39.0` (compiler) vs. `104.0` (replay). The existing test suite does not catch this because
  it only exercises the order-independent default policy (`MIN_FACTOR`). Once P4+ wires these into the live
  pipeline, a directive list that reaches `replay()` in a different order than it reached the compiler would either
  cause a false `ReplayInvariantFailure` (500) on a valid plan, or — worse — silently disagree in a way the
  cross-check test suite does not exercise.
- **Suggested fix:** Make both functions sort by the same key before resolving `last_wins` (or make `last_wins`
  itself order-independent by defining "last" as "highest `note_index`" everywhere), then add a `last_wins`-policy
  fixture with directives supplied out of order to the P2/P3 agreement test suite.
- **Fix applied (P6 session, 2026-09-18), pending verification in the next review pass:** `derive_envelope()` in
  `app/validation/replay.py` now iterates `sorted(directives, key=note_index)`, matching the compiler, so "last"
  means "highest `note_index`" in both. Regression test
  `test_compiler_and_replay_agree_under_an_order_sensitive_policy` supplies the reported directives in both orders
  under `SOLAR_OVERLAP_POLICY=last_wins` and asserts agreement. The reported failure was reproduced beforehand
  (39.0 vs 104.0) and no longer occurs.

#### R1-2 — Dead `elif` branch in `expand_window()`

- **Status:** FIXED — fix verified present by direct inspection 2026-09-18 (see "Verification log" below).
  Not yet re-confirmed by a full `/code-review` pass; Review 2 should still re-check it.
- **File:** [app/policies/spec_gaps.py:499](app/policies/spec_gaps.py#L499)
- **Severity:** Low — cosmetic/maintainability only, no behavioral impact.
- **Summary:** The `elif end_hour == HOURS_IN_DAY:` branch can never execute: `end_hour == HOURS_IN_DAY` (24) only
  arises when `start_hour <= 23`, which always satisfies the preceding `if end_hour > start_hour` check. It is
  exercised by test case `(22, 24, [22, 23])`, but that test passes through the `if` branch, not the `elif` —
  the `elif` is unreachable.
- **Failure scenario:** Not a runtime bug. The risk is purely to future maintainers: the branch reads as
  load-bearing logic for the cross-midnight / inclusive-end provisional policies, so the next person to touch this
  function may reasonably assume it does something and be misled while debugging or extending it.
- **Suggested fix:** Delete the dead branch, or replace it with a comment/assertion documenting why it is
  structurally unreachable if it's being kept as a guard against a future refactor.
- **Fix applied (P6 session, 2026-09-18), pending verification in the next review pass:** the unreachable
  `elif end_hour == HOURS_IN_DAY:` branch was deleted from `expand_window()` and replaced with a comment explaining
  why `end_hour == 24` is already covered by the forward case. The `(22, 24, [22, 23])` test still passes.

---

## Verification log

Records confirmations made **outside** a full review pass. These are targeted checks of a specific claim, not a
re-review of the codebase, and they never substitute for the next pass re-checking the finding itself.

### 2026-09-18 — R1-1 and R1-2 confirmed fixed in the working tree

Both fixes were applied during the P6 session and annotated above as *fix applied, pending verification*. Both are
now confirmed present in the committed code by direct inspection:

| Finding | Evidence |
|---|---|
| R1-1 | `app/validation/replay.py:136` — `derive_envelope()` now iterates `sorted(directives, key=lambda item: item.note_index)`, matching the compiler's ordering, with an explanatory comment at line 132. "Last" now means "highest `note_index`" on both sides, so the resolution is order-independent. |
| R1-2 | `app/policies/spec_gaps.py:88-91` — the unreachable `elif end_hour == HOURS_IN_DAY:` branch is gone; a comment explains that `end_hour == 24` is always covered by the ordinary forward case, since `start_hour <= 23`. |

Suite state at the time of this check: **174 tests passing** (`python -m pytest`, 9.35 s, zero failures).

> `ruff check .` was **not** verified in this check — `ruff` is not installed on either interpreter available in
> this environment (Python 3.14 or 3.12), despite `IMPLEMENTATION_TRACKER.md` §1 listing it as present. The
> tracker's "ruff clean" claim for P5/P6 is carried over unverified. Install `requirements-dev.txt` before relying
> on it, and before the P19 CI phase makes it a gate.

---

## Unreviewed scope

Review 1 covered the repository at commit `aa526c3` (P3 — directive compiler). Three feature commits have landed
since and **have never been through a review pass**:

| Commit | Phase | Principal new code |
|---|---|---|
| `58821e8` | P4 — shared LP/MILP model | `app/optimizer/model.py` |
| `fedb14c` | P5 — solvers | `app/optimizer/lp_relaxation.py`, `milp_solver.py`, `hybrid_solve.py` |
| `a715c42` | P6 — response builder | `app/optimizer/result.py`, `app/services/plan_summary.py`, rewritten `app/services/optimize_service.py` |

This is the highest-value surface for Review 2: it contains the numerically delicate code (the rounding/precision
ladder in `optimize_service.py`, the derive-don't-copy rules in `result.py`) and the three-way failure-class
mapping in `hybrid_solve.py` that decides whether a bad request becomes a 422 or a 500.

---

## Next review

When `/code-review` is next run, append a **Review 2** section above this line following the same structure:
re-check R1-1 and R1-2 first (confirm the `FIXED` status above, or reopen), then list anything new as `R2-*`.
Prioritize the unreviewed P4–P6 code listed in the section above.
