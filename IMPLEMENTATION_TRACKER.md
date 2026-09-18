# GridWise — Implementation Tracker

**Purpose:** single source of truth for *what is built, what is next, and why*. This file exists so that work can
resume in a brand-new chat/thread without re-reading the ~6,400 lines of `docs/`.

**Status:** `P2 COMPLETE — awaiting approval to start P3`
**Last updated:** 2026-09-18
**Current phase:** P3 (not started)
**Next action:** `T-030` (directive compiler)

---

## 0. How to use this file

### 0.1 If you are a new session picking this up

1. Read §1 (status snapshot), §2 (locked decisions), §3 (open decisions), §4 (canonical rules digest).
2. Read the phase board (§6) and find the first task that is not `[x]`.
3. Only if the task touches semantics you are unsure about, open the source doc named in §4.6.
4. Do the task. Write its tests. Run them. Then update §1, the task checkbox, and append to §10.

### 0.2 Status markers

| Marker | Meaning |
|---|---|
| `[ ]` | not started |
| `[~]` | in progress (say what is half-done in §10) |
| `[x]` | done **and** its tests pass |
| `[!]` | blocked (record the blocker in §3 or §10) |
| `[-]` | intentionally dropped (record why in §10) |

### 0.3 Definition of done (every task)

- Code written.
- Tests written **only where they carry their weight** — see D-15. Correctness-critical modules (guardrails, replay,
  compiler, solvers, error mapping, semantics) are tested; plumbing and glue are verified by running them.
- `pytest` green for the whole suite, not just the new test.
- `ruff check .` clean.
- This tracker updated: task marker, §1 snapshot, §10 log entry.

### 0.4 Working rhythm

One phase per turn. Finish the phase, verify it, update this file, then **stop and wait for approval** before
starting the next phase. (User instruction, session 2.)

### 0.5 Rules that override convenience

- Never edit anything in `docs/` — the organizer files are read-only, and `docs/PRD.md` / `docs/IMPLEMENTATION_GUIDE.md`
  are the frozen team spec. Changes of intent go **here**, not there.
- Never hard-code public sample wording, IDs, values, or schedules anywhere in `app/`.
- Never add a field to the `/optimize-energy` response body beyond the seven canonical fields.
- Never let a regex/keyword matcher become the semantic interpreter or its fallback.

---

## 1. Status snapshot

| Field | Value |
|---|---|
| Phase | P3 — Directive compiler (not started) |
| Last completed task | `T-021` (P2 complete) |
| Next task | `T-030` |
| Tests passing | 64 / 64, `ruff check .` clean |
| Public cases passing | 0 / 10 |
| Endpoint deployed | no |
| Docker image | not built |
| README | not written |

Local toolchain verified: Python 3.14 (dev) with FastAPI 0.138.1, Pydantic 2.12.5, NumPy 2.4.2, SciPy 1.17.1,
httpx 0.28.1, pytest 8.4.2, ruff 0.15.15 already installed. Python 3.12 also present; the Docker image pins 3.12
and the pinned versions in `requirements.txt` work on both.

---

## 2. Locked decisions

These are settled. Do not relitigate without recording a reason in §10.

| ID | Decision | Rationale / source |
|---|---|---|
| D-01 | Python 3.12 + FastAPI + Pydantic v2 + NumPy + SciPy (HiGHS) + pytest + ruff + Docker | Guide §2, §34; PRD §21 |
| D-02 | **LP-assisted MILP.** LP = relaxation / feasibility / lower bound only; MILP = authoritative returned plan | PRD §12; CLAUDE.md. Overrides the deep-research doc's "pure LP is enough" argument — that doc never overrides team spec |
| D-03 | LLM does semantic parsing only; it never emits kWh, costs, or schedules | Problem Statement §02–03; PRD §7 |
| D-04 | One structured-output LLM call for all 1–3 notes per request | Guide §7.2, §36 |
| D-05 | LLM context = battery object + notes only. **Do not** send the 24-hour demand/solar/tariff matrix | Guide §7.2; PRD FR-04 |
| D-06 | Directive taxonomy is closed (6 types). Unknown type ⇒ guardrail rejection, never coercion | Problem Statement §04 |
| D-07 | `plan_summary` is generated deterministically, not by a second LLM call | PRD FR-12; Guide §17 |
| D-08 | Error mapping: structural ⇒ 400, semantic / baseline-infeasible ⇒ 422, LLM-unusable / solver / replay ⇒ 500 | Problem Statement §6.1; Guide §19 |
| D-09 | The replay validator is *separate code* from the model builder and the canonicalizer, and runs on the **serialized-then-parsed** response values | Guide §15; PRD FR-11 |
| D-10 | Build order: optimizer first, LLM second (P0→P7 before P8) | Guide §43; CLAUDE.md |
| D-11 | Internal tolerance 1e-7; judge tolerance 0.01. No rounding of energy fields to 2 dp; serialize 6–8 decimals | Guide §37; PRD NFR-05 |
| D-12 | Provisional spec-gap policies are config-flagged and isolated in one module (cross-midnight, `through`, single-hour phrasing, overlapping solar factors) | PRD §20.2 |
| D-13 | Repo layout follows Guide §3 (`app/api`, `app/schemas`, `app/llm`, `app/guardrails`, `app/optimizer`, `app/validation`, `app/services`, `app/observability`, `app/cache`, `app/demo`) | Guide §3 |
| D-14 | Demo layer lives behind `DEMO_MODE` on separate routes; never inside the judge response | PRD §13 |
| D-15 | **Targeted tests, not blanket tests.** Test the correctness-critical surfaces (guardrails, replay validator, directive compiler, solvers, error mapping, semantic normalization) and skip tests for plumbing that running the code already proves. Supersedes CLAUDE.md's "every step ships with tests" | User instruction, session 2 |
| D-16 | Local dev runs on the globally installed Python 3.14; the image pins `python:3.12-slim`. Pinned dependency versions are valid on both | Session 2 environment check |

---

## 3. Open decisions (resolve before the phase that needs them)

| ID | Question | Needed by | Default if unresolved |
|---|---|---|---|
| O-01 | Which LLM provider + exact pinned model snapshot? (structured-output support is the hard requirement) | P8 | Pick a structured-output-capable model, pin the snapshot, record the exact ID in `.env.example` + README |
| O-02 | Backup provider — configure one, or accept single-provider risk? | P10 | Build the adapter seam; leave the backup unconfigured unless it passes the same semantic corpus |
| O-03 | Hosting platform for the public HTTPS endpoint | P16 | Any platform the team already knows; must bind `0.0.0.0`, no login/VPN, stays warm |
| O-04 | Container registry for the fallback image (Docker Hub / GHCR) | P16 | GHCR with an immutable digest |
| ~~O-05~~ | ~~Oversized request/note policy~~ | — | **Resolved P0:** 413, config key `OVERSIZED_REQUEST_STATUS`, to be documented in the README |
| ~~O-06~~ | ~~Reject negative `demand_kwh` / `solar_kwh`?~~ | — | **Resolved P0:** yes, 422, config key `REJECT_NEGATIVE_ENERGY_INPUTS`. Corroborated by INV-09/INV-10 in the adversarial corpus. **Tariff stays unrestricted** (PRD §20.2) |
| O-07 | Redis vs in-process LRU for the cache | P14 | In-process LRU+TTL; Redis only if it demonstrably helps |
| O-08 | Demo dashboard: React/Vite vs server-rendered | P18 | Server-rendered — fewer moving parts, no build step in the image |

---

## 4. Canonical rules digest

Distilled from the organizer documents. **If this digest and `docs/` ever disagree, `docs/` wins**, and the Problem
Statement wins over everything else.

### 4.1 API contract

`GET /health` → `200 {"status":"ok"}`. No LLM call, no solver call. Must be ready within 60 s of service start.

`POST /optimize-energy` request:

```
scenario_id: str
operator_notes: list[str]   # 1..3, non-empty after trim
hours: list[24]             # {hour: int 0..23 unique, demand_kwh, solar_kwh, tariff_bdt_per_kwh}
battery: {capacity_kwh, initial_energy_kwh, minimum_energy_kwh,
          max_charge_kwh_per_hour, max_discharge_kwh_per_hour}
```

Response — exactly these seven fields, nothing more:

```
scenario_id                 # echoes the request
directive_interpretation[]  # {note_index, applies, directive_type, structured_adjustment, explanation}
hourly_plan[24]             # {hour, grid_kwh, solar_used_kwh, battery_action, battery_kwh, battery_energy_after_kwh}
total_grid_kwh
total_cost_bdt
peak_grid_kwh
plan_summary
```

`battery_action ∈ {charge, discharge, idle}`; `battery_kwh` is a non-negative magnitude and must be `0` when `idle`.
The input `hours` array order is **not** trustworthy — canonicalize internally by the `hour` field.

### 4.2 Directive taxonomy (closed set)

| type | `structured_adjustment` | optimizer effect |
|---|---|---|
| `solar_reduction` | `{"hours":[...], "factor": n}` | `effective_solar[h] = solar[h] * factor` |
| `minimum_battery_reserve` | `{"hours":[...], "minimum_energy_kwh": n}` | `E[h] >= max(base_min, directive_min)` |
| `no_charge_window` | `{"hours":[...]}` | `c[h] = 0` |
| `no_discharge_window` | `{"hours":[...]}` | `d[h] = 0` |
| `max_grid_window` | `{"hours":[...], "max_grid_kwh": n}` | `g[h] <= max_grid_kwh` |
| `no_op` | `null` | none |

Hard rules: exactly one entry per note, emitted in `note_index` order `0..N-1`; `applies=false` **only** for `no_op`
(and then `structured_adjustment` must be `null`); every other type has `applies=true`; `hours` are unique integers
0–23 in **ascending** order.

### 4.3 Semantics that cost points when wrong

- **`factor` = fraction remaining.** "reduced to 20%" → `0.2`; "80% reduction" → `0.2`; "reduced by 20%" → `0.8`;
  "operating at 80%" → `0.8`; "one-fifth remains" → `0.2`; "halved" → `0.5`; "unavailable" → `0.0`; "12.5%" → `0.125`.
- **Windows are start-inclusive, end-exclusive.** 1 PM–3 PM → `[13,14]`; "6 until 9 PM" → `[18,19,20]`;
  "between 2 and 4 PM" → `[14,15]`; `13:00–15:00` → `[13,14]`; noon = 12; midnight = 0; a shared suffix
  ("one to three PM") applies to both endpoints.
- **Percentage reserves resolve against battery capacity** (SAMPLE-03: 50 % of a 200 kWh battery → 100 kWh) — this is
  exactly why the battery object must be in the prompt context.
- `factor=0.0` and `max_grid_kwh=0.0` are valid values. Never lose them to a truthiness check (`if factor:` is a bug).
- Distractors that mention times or energy words are still `no_op`.

### 4.4 Energy model

```
g[h] + s[h] + d[h] = demand[h] + c[h]              # balance, every hour
E[0] = initial + c[0] - d[0];  E[h] = E[h-1] + c[h] - d[h]
E[23] = initial_energy_kwh                          # end-of-day neutrality
active_min[h] <= E[h] <= capacity
0 <= s[h] <= effective_solar[h]                     # curtailment allowed, export forbidden
0 <= c[h] <= max_charge * yc[h];  0 <= d[h] <= max_discharge * yd[h];  yc[h] + yd[h] <= 1
minimize sum(g[h] * tariff[h])
```

No efficiency loss, no degradation cost, no export revenue on the judge path — the organizer defines none.
Totals are always recomputed from the returned plan. `idle` is derived when both magnitudes are zero.

Directive composition: reserves combine pointwise `max`; grid caps pointwise `min`; charge/discharge bans are hard
booleans (both on one hour ⇒ forced idle).

### 4.5 Guardrail boundaries

Guardrails may **only**: sort by `note_index` (when indices are unique), sort an already-unique hours array, normalize
`-0.0`, and trim explanation whitespace. They must **never**: deduplicate hours, clip out-of-range numbers, coerce an
unknown type, or invent a missing value. Anything else ⇒ reject ⇒ one bounded repair ⇒ otherwise controlled failure.

### 4.6 Where to look when this digest is not enough

| Question | Document |
|---|---|
| API fields, directive shapes, guardrails, battery/energy rules, validity | `docs/BUP_CSE_FEST_2026_Preliminary_Problem_Statement_GridWise_LLM.md` (**canonical**) |
| Scoring, penalties, latency bands, deliverables, submission, tie-breaks | `docs/BUP_CSE_FEST_2026_Participant_Guide_%26_Evaluation_Rubric_GridWise_LLM.md` (**canonical**) |
| Worked examples / regression seed | `docs/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json` |
| Product requirements FR-01..FR-14, NFRs, risks | `docs/PRD.md` |
| Module layout, code skeletons, config, prompts, CI, Docker, checklists | `docs/IMPLEMENTATION_GUIDE.md` |
| Edge-case matrix, adversarial gold examples, literature | `docs/GridWise-Deep-Research.md` (never overrides organizer docs) |
| Ready-made adversarial / guardrail / invalid-request fixtures | `docs/GridWise_Adversarial_Edge_Cases.json` (unofficial synthetic corpus — its own `_meta` says so) |
| 34 extra hidden-like scenarios with expected output + optimization reference | `docs/GridWise_Extended_HiddenLike_Cases.json` (unofficial synthetic corpus) |

### 4.8 Test-corpus assets

Added to `docs/` by the team after session 1. Both are **unofficial synthetic corpora**, not leaked judge data, and
neither overrides the organizer documents. They save a large amount of fixture authoring:

| Asset | Contents | Consumed by |
|---|---|---|
| `GridWise_Adversarial_Edge_Cases.json` | 7 semantic variation groups (58 phrasings) · 5 prompt-injection notes · 11 invalid request cases **with expected HTTP status** · 2 raw malformed bodies · 14 guardrail output cases · 4 spec-ambiguity cases · 10 metamorphic relations | P1 (error mapping), P9 (guardrails), P12 (semantics/injection), P13 (metamorphic) |
| `GridWise_Extended_HiddenLike_Cases.json` | 34 scenarios with `input`, `expected_output`, `optimization_reference`, tags | P7, P11, P12 |

Its `invalid_request_cases` classify every expectation as `canonical` or `recommended-domain-sanity`, which settles
O-06: negative demand and negative solar are 422 (`recommended-domain-sanity`), while tariff stays unrestricted.

### 4.7 Scoring map (what each phase is worth)

| Category | Pts | Phases that earn it |
|---|---:|---|
| LLM directive interpretation | 25 | P8, P9, P12 |
| Directive application & constraint correctness | 25 | P2, P3, P4, P5, P6 |
| Optimization quality — `min(1, optimal/team_cost)`, **0 for any invalid case** | 10 | P5, P7 |
| API contract & schema | 10 | P1 |
| Performance & reliability | 10 | P10, P14, P15, P17 |
| Deployment & Docker fallback | 10 | P16 |
| Documentation & local reproducibility | 10 | P20 |

Latency bands: p95 ≤ 5 s ⇒ 3/3; >5–15 s ⇒ 2/3; >15–30 s ⇒ 1/3; >30 s ⇒ 0 and the request counts as a failure.
Internal targets: 4.5 s soft budget, 28 s hard deadline.

---

## 5. Target file manifest

Tick a row when the file exists and its tests pass.

```
[x] pyproject.toml              [x] requirements.txt        [x] .env.example
[x] .gitignore                  [x] .dockerignore           [ ] Dockerfile
[ ] docker-compose.yml          [ ] README.md               [ ] .github/workflows/ci.yml

app/
[x] main.py                     [x] config.py
[x] api/routes.py               [x] api/errors.py           [x] api/middleware.py
[x] schemas/request.py          [x] schemas/directive.py    [x] schemas/response.py    [ ] schemas/internal.py
[ ] llm/base.py                 [ ] llm/interpreter.py      [ ] llm/prompts.py
[ ] llm/providers/primary.py    [ ] llm/providers/backup.py [ ] llm/repair.py
[ ] guardrails/directive_validator.py   [ ] guardrails/normalizer.py   [ ] guardrails/conflict_checks.py
[ ] optimizer/compile_directives.py     [ ] optimizer/model.py         [ ] optimizer/lp_relaxation.py
[ ] optimizer/milp_solver.py            [ ] optimizer/hybrid_solve.py  [ ] optimizer/result.py
[x] validation/replay.py        [x] validation/totals.py
[x] services/optimize_service.py
[ ] observability/logging.py    [ ] observability/metrics.py  [ ] observability/trace.py
[ ] cache/request_cache.py
[ ] demo/routes.py              [ ] demo/models.py
[ ] policies/spec_gaps.py       # D-12: cross-midnight, through, single-hour, solar overlap

tests/   unit/ integration/ regression/ security/ property/
scripts/ run_public_cases.py  benchmark_latency.py  verify_docker.py  paraphrase_eval.py
public_cases/sample_cases.json   # copied from docs/, never edited
```

---

## 6. Phase board

Phases are a dependency order (Guide §43), not a time budget. Time is explicitly **not** a constraint on this project;
do not scale work down to save it.

### P0 — Scaffolding `[x]`

- `[x] T-001` `pyproject.toml` (ruff + pytest config), `requirements.txt` / `requirements-dev.txt` (pinned),
  `.gitignore`, `.dockerignore`, and the `app/` package tree from §5.
  *Verified:* `ruff check .` clean, `import app` works, `pytest` exit 0.
- `[x] T-002` `app/config.py` — typed `Settings` for every key in Guide §4 plus `OVERSIZED_REQUEST_STATUS` (O-05),
  `REJECT_NEGATIVE_ENERGY_INPUTS` (O-06), `RESPONSE_DECIMAL_PLACES`, `SOLVER_EPSILON`, and the three spec-gap policies
  as `StrEnum`s. `LLM_API_KEY` / `BACKUP_LLM_API_KEY` are `SecretStr`. `.env.example` written; `.env` gitignored
  (`git check-ignore` confirms).
  *Tested:* `tests/unit/test_config.py` — env overrides apply; the API key never appears in `repr`/`str`.
- `[x] T-003` `public_cases/sample_cases.json` copied from `docs/`, verified byte-identical by SHA-256.

### P1 — Schemas, endpoints, error mapping `[x]`

- `[x] T-010` `schemas/request.py` — `StrictModel` (`extra="forbid"`) base, `Finite` float alias rejecting NaN/Inf,
  `HourInput` (`hour` bounded 0–23), `BatteryInput`, `OptimizeRequest` (1–3 notes, exactly 24 hours, hour set exactly
  `{0..23}`, notes non-empty after trim — note text itself left untouched). `canonical_hours()` orders by the `hour`
  field so array position is never trusted.
  Domain-sanity checks deliberately live in `validation/request_semantics.py` so they surface as 422, not 400.
- `[x] T-011` `schemas/directive.py` — `DirectiveType` enum, `HourSetAdjustment` (unique, ascending, in-range,
  non-empty) with `Solar`/`Reserve`/`GridCap` subclasses, six variants with `Literal` discriminators, and the
  `DirectiveInterpretation` discriminated union. `schemas/response.py` — `HourPlan` + `OptimizeResponse` with exactly
  the seven canonical fields and fail-closed validators (plan is hours 0..23 in order, `note_index` is 0..N-1 in order,
  `idle` carries zero magnitude).
- `[x] T-012` `api/errors.py` — `GridWiseError` taxonomy (`StructurallyInvalidRequest` 400,
  `SemanticallyInvalidRequest` 422, `RequestTooLarge` configurable, `InterpretationUnavailable` / `SolverFailure` /
  `ReplayInvariantFailure` / `PipelineNotImplemented` 500) plus handlers that override FastAPI's 422 default.
  One error envelope everywhere; 500s carry a correlation ID and nothing else. `api/middleware.py` adds the
  correlation ID (outermost) and the `Content-Length` body guard.
- `[x] T-013` `api/routes.py` + `main.py` — `/health` (no LLM, no solver) and `/optimize-energy` behind a
  `get_optimize_service` dependency seam. `services/optimize_service.py` runs limits → semantics, then raises
  `PipelineNotImplemented`: a valid request currently returns a controlled 500 rather than a fabricated plan.

*Verified:* all 11 `invalid_request_cases` and both `raw_invalid_cases` from the adversarial pack map to their
expected status; all 10 public inputs and all 10 public + 34 extended `expected_output` bodies round-trip through the
canonical models unchanged; the serialized HTTP body carries exactly seven fields with an explicit
`"structured_adjustment": null` on `no_op`; negative tariff is *not* rejected; `/openapi.json` and `/docs` render;
404/405 stay inside the error envelope. Live `uvicorn` smoke test passed (health, 400, 422, 500 paths).
38 tests green, `ruff check .` clean.

### P2 — Independent replay validator `[x]`

- `[x] T-020` `validation/replay.py` — `ViolationCode` (21 stable codes), `Violation`, `ValidationReport`,
  `ConstraintEnvelope`, `derive_envelope()`, and `replay()`. Every check in Guide §15 plus the Problem Statement §11.3
  consistency list. **It derives the constraint envelope itself** rather than calling the optimizer's compiler — see
  the note below.
- `[x] T-021` `validation/totals.py` — `recalculate_totals()` using `math.fsum`, keyed by hour number rather than
  array position.

*Verified:* all 10 public **and** all 34 extended reference plans replay clean — at 0.01, at 1e-6, and still at 1e-9,
so the envelope derivation agrees with organizer ground truth at machine precision, not merely inside judge tolerance.
Those 44 plans cover every directive type (solar 12, grid cap 12, no_op 11, no-charge 11, reserve 11, no-discharge 8).
20 mutation tests each fail with the expected `ViolationCode`, including one mutation per directive type (charge in a
ban window, discharge in a ban window, grid over cap, dip below a directive reserve, pre-reduction solar use).
An AST-level test asserts `replay.py` imports nothing from `app.optimizer`. 64 tests green, `ruff check .` clean.

> **Do not merge `derive_envelope()` into the P3 compiler.** They are two independent implementations of the same
> rules on purpose (D-09). If the compiler called replay's version, or vice versa, a composition bug would build the
> plan and then approve it. P7 cross-checks them against real cases; a disagreement there is a genuine defect.

### P3 — Directive compiler `[ ]`

- `[ ] T-030` `optimizer/compile_directives.py` → `CompiledConstraints(effective_solar, min_energy, charge_allowed,
  discharge_allowed, grid_upper, ambiguity_flags)` plus a per-hour provenance trace (internal only, Guide §39).
- `[ ] T-031` `policies/spec_gaps.py` — the four provisional policies behind config flags (D-12).
  *Acceptance:* composition tests (reserve `max`, cap `min`, ban union, ban+ban ⇒ idle, differing solar factors ⇒
  `min(factor)` + ambiguity flag); post-compile assertions (`min_energy <= capacity`, `grid_upper >= 0`,
  `effective_solar >= 0`, arrays of length 24); `factor=0.0` and `max_grid_kwh=0.0` survive compilation.

### P4 — Shared LP/MILP model `[ ]`

- `[ ] T-040` `optimizer/model.py` — one variable layout (`g, s, c, d, E, yc, yd` = 168 vars) and one constraint builder
  used by both stages (Guide §12).
  *Acceptance:* dimension/index unit tests; a hand-built feasible plan satisfies `A_eq x = b_eq` within 1e-9.

### P5 — Solvers `[ ]`

- `[ ] T-050` `optimizer/lp_relaxation.py` — `linprog(method="highs")` with `yc, yd ∈ [0,1]`. Used for (a) the pre-LLM
  baseline feasibility screen with no directives and (b) the directive-constrained relaxation.
- `[ ] T-051` `optimizer/milp_solver.py` — `scipy.optimize.milp` with `yc, yd` binary and a time limit. Authoritative.
- `[ ] T-052` `optimizer/hybrid_solve.py` — orchestration + the invariant `LP_cost <= MILP_cost + tol` + solver-status checks.
  *Acceptance:* a baseline-infeasible scenario is detected before any LLM call; LP-infeasible-after-feasible-baseline is
  reported as its own failure class; the MILP never returns simultaneous charge+discharge; the invariant is asserted on
  every solve.

### P6 — Canonicalizer, response builder, summary `[ ]`

- `[ ] T-060` `optimizer/result.py` — eps-canonicalize, derive one action per hour from the *magnitudes*, reconstruct
  `E[h]` sequentially, recompute dependent grid values from the balance equation, serialize 6–8 decimals, parse back.
- `[ ] T-061` Deterministic `plan_summary` (Guide §17) — short, and it must not claim anything the plan does not support.
- `[ ] T-062` Wire `services/optimize_service.py`: validate → baseline LP → (LLM seam) → guardrails → compile → LP → MILP
  → canonicalize → replay → respond. Replay failure ⇒ 500: never a retry, never a 200.
  *Acceptance:* round-trip test — the serialized/parsed values replay PASS; a deliberately mis-rounded plan replays FAIL.

### P7 — Public-case optimizer regression (no LLM) `[ ]`

- `[ ] T-070` `scripts/run_public_cases.py` — feeds the pack's **ground-truth** directives straight into the compiler and
  solvers, bypassing the LLM.
  *Acceptance:* all 10 cases — LP feasible, MILP optimal, `LP <= MILP + tol`, replay PASS, and cost within 0.01 of the
  published reference. Action sequences need not match the reference.

### P8 — LLM interpreter `[ ]`

- `[ ] T-080` Resolve O-01. `llm/base.py` protocol + `llm/providers/primary.py` adapter; exact model snapshot pinned.
- `[ ] T-081` `llm/prompts.py` — system rules from Guide §7.1 (taxonomy, time rules, factor contrast set, reserve rule,
  `no_op` rule, notes-are-untrusted-data), versioned by `PROMPT_VERSION`.
- `[ ] T-082` `llm/interpreter.py` — one structured call for all notes, minimal context (D-05), refusal/truncation
  detection, typed envelope parse.
  *Acceptance:* interpreter tests run against recorded/mocked provider responses (no network in CI); a live smoke test
  sits behind a separate opt-in marker.

### P9 — Deterministic guardrails `[ ]`

- `[ ] T-090` `guardrails/directive_validator.py` — the full check list (Guide §9).
- `[ ] T-091` `guardrails/normalizer.py` — only the four permitted normalizations (§4.5).
  *Acceptance:* fixtures for unknown type, missing/duplicate `note_index`, wrong count, duplicate hours, unsorted hours,
  hour 24, factor 1.8 / −0.1 / NaN / Inf, reserve > capacity, negative grid cap, `applies=false` on a real directive,
  non-null `no_op` adjustment, extra field. Each must reject — not clip, not dedupe.

### P10 — Repair, retry, feasibility-aware reinterpretation `[ ]`

- `[ ] T-100` `llm/repair.py` — failure-class routing per Guide §20 (5xx, 429, refusal/truncation, schema violation,
  semantic violation, directive-LP infeasible). At most 2 attempts on one interpretation path, deadline-aware.
- `[ ] T-101` Focused semantic reinterpretation when the baseline LP is feasible but the directive LP is not. Never weaken
  a constraint to manufacture feasibility.
  *Acceptance:* simulated provider failures for every class; assert attempt counts, and assert that a replay failure
  triggers **no** retry.

### P11 — End-to-end public regression `[ ]`

- `[ ] T-110` All 10 cases through the real HTTP endpoint with the real interpreter.
  *Acceptance:* interpretation semantics match ground truth (type, hours, numerics — explanation text free), plan valid,
  cost within tolerance, latency recorded per case.

### P12 — Semantic & adversarial corpus `[ ]`

- `[ ] T-120` Build the immutable gold corpus — hundreds of fixtures across the families in Guide §26 / PRD §17.2 /
  research "Edge cases": 12 h vs 24 h, noon/midnight, shared suffix, `until`/`between`/number words, unicode dashes,
  non-breaking spaces, fractions, decimal percentages, thousands separators, the to/by/reduction/operates-at contrast
  set, zero factor, zero grid cap, capacity-relative reserves, distractors containing energy vocabulary, prompt
  injection, schema-looking note text, note reordering, three-note scenarios.
- `[ ] T-121` `scripts/paraphrase_eval.py` — per-model / per-prompt-version scorecard (type match, hours match, numeric
  match, `no_op` accuracy, guardrail pass rate, p50/p95/p99).
  *Acceptance:* labels are hand-verified for every percentage and time case; provisional-policy cases live in a separate
  bucket so an organizer clarification cannot silently move the headline number.

### P13 — Property & metamorphic tests `[ ]`

- `[ ] T-130` Random feasible scenario generator + the invariants in Guide §27.
- `[ ] T-131` Metamorphic properties: more solar cannot raise cost; tightening a feasible reserve or grid cap cannot
  lower it; removing a hard constraint cannot worsen the objective; repeated solves are deterministic within tolerance.

### P14 — Cache, budgets, resource protection `[ ]`

- `[ ] T-140` `cache/request_cache.py` — parser cache keyed on notes + battery context + provider + exact model +
  `PROMPT_VERSION` + `SCHEMA_VERSION`; full-response cache additionally on the canonical request + `OPTIMIZER_VERSION` +
  commit SHA. Cache only guardrail-valid interpretations and replay-valid responses.
- `[ ] T-141` Deadlines (4.5 s soft / 28 s hard), body-size and note-length limits, request and LLM concurrency semaphores.
  *Acceptance:* the "same note, different battery capacity" collision test must miss the cache, not hit it.

### P15 — Observability `[ ]`

- `[ ] T-150` Structured JSON logging with correlation IDs and the field list in Guide §23. Raw notes, prompts, provider
  payloads, and secrets are never logged at INFO.
- `[ ] T-151` Prometheus-style counters and histograms (Guide §23 metric list).

### P16 — Docker & deployment `[ ]`

- `[ ] T-160` Dockerfile per Guide §34 — pinned base, deps installed at build time, non-root user, `HEALTHCHECK` →
  `/health`, no secrets in layers or build args. `.dockerignore` excludes `.git`, venvs, `.env`.
- `[ ] T-161` `scripts/verify_docker.py` — build, run, `/health`, one full `/optimize-energy`, assert replay PASS inside
  the container, and assert that SciPy LP **and** MILP both work in the final image.
- `[ ] T-162` Deploy to the chosen platform (O-03); verify both endpoints from an external network; push an immutable
  tag/digest to the registry (O-04).

### P17 — Warm canary & latency `[ ]`

- `[ ] T-170` Pre-judging canary against the exact production model + prompt version + schema version (separate from
  `/health`, which must never call the provider).
- `[ ] T-171` `scripts/benchmark_latency.py` — external p50/p95/p99. Target p95 ≤ 4.5 s.

### P18 — Demo layer `[ ]`

- `[ ] T-180` `demo/` routes behind `DEMO_MODE`: pipeline trace, 24 h energy chart, constraint bands, validation proof,
  cost comparison (label an infeasible no-storage baseline as infeasible rather than forcing the comparison),
  active-constraint inspector, what-if lab, paraphrase lab, public-case runner, request replay.
  *Constraint:* zero effect on `/optimize-energy`'s schema or latency.

### P19 — CI `[ ]`

- `[ ] T-190` GitHub Actions per Guide §33: ruff → types → unit → property/metamorphic → public integration → adversarial
  fixtures → API contract → secret scan → docker build → run container → `/health` → one full optimize → replay PASS.

### P20 — Docs, video, release freeze `[ ]`

- `[ ] T-200` `README.md` with all 20 items from Guide §41 — clean-environment quickstart, env var **names** only, exact
  model/provider ID, LLM role, guardrail role, solver role, run command, `/health` and `/optimize-energy` curl examples,
  public-sample command plus expected result, Docker pull/run, dependency credits, provisional policies, known
  limitations, secret handling.
- `[ ] T-201` 3-minute video per Guide §42 (tie-break only — but it is the *first* tie-break).
- `[ ] T-202` Release freeze: record model ID, prompt version, schema version, optimizer version, SciPy/HiGHS versions,
  commit SHA, image digest. No changes after this without re-running the full suite.

---

## 7. Test inventory

| Suite | Path | Gate |
|---|---|---|
| Unit | `tests/unit/` | every task |
| Guardrail fixtures | `tests/unit/guardrails/` | P9 |
| Semantic gold corpus | `tests/regression/semantic/` | P12 |
| Public-case regression | `tests/regression/public/` | P7, P11 |
| API contract / error mapping | `tests/integration/api/` | P1 |
| Property & metamorphic | `tests/property/` | P13 |
| Security / injection | `tests/security/` | P12 |
| Container | `scripts/verify_docker.py` | P16 |

Commands (create them in P0):

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
pytest
pytest tests/unit/test_x.py::test_y
ruff check .
python scripts/run_public_cases.py public_cases/sample_cases.json
python scripts/benchmark_latency.py
docker build -t gridwise . && docker run -p 8000:8000 --env-file .env gridwise
```

---

## 8. Release gates

The work is not done until every line here is ticked. Full mechanical list: Guide §44.

```
[ ] /health → 200 {"status":"ok"} externally, with no provider call
[ ] structural 400 / semantic 422 / internal 500 all verified by test
[ ] 10/10 public interpretations correct
[ ] 10/10 public LPs feasible, 10/10 MILPs optimal, cost within 0.01
[ ] LP <= MILP + tol on every regression case
[ ] every returned schedule replays PASS after serialization
[ ] percentage contrast corpus passes (to / by / reduction / operates-at / fractions)
[ ] time corpus passes (AM/PM / noon / midnight / 24 h / until / between / shared suffix)
[ ] factor=0 and grid-cap=0 cases pass
[ ] duplicate-hour and duplicate-note-index model output triggers repair, not silent dedupe
[ ] prompt-injection notes stay data-only
[ ] provider refusal / truncation / 429 / 5xx / timeout are all controlled
[ ] cache keys include battery context + prompt/schema/model/optimizer versions
[ ] p95 <= 4.5 s measured externally
[ ] warm canary succeeds against the exact production model + prompt + schema
[ ] Docker: build, run, health, public sample, LP+MILP inside the image
[ ] no secret in repo, image layers, logs, or responses
[ ] README clean-environment reproduction succeeds
[ ] versions recorded and frozen; video accessible
```

---

## 9. Risk watchlist

| Risk | Where it bites | Guard |
|---|---|---|
| `reduced by` vs `reduced to` inverted | 25 interpretation pts | contrastive prompt examples + gold fixtures (P12) |
| Off-by-one on the end-exclusive window | interpretation + application | explicit examples in the prompt; hours fixtures |
| Capacity-relative reserve computed without battery context | interpretation | D-05 sends the battery object; range check in guardrails |
| Truthiness bug swallowing `factor=0.0` / `max_grid_kwh=0.0` | application (invalid case ⇒ 0 optimization credit) | explicit zero fixtures in P3 and P9 |
| Independent 2-dp rounding breaking the balance equation | every case invalid | D-11 + the P6 reconstruct-then-replay sequence |
| Replay validator sharing a bug with the optimizer | false PASS | D-09: separate module, no shared imports |
| Provider outage / cold structured-output schema | reliability + latency | P10 failure classes, P17 canary, O-02 backup |
| Cache returning a context-wrong directive | correctness | P14 key composition + the collision test |
| Protection limits blocking judge traffic | reliability | generous limits, load-tested in P14 |
| Hidden-test overfitting to public phrasing | interpretation | no public wording in `app/`; the corpus is paraphrase-first |
| Last-minute model / prompt / solver swap | everything | T-202 freeze |

---

## 10. Session log

Append one entry per working session, newest last. Keep entries short and factual.

### 2026-09-18 — Session 1 (planning only)

- Read all six documents in `docs/` end to end: Problem Statement, Participant Guide & Rubric, the 10-case sample pack
  (including `_meta.interpretation_rules` and `_meta.constraint_reminders`), PRD, Implementation Guide, Deep Research report.
- No code written — this was explicitly a planning-only session.
- Created this tracker: locked decisions D-01..D-14, open decisions O-01..O-08, the canonical digest, the file manifest,
  a 21-phase board (T-001..T-202), the test inventory, release gates, and the risk watchlist.
- Found and resolved one cross-document conflict, recorded as D-02: the deep-research report argues a pure LP (signed
  battery variable) is sufficient, while the PRD, Implementation Guide, and CLAUDE.md all mandate LP-assisted MILP with
  the MILP authoritative. Team spec wins; the research doc never overrides it.
- Confirmed from the sample pack that SAMPLE-03 resolves "50% of the battery capacity" against `capacity_kwh=200` → 100
  kWh, which is the concrete justification for sending the battery object to the LLM (D-05).
- Next session starts at `T-001`.

### 2026-09-18 — Session 2 (P0 — scaffolding)

- New working rhythm agreed: one phase per turn, then stop for approval (§0.4). Testing scope narrowed to
  correctness-critical surfaces only (D-15).
- Environment verified: Python 3.14 local with every runtime dependency already installed; Python 3.12 also available
  for the image (D-16). `pytest-asyncio` is *not* installed and was dropped from dev requirements — Starlette's
  `TestClient` covers the API tests without it. Add it back only if a genuinely async test appears.
- `T-001`/`T-002`/`T-003` complete. `ruff check .` clean, `pytest` 2 passed.
- Two unofficial synthetic corpora appeared in `docs/` (`GridWise_Adversarial_Edge_Cases.json`,
  `GridWise_Extended_HiddenLike_Cases.json`). Catalogued in §4.8. They cover a large share of the P1/P9/P12/P13
  fixture work — reuse them rather than authoring fixtures from scratch.
- O-05 and O-06 resolved and implemented as config keys; INV-09/INV-10 in the adversarial pack independently
  corroborate the negative-demand/solar → 422 choice.
- Next session starts at `T-010`.

### 2026-09-18 — Session 3 (P1 — schemas, endpoints, error mapping)

- `T-010`..`T-013` complete. 38 tests green, `ruff check .` clean, live `uvicorn` smoke test passed.
- Built on P0 rather than beside it: `config.Settings` drives the body limit, the oversized-request status (O-05),
  and the negative-energy policy (O-06); `SecretStr` keeps keys out of every error path.
- **The 400/422 split is structural-vs-semantic, and that shapes where each check lives.** Anything expressible in the
  Pydantic model (types, counts, hour set, NaN/Inf, unknown fields) is a 400 by construction. Anything relational
  (initial > capacity, reserve > capacity, negative demand/solar) is deliberately *kept out* of the models so it
  surfaces as 422. Moving a check across that line silently changes the HTTP contract — check the corpus expectations
  before relocating one.
- Adversarial corpus wired straight into the tests: 11 `invalid_request_cases` + 2 `raw_invalid_cases` are asserted
  against their own `expected_http_status`, so the expectation can never drift from the fixture.
- All 10 public and 34 extended `expected_output` bodies validate against `OptimizeResponse`, which is real evidence
  that the directive union and the response model match the organizer's worked examples rather than my reading of them.
- Deliberate non-strictness: numeric fields stay in Pydantic's lax mode, so `"7"` would be accepted as `7`. Rejecting
  it would be more contract-pure, but a false 400 on judge traffic costs far more than accepting a tolerable spelling.
  INV-11 (`"high"`) is still rejected.
- `no_op` wire format explicitly tested — `"structured_adjustment": null` must be *present*, not omitted. An
  `exclude_none` default anywhere in the response path would break the contract silently.
- Known rough edge, deferred to P15: `logging.basicConfig` at INFO makes `httpx`/`uvicorn` noisy. Structured logging
  with per-logger levels replaces it.
- Next session starts at `T-020` (independent replay validator).

### 2026-09-18 — Session 4 (P2 — independent replay validator)

- `T-020`/`T-021` complete. 64 tests green, `ruff check .` clean.
- Builds directly on P1: replay consumes the typed `OptimizeResponse` from P1 (so it validates what actually goes over
  the wire), reads the spec-gap policy from the P0 `Settings`, and raises nothing itself — the service turns a failed
  report into `ReplayInvariantFailure`, the 500 class already defined in P1's error taxonomy.
- **The independence decision cost real duplication and is worth it.** `derive_envelope()` re-implements directive
  composition instead of importing the (not yet written) compiler. Guide §15's pseudocode calls `compile_directives`,
  but doing that would let one buggy composition both build and bless a plan. The duplication is now guarded by an
  AST test that fails if `replay.py` ever imports `app.optimizer`.
- Strong evidence, not just green ticks: all 44 published reference plans (10 public + 34 extended) replay clean at
  **1e-9**, three orders tighter than the internal tolerance and seven tighter than the judge's. That says the envelope
  rules match organizer ground truth exactly, across all six directive types.
- Mutation tests deliberately bypass the P1 response-model validators with `model_construct` where the mutation is one
  the schema itself would reject (negative grid, idle-with-magnitude). Otherwise Pydantic would catch it first and the
  test would prove nothing about replay.
- Replay carries the *reported* battery energy forward rather than its own recomputed value, so one bad hour surfaces
  as a single `state_transition` violation instead of cascading into 23 misleading ones.
- Next session starts at `T-030` (directive compiler) — the second, independent implementation of the same composition
  rules, plus `policies/spec_gaps.py`.
