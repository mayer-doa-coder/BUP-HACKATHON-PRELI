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

## Review 2 — 2026-09-18 (after P4–P6: shared model, solvers, response builder)

Scope: the three commits flagged as "Unreviewed scope" after Review 1 — `58821e8` (P4, `app/optimizer/model.py`),
`fedb14c` (P5, `lp_relaxation.py`/`milp_solver.py`/`hybrid_solve.py`), `a715c42` (P6, `result.py`,
`plan_summary.py`, the rewritten `optimize_service.py`) — plus everything else in the diff since `aa526c3`
(guardrails, LLM interpreter/providers/repair, which did not exist at Review 1 and so were also unreviewed).

Method: 8 parallel finder-angle agents (reuse, simplification, altitude/mechanism-generality, efficiency,
removed-behavior audit, CLAUDE.md-conventions audit, cross-file tracer, line-by-line diff scan) independently
combed the diff and reported 20+ raw candidates. Several were found by more than one angle independently — treated
here as higher-confidence. The highest-severity and multiply-corroborated claims were then re-verified directly
(file reads / greps against the current tree, not the diff) before being written up below; that direct-inspection
evidence is cited inline. Lower-priority findings that were not independently re-verified this pass are marked as
such and should be spot-checked before being trusted at the same level as the verified ones.

### Carried over from previous passes

| Finding | Prior status | This pass | Evidence |
|---|---|---|---|
| R1-1 (compiler/replay solar-overlap ordering) | FIXED, pending re-confirmation | **Re-confirmed FIXED** | The removed-behavior-audit agent independently read `app/validation/replay.py` end to end this pass and confirmed `derive_envelope()` sorts by `note_index` before resolving overlaps, calling the change "a bug fix, not a regression," backed by `test_compiler_and_replay_agree_under_an_order_sensitive_policy`. |
| R1-2 (dead `elif` in `expand_window()`) | FIXED, pending re-confirmation | **Re-confirmed FIXED** | Same agent independently confirmed the unreachable branch is gone and traced the removal to a genuine dead-code deletion, not a behavior change. |

Both are now fully confirmed across two independent passes and can be treated as closed unless a future change to
`compile_directives.py`, `replay.py`, or `spec_gaps.py` reopens them.

### New findings — verified by direct inspection

#### R2-1 — A misconfigured backup LLM provider crashes the whole app at import time

- **Status:** OPEN — confirmed by direct inspection.
- **File:** [app/llm/providers/__init__.py:79](app/llm/providers/__init__.py#L79) (`_build` raises
  `ProviderNotConfigured`), [app/llm/repair.py:296](app/llm/repair.py#L296) (`build_runner` calls
  `build_backup_provider` unguarded), [app/services/optimize_service.py:61](app/services/optimize_service.py#L61)
  (`OptimizeService.__init__` calls `build_runner` synchronously), [app/api/routes.py:19](app/api/routes.py#L19)
  (`_service = OptimizeService()` at **module import time**).
- **Severity:** Critical — violates CLAUDE.md's "Fail closed; never crash," and takes `/health` down with it,
  which CLAUDE.md and the release gates treat as the one endpoint that must never depend on provider config.
- **Summary:** `app/llm/interpreter.py:159-162` wraps `build_provider(settings)` in
  `try/except ProviderNotConfigured: return None`, so a misconfigured **primary** provider degrades gracefully — the
  module's own docstring says exactly this is the point ("the factory returns `None` rather than raising ... so the
  service can start [and] answer `/health`"). `build_runner()` in `repair.py` does not apply the same guard to the
  **backup** provider: it calls `build_backup_provider(settings)` directly (line 296), and `_build()` raises
  `ProviderNotConfigured` whenever `provider_name` doesn't match `OPENAI_ALIASES`/`ANTHROPIC_ALIASES`. Since
  `_service = OptimizeService()` runs at module import time, this exception propagates out of the import itself.
- **Failure scenario:** Operator sets `BACKUP_LLM_PROVIDER` to a typo'd or unsupported value (e.g. `openai-compat`
  instead of `openai_compatible`) while also populating `BACKUP_LLM_MODEL`/`BACKUP_LLM_API_KEY`, intending a
  graceful backup. Instead of degrading to "no backup," the container fails to import `app.api.routes` and never
  starts — not even `/health` comes up.
- **Suggested fix:** Wrap the `build_backup_provider(settings)` call in `repair.py:296` in the same
  `try/except ProviderNotConfigured: backup_provider = None` pattern `interpreter.py` already uses for the primary
  provider, and add a regression test that sets an invalid `BACKUP_LLM_PROVIDER` and asserts the app still imports
  and `/health` still returns 200.
- *(Independently found by two finder-angle agents — Angle A "line-by-line diff scan" and Angle C "cross-file
  tracer" — reaching the same file:line pair by different methods.)*

#### R2-2 — The precision ladder aborts on the first `SolverFailure` instead of retrying at finer precision

- **Status:** OPEN — confirmed by direct inspection.
- **File:** [app/services/optimize_service.py:248-254](app/services/optimize_service.py#L248-L254)
  (`_build_validated_response`), raised from [app/optimizer/result.py](app/optimizer/result.py) lines 78, 120, 148,
  153, 165 (`_fit_to_bound`, `_reject_banned_activity`, the simultaneous charge+discharge check).
- **Severity:** High — directly contradicts the method's own documented purpose.
- **Summary:** `_build_validated_response`'s docstring states: "Rather than fail such a request, the plan is
  rebuilt at finer precision and finally at full precision." The loop only handles a `replay()` failure
  (`report.ok is False`) by moving to the next rung; it has no `try/except` around
  `candidate = self._assemble(request, directives, outcome, decimals=decimals)` (line 249), which calls
  `build_hourly_plan()` → `_fit_to_bound()`/`_reject_banned_activity()`, and those raise `SolverFailure` directly —
  not a status the loop can inspect — whenever coarse rounding pushes a value past its bound by more than
  `BOUND_REPAIR_TOLERANCE` (1e-6). That exception propagates out of the loop immediately, so the `coarse+3` and
  `None` (full-precision) rungs the ladder exists to reach are never attempted.
- **Failure scenario:** A scenario whose true optimal MILP solution has a charge value that, once rounded to
  `response_decimal_places` (the coarse rung), lands just over `max_charge_kwh_per_hour` by more than 1e-6 — the
  request fails closed with a 500 `SolverFailure`, and thus **zero optimization credit** for that case, even though
  the unrounded (`decimals=None`) solution is perfectly valid and would have passed at a finer rung.
- **Suggested fix:** Catch `SolverFailure` inside the loop (alongside the existing `report.ok` check) and continue
  to the next precision rung instead of letting it propagate; only re-raise after the last rung is exhausted. Add a
  fixture that forces a coarse-rounding bound overshoot and asserts the ladder recovers at a finer rung.
- *(Independently found by two finder-angle agents — Angle A and Angle C — from different starting points: Angle A
  via the missing `try/except`, Angle C via tracing the ladder's documented intent against its implementation.)*

#### R2-3 — `DirectiveInfeasible` inherits HTTP 500 instead of a plausible 422, and the tracker's "until P10 lands" caveat was never revisited after P10 landed

- **Status:** OPEN — confirmed by direct inspection. Policy question, not obviously a bug — see below.
- **File:** [app/api/errors.py:84](app/api/errors.py#L84) (`DirectiveInfeasible`, no `http_status` override — unlike
  `SemanticallyInvalidRequest` at line 65, which sets `http_status = 422`),
  [app/services/optimize_service.py:220-226](app/services/optimize_service.py#L220-L226) (raise site).
- **Severity:** High — potential direct rubric cost on the "API contract" scoring category if the organizer's
  hidden harness expects 422 here.
- **Summary:** `DirectiveInfeasible` — raised when the interpreted directives make the LP relaxation infeasible even
  after the one bounded P10 feasibility reparse — has no `http_status` class attribute, so it inherits
  `GridWiseError.http_status = 500`. Its own docstring calls it "distinct from a solver fault," which reads as
  intending the 422 bucket (valid, well-formed request that just can't be scheduled as interpreted) rather than the
  500 bucket CLAUDE.md defines for "LLM-unusable after budget, solver failure, replay failure." Confirmed via
  `IMPLEMENTATION_TRACKER.md` that this was a deliberate **provisional** choice, explicitly annotated "500 until
  P10's reparse lands" — and P10 (the reinterpretation retry in `app/llm/repair.py`) is now implemented in this
  same diff, but the status code was never revisited against that original caveat.
- **Failure scenario:** An operator note is correctly interpreted (e.g. `max_grid_window` with `max_grid_kwh: 0.0`
  on a high-demand, low-solar night hour), the scenario is baseline-schedulable, but that specific reading is
  unschedulable even after the one reparse attempt. The judge harness receives an opaque 500 for what may be, per
  the organizer's own rubric wording, a "cross-field semantic invalidity" case expecting 422.
- **Suggested fix:** This needs an organizer-mapping decision, not a unilateral change — but at minimum, revisit
  the tracker's stale "until P10 lands" note now that P10 exists, decide 422 vs. 500 deliberately, and add an
  integration test asserting the resulting HTTP status end-to-end (today only the exception *class* is asserted,
  never the status code that reaches the client).
- *(Independently found by **three** finder-angle agents — Angle B "removed-behavior audit," Angle C "cross-file
  tracer," and Angle A "line-by-line diff scan" — the strongest corroboration of any finding in this pass.)*

#### R2-4 — The baseline feasibility screen conflates a solver malfunction with genuine infeasibility, returning 422 instead of 500

- **Status:** OPEN — confirmed by direct inspection.
- **File:** [app/optimizer/hybrid_solve.py:94](app/optimizer/hybrid_solve.py#L94) (`screen_baseline_feasibility`),
  [app/services/optimize_service.py:122-127](app/services/optimize_service.py#L122-L127) (`screen_feasibility`,
  raises `SemanticallyInvalidRequest` → 422). Contrast with the *same file*'s directive-constrained path at
  [hybrid_solve.py:109,117](app/optimizer/hybrid_solve.py#L109-L117), which correctly separates `lp.is_infeasible`
  (→ `DIRECTIVE_INFEASIBLE`) from `not lp.is_optimal` more broadly (→ `SOLVER_FAILURE`, 500).
- **Severity:** High — a real solver malfunction (HiGHS iteration limit, internal error, unbounded LP) on a
  schedulable scenario is reported to the client as "this scenario cannot be scheduled" (422) — a false,
  judge-visible claim about the request — instead of a controlled 500, and it happens *before* any LLM call, so it
  can never benefit from the retry/backup-provider logic that exists for the post-directive path.
- **Summary:** `screen_baseline_feasibility` returns `BaselineScreen(feasible=lp.is_optimal, lp=lp)` — `feasible` is
  only `True` for `LpStatus.OPTIMAL`, so `LpStatus.ERROR`, `LpStatus.LIMIT`, and `LpStatus.UNBOUNDED` are all folded
  into `feasible=False` exactly like genuine infeasibility. `screen_feasibility()` then unconditionally raises
  `SemanticallyInvalidRequest` (422) whenever `not screen.feasible`.
- **Failure scenario:** HiGHS hits its iteration limit or throws on the (directive-free) baseline LP for a scenario
  that is actually schedulable — the client gets 422 "scenario cannot be scheduled," not 500 "solver failure." No
  test in the diff exercises `screen_baseline_feasibility` with `LpStatus.ERROR`/`LIMIT`/`UNBOUNDED` — the only
  such-status assertions target `hybrid_solve()`'s outcome, not the baseline screen.
- **Suggested fix:** Split `screen_baseline_feasibility` the same way `hybrid_solve` already does: `lp.is_infeasible`
  → baseline-infeasible (422), any other non-optimal status → a distinct solver-failure signal the caller maps to
  500. Add fixtures forcing `LpStatus.ERROR`/`LIMIT`/`UNBOUNDED` on the baseline screen specifically.
- *(Found by one angle — Angle C "cross-file tracer" — but independently re-verified here by direct code
  inspection, including the contrast with `hybrid_solve`'s own correct handling of the identical distinction a few
  lines below.)*

#### R2-5 — Guardrail normalization exceeds CLAUDE.md's four permitted operations, and `explanation`'s required-field check is explicitly skipped

- **Status:** OPEN — confirmed by direct inspection. Self-documented as deliberate; flagged because CLAUDE.md's
  rule text draws no carve-out for score-irrelevant fields.
- **File:** [app/guardrails/normalizer.py:54-67](app/guardrails/normalizer.py#L54-L67) (`normalize_explanation`),
  [app/guardrails/directive_validator.py:216-227](app/guardrails/directive_validator.py#L216-L227) (`_validate_entry`
  skipping `MISSING_FIELD` for `explanation`).
- **Severity:** Medium — practical scoring impact is low (the rubric doesn't grade explanation wording), but it is
  a literal violation of a rule CLAUDE.md states as closed and absolute.
- **Summary:** CLAUDE.md: "Guardrails may only sort by `note_index`, sort an already-unique hour set, normalize
  `-0.0`, and trim whitespace. They must never deduplicate hours, clip out-of-range numbers, or repair semantics."
  `normalize_explanation` does three things outside that list: (a) fabricates `""` when the field is `None` (line
  62-63); (b) coerces a non-string via `str(value).strip()` (line 67); (c) truncates to `MAX_EXPLANATION_CHARS`
  (500) — content modification, not whitespace trimming. `_validate_entry` compounds this: `explanation` is listed
  in `REQUIRED_ENTRY_FIELDS`, but line 220-221 explicitly `continue`s past the `MISSING_FIELD` rejection for it
  specifically. The code's own docstring (`normalizer.py:57`) calls this "a documented, deliberate extension of the
  four safe normalizations" — an admission, in-line, that it goes beyond the rule as written.
- **Failure scenario:** None in terms of a wrong optimizer output — `explanation` carries no score. The risk is
  policy drift: CLAUDE.md presents the four-operation list as closed and non-negotiable elsewhere in the same
  document ("Never invent directive types," "Never hard-code..."), so a reviewer or judge auditing guardrail
  behavior against the literal spec text would find a contradiction the code comments explain but the governing
  document does not sanction.
- **Suggested fix:** Either (a) formally amend CLAUDE.md / `IMPLEMENTATION_TRACKER.md`'s digest to carve out
  `explanation` as a sixth allowed normalization (since it's unscored, this is defensible), or (b) stop treating
  `explanation` as a guardrail concern at all — drop it from `REQUIRED_ENTRY_FIELDS`/`MISSING_FIELD` handling and
  let the downstream Pydantic response model coerce/default it, which is the general mechanism already used
  elsewhere in the pipeline for non-guardrail concerns. Either is fine; leaving the closed list contradicted by a
  code comment is the part worth fixing.
- *(Independently found by two finder-angle agents — Angle "altitude/mechanism-generality" and Angle
  "CLAUDE.md-conventions audit" — from different framings of the same underlying issue.)*

### New findings — reported by one angle, corroborating evidence gathered but not independently re-derived

#### R2-6 — A genuine solver failure on the P10 retry is silently discarded in favor of the original outcome

- **Status:** OPEN — confirmed by direct inspection. Currently **latent** (both statuses map to 500 today per
  R2-3), becomes an **active** bug the moment R2-3 is resolved in favor of 422.
- **File:** [app/services/optimize_service.py:191-194](app/services/optimize_service.py#L191-L194)
  (`_solve_with_feasibility_retry`).
- **Severity:** Medium today, High if R2-3 changes `DirectiveInfeasible` to 422.
- **Summary:** `retry_outcome = hybrid_solve(request, retry.directives, self._settings)` — if `retry_outcome.ok` is
  `False` for *any* reason, including a genuine `SOLVER_FAILURE` on the reparsed directives, the function discards
  `retry_outcome` entirely and returns the **original** `outcome`/`directives` (line 194), which is always
  `DIRECTIVE_INFEASIBLE` at this call site.
- **Failure scenario (once R2-3 is fixed):** After the one bounded reparse, the new directive set is legitimate but
  the MILP genuinely errors out on it. Instead of surfacing as 500 (a real internal fault), it would be reported as
  422 "unschedulable" — masking an internal fault as a client-facing semantic rejection.
- **Suggested fix:** Propagate `retry_outcome`'s actual status when it is itself a `SOLVER_FAILURE`, rather than
  unconditionally falling back to the pre-retry outcome.
- *(Angle C "cross-file tracer".)*

#### R2-7 — `replay.py` hand-rolls its own solar-overlap tolerance instead of importing the shared policy

- **Status:** OPEN — confirmed by direct inspection.
- **File:** [app/validation/replay.py:172-176](app/validation/replay.py#L172-L176) (`_compose_solar_factor`, local
  `abs_tol=1e-12`) vs. [app/policies/spec_gaps.py:27,32,50](app/policies/spec_gaps.py#L27) (`compose_solar_factors`,
  `FACTOR_EQUALITY_TOLERANCE = 1e-12`, imported and used correctly by
  [app/optimizer/compile_directives.py:23,116](app/optimizer/compile_directives.py#L23)).
- **Severity:** Medium — drift risk, distinct in kind from the *intentional* D-09 duplication.
- **Summary:** This is **not** the deliberate compiler/replay independence CLAUDE.md and D-09 defend — that
  principle is about not sharing the *envelope-deriving* logic, so a composition bug can't build a bad plan and
  then have the same bug approve it. `spec_gaps.py` is different: CLAUDE.md explicitly designates it the single,
  config-flagged source of truth for provisional policies specifically *so that* "an organizer clarification is a
  one-line change." `replay.py` reimplementing the tolerance as a bare literal instead of importing
  `FACTOR_EQUALITY_TOLERANCE`/`compose_solar_factors` defeats that guarantee for this one policy.
- **Failure scenario:** An organizer clarification (or an internal decision) changes the overlap-resolution
  tolerance or logic in `spec_gaps.py`. `compile_directives.py` picks it up automatically; `replay.py` silently
  keeps behaving the old way, which can produce a false `ReplayInvariantFailure` (500) on a now-valid plan, or the
  reverse.
- **Suggested fix:** Have `replay.py` import and call `app.policies.spec_gaps.compose_solar_factors` directly, the
  same way `compile_directives.py` does, instead of maintaining a second copy.
- *(Angle "altitude/mechanism-generality".)*

#### R2-8 — The constraint-matrix build is redone 2–3× per request even though most of it doesn't depend on directives

- **Status:** OPEN — call-site pattern confirmed by direct inspection (`build_model` called at
  [hybrid_solve.py:92 and :106](app/optimizer/hybrid_solve.py#L92)); the "identical output" claim itself was not
  independently re-derived.
- **File:** [app/optimizer/model.py:159-256](app/optimizer/model.py#L159) (`build_model`), called from
  `screen_baseline_feasibility` and `hybrid_solve`, and a third time on the P10 retry path
  (`optimize_service.py` calls `hybrid_solve` again inside `_solve_with_feasibility_retry`); companion redundancy
  in `app/optimizer/compile_directives.py:92-96` (per-hour default arrays rebuilt from `request.canonical_hours()`
  every call).
- **Severity:** Medium — performance only, not correctness; relevant to the 4.5s soft / 30s hard latency budget.
- **Summary:** `objective`, `a_eq` (49×168), and `a_ub` (72×168) depend only on `request` (demand, tariff, battery
  rate limits) — never on `compiled`/directives — but are rebuilt via per-element Python loops on every call rather
  than being built once per request and reused with only the bounds swapped in.
- **Suggested fix:** Split into `build_base_model(request)` (built once per request, cached) +
  `apply_bounds(base, compiled)` (cheap array assignment), so the baseline screen, the real solve, and the P10
  retry share one base build.
- *(Angle "efficiency".)*

#### R2-9 — `soft_response_budget_seconds` is defined but never used; no time is reserved for solve+replay after the LLM call

- **Status:** OPEN — confirmed by direct inspection: `grep -rn soft_response_budget_seconds app/` matches only its
  own definition at [app/config.py:77](app/config.py#L77) (plus a stale `.pyc`).
- **File:** `app/config.py:77`, `app/services/deadline.py` (only tracks `hard_request_deadline_seconds`, 28s),
  `app/llm/repair.py` (`_budget_allows` only checks `deadline.allows(MINIMUM_ATTEMPT_SECONDS)`, 0.5s, before
  starting another LLM attempt).
- **Severity:** Medium-High — reliability/latency risk. The organizer's hard limit is 30s with an uncontrolled
  timeout counting as a full failure, worse than a controlled 500.
- **Summary:** `Deadline` tracks a single 28s ceiling with no concept of "enough time must also remain for
  compile + LP + MILP + the up-to-3-rung precision ladder + replay" after the LLM stage finishes.
  `hybrid_solve()` itself takes no deadline argument and is never time-checked.
- **Failure scenario:** Two LLM attempts near `llm_attempt_timeout_seconds` each, plus a rate-limit wait, plus the
  P10 reinterpretation, can legitimately consume close to the full 28s under the operator's own config — leaving
  the solve + 3-rung ladder + replay to run with no time check at all, risking a response past the organizer's 30s
  hard limit as an uncontrolled timeout rather than a fast, controlled 500.
- **Suggested fix:** Reserve a fixed slice (reuse `soft_response_budget_seconds` or add `solve_reserve_seconds`)
  for the post-LLM stages; have `_budget_allows` refuse a further LLM attempt once remaining time drops below
  `(reserve + MINIMUM_ATTEMPT_SECONDS)`.
- *(Angle "efficiency".)*

### New findings — lower priority, not independently re-verified this pass

These were reported with direct code quotes and file:line references by a single agent each; they read as
plausible and are worth fixing, but were not re-derived by separate inspection this pass given the volume of
findings. Spot-check before trusting at the same confidence as the entries above.

| ID | File | One-line summary | Severity | Angle |
|---|---|---|---|---|
| R2-10 | `app/llm/repair.py:234` | `error.retry_after or TRANSPORT_BACKOFF_SECONDS` treats an explicit `Retry-After: 0` as falsy, adding a spurious 0.25s backoff instead of retrying immediately — the same `if x:` vs `if x is not None:` class of bug the guardrails are otherwise careful about for `factor`/`max_grid_kwh`. | Low | Line-by-line (Angle A) |
| R2-11 | `app/services/plan_summary.py` | `build_plan_summary`'s branching logic (directive-phrase lookup, "no directive applied" vs. "N note(s) not schedule-relevant," charge/discharge sentence construction) has zero direct test coverage — confirmed via `grep -rn build_plan_summary tests/` returning no matches. | Medium | Conventions audit |
| R2-12 | `app/llm/providers/anthropic_provider.py` + `openai_provider.py` | `_raise_for_status`/`_is_number` and the pooled-`httpx.AsyncClient` boilerplate are byte-for-byte duplicated across both provider adapters instead of living in `app/llm/base.py`. | Low-Medium | Reuse + Altitude (both independently) |
| R2-13 | `app/llm/schema.py:65-151` | Per-directive-type required-adjustment-field lists duplicate `app/guardrails/directive_validator.py`'s `ADJUSTMENT_FIELDS`, as two independently hand-maintained copies of the same taxonomy fact. | Low | Reuse |
| R2-14 | `app/optimizer/hybrid_solve.py:109-169` | Five near-identical `SolveOutcome(...)` construction blocks (one per failure branch) that a small `_failure(...)` helper would collapse to one, reducing the chance of forgetting to pass `lp=`/`milp=` in a new branch. | Low | Simplification |
| R2-15 | `app/guardrails/directive_validator.py:342-395` | `_validate_factor`/`_validate_reserve`/`_validate_grid_cap` share an identical check→record→normalize shape that a single parameterized helper would collapse. | Low | Simplification |
| R2-16 | `app/optimizer/lp_relaxation.py:75` vs `milp_solver.py:83` | `scipy_bounds()` materializes a fresh 168-tuple Python list every LP solve (2-3× per request); the MILP path passes `model.lower_bounds`/`upper_bounds` directly via `scipy.optimize.Bounds`, which is vectorized and could be reused by the LP path too. | Low | Efficiency |
| R2-17 | `app/guardrails/directive_validator.py` (`_validate_hours`) | The `HOUR_OUT_OF_RANGE` branch doesn't `return`, unlike every other check in the function — falls through to `sort_hours`, which can append a "normalized" telemetry entry for an hour set already known invalid (the containing report is discarded once `ok=False`, so not exploitable, but pollutes `normalizations` telemetry). | Low | Line-by-line (Angle A) |
| R2-18 | `app/optimizer/result.py:137-155`, `app/services/optimize_service.py:229-283` | Two minor "worth a look, not a defect" notes: `_fit_to_bound`'s `np.isscalar` branch exists only to serve its own two call shapes and could be dropped if both callers passed arrays; `_assemble`/`_build_validated_response` split adds one layer of indirection without removing real duplication. | Low | Simplification |

---

## Review 3 — 2026-09-18 (commit `b886a0b`, Docker + regression/property/security test suites)

Scope: **narrower than Review 2 on purpose** — this pass targeted only the single new commit that landed after
Review 2, `b886a0b` ("feat: initiate docker, regression test"): `Dockerfile`, `docker-compose.yml`, `DOCKER.md`,
`scripts/{healthcheck,paraphrase_eval,semantic_corpus,verify_docker,verify_solver}.py`, a small `milp_solver.py`
change (`milp_relative_gap: 1e-4 -> 0.0`), and four new test suites (`tests/property/test_optimizer_properties.py`,
`tests/regression/test_end_to_end.py`, `tests/regression/test_semantic_corpus.py`,
`tests/security/test_prompt_injection.py`). It did **not** re-run the 8-angle finder process or re-check R2-1
through R2-18 against the current tree — see "Unreviewed scope" below for what Review 4 still owes.

Method: single-pass `/code-review` (not the multi-agent fan-out used for Review 2) — read the full diff, then
actually ran the new/changed test suites rather than trusting them statically. All five new/touched suites passed.
A repeating "Windows fatal exception: access violation" noise from the httpx/starlette `TestClient` was confirmed
to be a pre-existing local-environment artifact (also present running the untouched `tests/integration/`
`test_optimize_pipeline.py`), not something this commit introduced, and is excluded below.

### Carried over from previous passes

**Not re-checked this pass** — Review 3's scope was limited to the single new commit (see above). R1-1/R1-2 remain
`FIXED` (last re-confirmed in Review 2). R2-1 through R2-18 remain `OPEN` as of Review 2 and were not touched by
`b886a0b`'s diff (none of the files it changes overlap with any R2 finding's file), so their status is presumed
unchanged, but this is an assumption, not a re-verification — Review 4 should confirm it directly rather than
trust this note indefinitely.

### New findings

#### R3-1 — `optimizer_version` was not bumped despite a real MILP behavior change, weakening cache-key and diagnostic traceability

- **Status:** OPEN — confirmed by direct inspection.
- **File:** [app/config.py:104](app/config.py#L104) (`optimizer_version: str = "lp-milp-v1"`, unchanged),
  vs. `app/config.py:~103` (`milp_relative_gap: float = 0.0`, changed from `1e-4` in this commit — confirmed via
  `git show b886a0b -- app/config.py`).
- **Severity:** Medium-High — CLAUDE.md is explicit that `OPTIMIZER_VERSION` (along with `PROMPT_VERSION`,
  `SCHEMA_VERSION`, and commit SHA) "belong in cache keys and diagnostics — a parser cache keyed only on note text
  is a correctness bug." This commit is exactly the kind of change that rule exists for.
- **Summary:** `milp_relative_gap` tightening from `1e-4` to `0.0` is a genuine change to MILP solve behavior (a
  looser gap could previously accept a near-optimal-but-not-optimal solution as `proven_optimal=true`; this commit
  fixes that). `app/cache/request_cache.py`'s `response_cache_key()` and the diagnostic trace both key off
  `settings.optimizer_version`, which this commit leaves at `"lp-milp-v1"`. The only other differentiator,
  `app_commit_sha`, defaults to `""` and `DOCKER.md` documents it as optional ("no [value] required").
- **Failure scenario:** A deploy that forgets to set `APP_COMMIT_SHA` produces cache entries / diagnostic traces
  from before this fix that are indistinguishable from ones after it — a pre-fix result could carry
  `proven_optimal=true` while actually having been accepted at the old, looser 1e-4 gap, which is the exact
  score-losing bug this commit is fixing, silently surviving in the cache under the same version key.
- **Suggested fix:** Bump `optimizer_version` whenever solver-affecting settings change (this one qualifies), or
  make `APP_COMMIT_SHA` a hard requirement at startup rather than an optional documentation note.

#### R3-2 — A new end-to-end test asserts an exact, whitespace-sensitive prompt substring, unlike its own sibling test in the same commit

- **Status:** OPEN — confirmed by direct inspection.
- **File:** [tests/regression/test_end_to_end.py:60](tests/regression/test_end_to_end.py#L60) (`ReferenceProvider.complete`),
  contrast with `tests/security/test_prompt_injection.py`'s `test_system_prompt_states_the_data_boundary`.
- **Severity:** Low-Medium — test fragility / false-negative risk, not a production bug.
- **Summary:** `assert "reduced BY 20%       -> 0.80" in system_prompt` depends on the literal internal spacing of
  `app/llm/prompts.py`'s factor-contrast table. The prompt-injection test added in the *same commit* deliberately
  avoids exactly this fragility: it collapses whitespace first
  (`" ".join(build_system_prompt().split())`) with a comment explaining that line-wrap brittleness is undesirable —
  i.e., the commit already contains the fix pattern, just not applied consistently to its sibling test.
- **Failure scenario:** A future purely-cosmetic reformat of the factor table (column re-alignment, switching to
  markdown table syntax, adjusting wrap width — no semantic change) fails this "guards the mandatory-LLM
  requirement" end-to-end suite, giving a false signal that the interpreter was bypassed when it wasn't.
- **Suggested fix:** Apply the same whitespace-collapsing comparison `test_prompt_injection.py` already uses.

#### R3-3 — The Docker deployment gate's secret-leak check can false-positive on ordinary LLM-generated explanation text

- **Status:** OPEN — confirmed by direct inspection.
- **File:** [scripts/verify_docker.py:106](scripts/verify_docker.py#L106) (response-body scan for bare words like
  `"Authorization"`/`"api_key"`).
- **Severity:** Medium — this script is the pre-push "do not ship" gate (`T-161`); a false failure blocks a
  legitimate build, which has a real cost during a hackathon deadline even though it fails safe (blocks a good
  build) rather than unsafe (ships a bad one).
- **Summary:** The check flags any response body containing the bare word `"Authorization"` or `"api_key"`,
  without distinguishing an actual leaked credential from those words simply appearing in generated text.
- **Failure scenario:** An operator note like "requires facilities authorization before 6 PM" causes the model's
  `explanation` field to echo the word "Authorization." `exercise_optimize()` raises
  `VerificationError("response leaked 'Authorization'")`, failing a build that shipped nothing sensitive.
- **Suggested fix:** Match against actual secret-shaped values (the configured API key's value, a credential
  pattern) rather than bare English words that can appear in ordinary generated text.

#### R3-4 — `IMPLEMENTATION_TRACKER.md` marks Docker tasks `[x]` complete while the same entry discloses the image was never built or run

- **Status:** OPEN — confirmed by direct inspection.
- **File:** [IMPLEMENTATION_TRACKER.md:637-645](IMPLEMENTATION_TRACKER.md#L637-L645) (`T-160`, `T-161`).
- **Severity:** Medium — process/documentation accuracy, not a code defect. The tracker's own "Definition of done"
  (§0.3) requires "`pytest` green for the whole suite" and code "verified," which for `scripts/verify_docker.py`
  specifically means actually running it.
- **Summary:** `T-160` and `T-161` both carry the `[x]` "done and its tests pass" marker, but `T-161`'s own
  description line ends with "**Not yet executed:** no Docker daemon on the authoring machine — see the session
  log" — directly contradicting the `[x]` marker's stated meaning (§0.2: `[x]` = "done **and** its tests pass").
- **Failure scenario:** Someone scanning the tracker's checklist for what's safely usable — e.g. a teammate about
  to deploy the image to Azure per the session log's own note ("a teammate needs it now") — would reasonably read
  `[x]` as "the container has been proven to build and run" when it has not been, on this machine, at all.
- **Suggested fix:** Mark `T-160`/`T-161` `[~]` (in progress) or add a distinct marker for "code complete, unverified
  in this environment" until `scripts/verify_docker.py` has actually been run once, on any machine with a Docker
  daemon, and the tracker updated with the result.

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

Review 2 covered P4–P6 (`58821e8`, `fedb14c`, `a715c42`) plus the LLM interpreter/providers/repair and guardrails
code (via the commits `3a7c7f4`, `28b9705` that had landed by the time Review 2 ran). Review 3 covered only the
single commit that landed after that, `b886a0b` (Docker + regression/property/security test suites).

**Still outstanding for Review 4:**
- **R2-1 through R2-18 have not been re-checked against the current tree since Review 2.** None of `b886a0b`'s
  files overlap with an R2 finding's file, so nothing in Review 3 should have changed their status — but this is
  an inference, not a re-verification. Review 4 should confirm directly, prioritizing R2-1 (app-crash-at-import),
  R2-2 (precision ladder), R2-3/R2-4 (error-status mapping), and R2-5 (guardrail scope) as the highest-severity
  items still unconfirmed as fixed or open.
- Review 2's "lower priority, not independently re-verified" table (R2-10 through R2-18) still needs spot-checking.
- Whatever lands after `b886a0b` needs its own pass — check `git log a715c42..HEAD` (or the current tracker's
  latest completed task) for anything not yet listed as a review scope in this file.

---

## Next review

When `/code-review` is next run, append a **Review 4** section above this line following the same structure. Two
things it should do that Review 3 explicitly deferred: (1) re-check R2-1 through R2-18 against the current tree —
none were touched by `b886a0b`, so they are presumed still `OPEN`, but this needs direct confirmation, not
inheritance; (2) re-check R3-1 through R3-4. If R2-3 (`DirectiveInfeasible` status code) is resolved, re-check R2-6
(retry-outcome masking) specifically, since fixing one can turn the other from latent to active.
