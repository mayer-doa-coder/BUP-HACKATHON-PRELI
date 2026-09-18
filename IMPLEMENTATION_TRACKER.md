# GridWise — Implementation Tracker

**Purpose:** single source of truth for *what is built, what is next, and why*. This file exists so that work can
resume in a brand-new chat/thread without re-reading the ~6,400 lines of `docs/`.

**Status:** `P0-P18 COMPLETE, P16 DEPLOYED to Azure App Service (P19 dropped; P20 docs/video delegated)`
**Last updated:** 2026-09-18
**Current phase:** P20 — teammates own the README and video; `T-202` release freeze remains
**Next action:** freeze versions (`T-202`) — the deployed URL is `https://gridwise-api.azurewebsites.net` (see §1 and Session 17)

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
| Phase | P20 — Docs, video, release freeze (owned by teammates) |
| Last completed task | `T-180` (P17 + P18 complete; P19 dropped) |
| Next task | `T-202` (release freeze) — `T-200`/`T-201` are with teammates |
| Tests passing | 458 / 458 (+2 `live` deselected), `ruff check .` clean |
| Public cases passing | 10 / 10 and 44 / 44 end-to-end over HTTP; optimization ratio exactly 1.000000 on every known case |
| Endpoint deployed | **yes** — `https://gridwise-api.azurewebsites.net` (Azure App Service, Linux B1, Always On, Southeast Asia) |
| Docker image | built remotely by Azure Container Registry `gridwiseacr50329` (no local daemon needed); running tag `gridwise:1.0.3`, digest `sha256:4a965aed710767a33d183b2a4adc27a921d58fdbd91ebb832f5a3270b2a112b6`, built from commit `7fadf96` |
| Live verification | 44 / 44 public + extended cases; 65 / 65 real-model paraphrase/injection/provisional cases; 13 / 13 invalid-request cases; `verify_contract.py` 104 / 104 against the deployed URL (details in Session 17) |
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
[x] .gitignore                  [x] .dockerignore           [x] Dockerfile
[x] docker-compose.yml          [~] README.md   [x] DOCKER.md               [ ] .github/workflows/ci.yml

app/
[x] main.py                     [x] config.py
[x] api/routes.py               [x] api/errors.py           [x] api/middleware.py
[x] schemas/request.py          [x] schemas/directive.py    [x] schemas/response.py    [ ] schemas/internal.py
[x] llm/base.py                 [x] llm/interpreter.py      [x] llm/prompts.py   [x] llm/schema.py
[x] llm/providers/openai_provider.py  [x] llm/providers/anthropic_provider.py  [x] llm/repair.py
[x] guardrails/directive_validator.py   [x] guardrails/normalizer.py   [-] guardrails/conflict_checks.py
[x] optimizer/compile_directives.py     [x] optimizer/model.py         [x] optimizer/lp_relaxation.py
[x] optimizer/milp_solver.py            [x] optimizer/hybrid_solve.py  [x] optimizer/result.py
[x] validation/replay.py        [x] validation/totals.py
[x] services/optimize_service.py   [x] services/plan_summary.py   [x] services/deadline.py
[x] observability/logging.py    [x] observability/metrics.py  [x] observability/trace.py
[x] observability/record.py
[x] cache/request_cache.py
[x] demo/routes.py              [x] demo/models.py   [x] demo/service.py   [x] demo/page.py
[x] policies/spec_gaps.py       # D-12: cross-midnight, through, single-hour, solar overlap

tests/   unit/ integration/ regression/ security/ property/
scripts/ [x] run_public_cases.py  [x] benchmark_latency.py  [x] verify_docker.py  [x] paraphrase_eval.py
         [x] warm_canary.py
         [x] verify_solver.py  [x] healthcheck.py  [x] semantic_corpus.py
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

### P3 — Directive compiler `[x]`

- `[x] T-030` `optimizer/compile_directives.py` — `CompiledConstraints` (NumPy `effective_solar`, `min_energy`,
  `charge_allowed`, `discharge_allowed`, `grid_upper`, plus `original_solar` / `solar_factor` for the demo layer),
  `ConstraintTrace` provenance per Guide §39, `has_grid_cap` / `forced_idle_hours` helpers, and
  `_assert_compiled_invariants()` raising the new `DirectiveCompilationFailure` (500) rather than clipping.
  Directives are processed in `note_index` order so compilation is deterministic even under an order-sensitive policy.
- `[x] T-031` `policies/spec_gaps.py` — `compose_solar_factors()` (used by the compiler), `expand_window()` (the single
  deterministic statement of the window convention, consumed by the P8 prompt and the P18 paraphrase lab),
  `through_is_end_exclusive()`, `single_hour_window()`, `policy_summary()` for the README and diagnostics.

*Verified:* **the compiler and P2's `derive_envelope` agree on all five arrays across all 44 reference cases** — two
independently written implementations of the same rules reaching the same answer. The comparison was probed to confirm
it is sensitive (a flipped boolean, an `inf`→finite cap, and a 0.001 kWh solar drift are all caught) while tolerating
1e-15 float noise. Composition tests cover reserve `max`, cap `min`, ban union, ban+ban ⇒ forced idle, and differing
solar factors ⇒ `min(factor)` + ambiguity flag; `factor=0.0` / `max_grid_kwh=0.0` survive and are recorded in the trace;
a reserve above capacity fails closed. Window tests assert the canonical §04.2 examples separately from the provisional
policies. 106 tests green, `ruff check .` clean.

### P4 — Shared LP/MILP model `[x]`

- `[x] T-040` `optimizer/model.py` — one variable layout (`g, s, c, d, E, yc, yd` = 168 vars, 49 equality rows,
  72 inequality rows) and one constraint builder for both stages (Guide §12). `OptimizationModel` carries the
  objective, both constraint blocks, bounds, and the `integrality` vector, plus `scipy_bounds()`, `cost_of()`,
  `split()`, and `residuals()`. **There is no `stage` parameter** — the LP and MILP cannot be handed different
  problems, which is what makes `LP_cost <= MILP_cost` meaningful. Directives enter purely as bounds; the module never
  inspects a directive.

*Verified:* all 44 published reference schedules are feasible points of the model as built (equality, inequality, and
bound residuals all below 1e-9) and the objective reproduces every published `total_cost_bdt` to 1e-6. The residual
check was probed to confirm it reacts (a +5 kWh grid nudge and a +12 kWh capacity breach are both measured exactly).
Directive-to-bound tests cover solar upper bound, grid cap, reserve floor, and bans pinning **both** the amount and its
mode variable. 122 tests green, `ruff check .` clean.

*Solver probe (not yet a committed test — P5 formalizes it):* driving these matrices through
`linprog(method="highs")` and `scipy.optimize.milp` solves all 44 cases, `LP <= MILP` holds everywhere, and the MILP
objective equals the published optimum exactly on every one. The model is sound before a single solver module exists.

### P5 — Solvers `[x]`

- `[x] T-050` `optimizer/lp_relaxation.py` — `LpStatus` / `LpResult` / `solve_lp_relaxation()`. Solver problems become
  **statuses, never exceptions**, so "impossible scenario" stays distinguishable from "solver broke".
- `[x] T-051` `optimizer/milp_solver.py` — `MilpStatus` / `MilpResult` / `solve_milp()`, capturing `mip_gap` and
  `mip_dual_bound` for diagnostics. A time-limited but feasible incumbent is *usable* (see the log note).
- `[x] T-052` `optimizer/hybrid_solve.py` — `screen_baseline_feasibility()` (the pre-LLM screen) and `hybrid_solve()`,
  returning `SolveOutcome` with a four-way `SolveStatus`: `OK`, `BASELINE_INFEASIBLE` (→ 422),
  `DIRECTIVE_INFEASIBLE` (→ P10 reparse), `SOLVER_FAILURE` (→ 500). Three invariants gate every solution:
  `LP <= MILP + tol`, model residuals within 1e-6, and no hour both charging and discharging.

*Verified:* **all 44 reference cases reach the published optimum exactly**, MILP optimality proven on every one,
`LP <= MILP` everywhere, directive bounds binding the *solved* plan rather than just the published one, and no
simultaneous charge/discharge anywhere. Edge cases: zero-capacity battery, zero charge rate, a completely rigid
battery, negative tariff (solves, cost goes negative, stays bounded), `factor=0.0`, both bans on one hour, and a zero
grid cap (→ `DIRECTIVE_INFEASIBLE`). Failure injection confirms a crashing solver surfaces as `SOLVER_FAILURE` rather
than a traceback, and an artificially inflated LP bound trips the invariant. 144 tests green, `ruff check .` clean.

*Latency headroom:* baseline screen p50 3.3 ms, LP 3.0 ms, MILP 15.6 ms; worst observed baseline + hybrid total
**39 ms** against the 4,500 ms budget. The LLM call will be the only meaningful latency cost in the pipeline.

### P6 — Canonicalizer, response builder, summary `[x]`

- `[x] T-060` `optimizer/result.py` — `build_hourly_plan()`. Eps-canonicalizes, rounds **only the independent
  decisions** (charge, discharge, solar used), then *derives* `battery_energy_after_kwh` sequentially and `grid_kwh`
  from the balance equation, so the balance closes by construction. Rounding overshoot within
  `BOUND_REPAIR_TOLERANCE` (1e-6) is clipped; anything larger fails closed as `SolverFailure`, as does activity in a
  banned hour, simultaneous charge/discharge, and a schedule the response model cannot represent.
- `[x] T-061` `services/plan_summary.py` — `build_plan_summary()`, adaptive: it does not claim the battery shifted
  energy on a day when the battery never moved, and it counts non-relevant notes separately.
- `[x] T-062` `services/optimize_service.py` rewritten around the real pipeline: `validate` → `screen_feasibility`
  → `interpret` (P8 seam) → `solve_and_build`. `SolveStatus` becomes HTTP outcomes here and nowhere else
  (`BASELINE_INFEASIBLE` → 422, `DIRECTIVE_INFEASIBLE` → new `DirectiveInfeasible` 500 until P10's reparse lands,
  `SOLVER_FAILURE` → 500). The response is serialized, **parsed back**, and replayed before it is returned.

*Verified:* all 44 reference cases build a replay-clean response at the published optimal cost — optimization quality
ratio `min(1, optimal/team)` is **exactly 1.000000 on every case**. Corrupting the solver's own `E` or `g` blocks
changes nothing in the response (both are re-derived); a mode flag set with a zero amount still yields `idle`; idle
hours carry an exact `0.0`. Deterministic across repeated solves. Over HTTP with a stub interpreter the endpoint
returns 200 with exactly the seven fields, and the parsed body replays clean. 173 tests green, `ruff check .` clean.

*Latency:* screen + solve + build + replay is p50 **23.5 ms**, max 62 ms.

> **The precision ladder is load-bearing, not decoration.** Rounding the independent decisions to 6 dp is enough to
> break a valid plan when the inputs carry long decimals: the rounded battery movements stop cancelling over the day
> and the end-of-day balance drifts ~1e-6, past the 1e-7 internal tolerance. The builder therefore tries
> `(6, 9, None)` decimal places and keeps the first that replays clean. A regression test reproduces the failure
> deliberately. Do not collapse the ladder to a single rung.

### P7 — Public-case optimizer regression (no LLM) `[x]`

- `[x] T-070` `scripts/run_public_cases.py` — two modes from one runner: **local** (ground-truth directives straight
  into the compiler and solvers, isolating the deterministic half) and **`--endpoint URL`** (POSTs to a running
  service, exercising the full LLM path — reused by P11 and P16). Reports interpretation / validity / cost gap /
  latency per case, `--extended` adds the 34-case pack, `--json` emits machine-readable output, and it exits non-zero
  on any failure so it works as a CI gate. A path bootstrap lets it run from a clean checkout without installation.
- `[x]` `app/validation/interpretation_match.py` — compares an interpretation against a reference on exactly what the
  organizers check (relevance, type, hours, numerics within 0.01) and deliberately **ignores explanation wording**.

*Verified:* `python scripts/run_public_cases.py public_cases/sample_cases.json` → 10/10, exit 0; `--extended` → 44/44.
The comparator is tested in both directions: it accepts every reference interpretation and reworded explanations, and
detects a wrong type, wrong hours, an inverted factor, a flipped `applies`, and a missing entry. The runner reports a
broken case rather than dying on it.

### P8 — LLM interpreter `[x]`

- `[x] T-080` `llm/base.py` — `StructuredOutputProvider` protocol, `ProviderResponse`, and the **failure taxonomy the
  P10 retry policy branches on** (`ProviderTimeout`, `ProviderUnavailable`, `ProviderRateLimited(retry_after)`,
  `ModelRefusal`, `ModelTruncated`, `MalformedModelOutput`, `ProviderNotConfigured`). Two adapters —
  `llm/providers/openai_provider.py` (Chat Completions + `json_schema` strict) and
  `llm/providers/anthropic_provider.py` (forced tool call as a typed output channel) — behind
  `llm/providers/__init__.build_provider()`, selected by `LLM_PROVIDER`. **O-01 is still open**: both adapters exist,
  but no provider/model/key is pinned yet.
- `[x] T-081` `llm/prompts.py` — system prompt (taxonomy, untrusted-data rule, one-entry-per-note, time rules, factor
  contrast set, reserve/grid rules, relevance, never-invent) plus a provisional-policy block generated from the
  config. `build_user_payload()` sends the battery object and the notes as escaped JSON — and **nothing else**.
- `[x] T-082` `llm/interpreter.py` — one structured call for all notes, `parse_envelope()` for structural unwrapping,
  `coerce_to_canonical()` as the shape gate, `build_interpreter()` factory. `llm/schema.py` builds the tagged-union
  JSON Schema with the entry count pinned to the note count.
- `[x]` Wired into `OptimizeService`, built once per service (pooled HTTP client), released on app shutdown via a
  FastAPI lifespan. New config: `LLM_BASE_URL`, `LLM_MAX_OUTPUT_TOKENS`, `LLM_TEMPERATURE`, `BACKUP_LLM_BASE_URL`.

*Verified:* 48 offline tests. Prompt tests assert the contrast set verbatim, the untrusted-data clause, determinism,
and — importantly — that the payload contains **no** `demand_kwh` / `solar_kwh` / `tariff` (D-05). Schema tests check
all six variants, the pinned entry count, bounds, illegal combinations being unrepresentable, and a drift guard tying
the schema's fields to the canonical Pydantic models. Both adapters are driven through `httpx.MockTransport` for 429
(with `retry-after`), 5xx, 401, timeout, refusal, truncation, and malformed body. Full-chain integration tests run a
stubbed provider through the real prompt, schema, compiler, solvers, canonicalizer and replay — including a
prompt-injection note, which reaches the model as data and cannot add `battery_shutdown` to the schema.
`tests/integration/test_live_provider.py` is the opt-in warm canary (`pytest -m live`), deselected by default.

### P9 — Deterministic guardrails `[x]`

- `[x] T-090` `guardrails/directive_validator.py` — `GuardrailCode` (26 stable classes), `GuardrailFailure`,
  `GuardrailReport`, `validate_directives(raw_items, request)`. Runs on the **raw payload** before any Pydantic model
  exists, because the union would reject an unknown type and a duplicate hour with the same opaque error and the
  distinction is what P10 routes on. Collects *all* failures, not the first. Ends with the canonical models as a
  backstop, so a missed check still fails closed.
- `[x] T-091` `guardrails/normalizer.py` — `sort_entries_by_note_index`, `sort_hours`, `normalize_negative_zero`,
  `normalize_explanation`. Each refuses to act where acting would hide a fault: entries are not reordered when an
  index is duplicated or non-integer, and hours are not sorted when they contain duplicates.
- `[-] guardrails/conflict_checks.py` — **dropped, not deferred.** Every cross-field rule that exists (reserve vs
  capacity, `applies` vs type, adjustment shape vs type) is scenario-local and lives in the validator; ambiguity
  flags are already produced by the compiler and feasibility is the LP's job. A separate module would have been
  filler. Recorded here so a future session does not "restore" it.

*Verified:* 39 tests. All 44 reference interpretations pass **untouched** (no normalization fired — a false rejection
or a needless rewrite would both be defects). Nine `GR-*` fixtures from the adversarial pack are asserted to fail with
the exact expected code, plus GR-09 (missing mapping) and GR-10 (duplicate index). Hostile payloads covered:
`note_index` as a string / as `True` / out of range, `applies` as a string, adjustment as a list, hours as a string /
empty / fractional / boolean, extra adjustment keys, NaN and Inf in every numeric field. Explicit no-repair tests
prove duplicate hours are never deduplicated, factors never clipped, hours never clamped, and unknown types never
coerced. `factor=0.0` and `max_grid_kwh=0.0` survive.

> **Two deliberate policy calls, both documented in code.** (1) *Unsorted but unique* hours are **sorted**, not
> rejected — GR-02 permits either, a window is a set so ordering carries no information, and rejecting would spend a
> repair round trip on a difference that cannot change the constraint. (2) A missing or non-string `explanation` is
> filled rather than rejected: it is free text the rubric explicitly does not match, so failing a case over it trades
> real points for nothing. This is a fifth normalization beyond Guide §9's four, taken knowingly.

### P10 — Repair, retry, feasibility-aware reinterpretation `[x]`

- `[x] T-100` `llm/repair.py` — `InterpretationRunner` with per-class routing (Guide §20): transport 5xx/timeout →
  short-backoff retry; 429 → honor `retry_after` when it fits, otherwise the backup provider, otherwise stop;
  refusal/truncation → immediate bounded retry (no backoff — not a load problem); schema violation → repair call
  carrying the structural problems; guardrail violation → focused semantic repair naming the broken rules.
  `RepairReason` and `InterpretationRun` carry the telemetry P15 needs. `services/deadline.py` provides the monotonic
  budget; every attempt is capped by `LLM_MAX_ATTEMPTS` *and* by whether it can still land.
- `[x] T-101` `reinterpret_for_feasibility()` plus `OptimizeService._solve_with_feasibility_retry()`: on
  `DIRECTIVE_INFEASIBLE`, exactly one focused reinterpretation that re-reads the original notes and is explicitly told
  not to weaken, drop or soften anything. If the second reading is also infeasible, the **first** outcome is reported —
  a second wrong answer is not an improvement.
- `[x]` Repair prompts live with the other prompts in `llm/prompts.py`; `build_user_payload(request, repair_note)`
  appends feedback without ever replacing the operator's own words.

*Verified:* 25 tests. Every failure class is asserted to produce its own `RepairReason` **and** the right second-call
payload — a transport retry carries no corrective text, a schema repair carries the structural problems, a semantic
repair names the broken rule codes and re-reads the notes. Budget tests: an exhausted deadline makes zero calls, a
retry too large for the remaining budget is skipped, the attempt timeout never exceeds what is left, and
`LLM_MAX_ATTEMPTS=1` disables retrying entirely. End-to-end, an infeasible first interpretation earns exactly one
reinterpretation and the corrected reading reaches the response; a twice-infeasible one raises `DirectiveInfeasible`;
a feasible first interpretation is never reinterpreted. Replay failure still triggers **no** retry (P6 test).

> **A repair never supplies the answer.** Feedback states what was structurally wrong or which rule broke, never what
> the directive should have been. Handing over the expected value would make the pipeline look correct while the
> model's actual understanding stayed wrong — and hidden cases would then fail exactly where it matters.

### P11 — End-to-end public regression `[x]`

- `[x] T-110` `tests/regression/test_end_to_end.py` — all 10 public and 34 extended cases through the **real HTTP
  endpoint**, graded the way the judge grades: interpretation semantics, replay validity, recalculated cost, latency.
  The model is a deterministic stub that **asserts it received the production prompt and schema**, so the suite cannot
  pass with the interpreter bypassed.

*Verified:* 11 tests. 44/44 cases return 200 with exactly the seven canonical fields, correct interpretation,
replay-clean plans and the published optimal cost; `no_op` keeps its explicit `null`; repeated requests are byte
identical; `/health` stays available alongside traffic; the 400/422 mapping still holds with a live interpreter
behind it. Two spend guards asserted: a **structurally invalid request never reaches the model**, and neither does a
**baseline-infeasible scenario**. Optimization ratio `min(1, optimal/team)` is exactly **1.000000 on all 44**.

### P12 — Semantic & adversarial corpus `[x]`

- `[x] T-120` `scripts/semantic_corpus.py` — loads the corpus into three **separately scored buckets**: `semantic`
  (58 paraphrases across 7 groups), `adversarial` (5 injection notes), `provisional` (spec-gap cases). Each case
  carries its own battery context (a percentage reserve resolves against capacity) and builds a complete, feasible
  `OptimizeRequest` from a synthetic 24-hour profile that never reaches the model.
- `[x] T-121` `scripts/paraphrase_eval.py` — per-bucket scorecard (exact match, directive-type match, guardrail pass
  rate, `no_op` relevance, p50/p95 latency), stamped with the prompt/schema/model versions that produced it. The
  provisional bucket is **excluded from the pass threshold** by design.
- `[x]` `tests/security/test_prompt_injection.py` — the three structural defence layers.

*Verified:* 35 tests, all offline. Corpus integrity: every canonical answer passes **our own** guardrails and compiles
into constraints (otherwise the target itself would be wrong), the synthetic scenarios are schedulable, and no corpus
note echoes published sample wording. Policy agreement: the pack's provisional answers for cross-midnight (`[0,1,23]`)
and single-hour (`[16]`) match `expand_window`/`single_hour_window` exactly, and AMB-03's "most restrictive" rule
matches the compiler. **The scorer is proven able to fail** — it detects an inverted factor, an off-by-one window, a
guardrail rejection, and survives a provider outage mid-run. Injection: each of the 5 notes stays a JSON-escaped
string value, cannot widen the schema, and its *genuine* instruction is still honoured; a model that obeys an
injection is refused by the guardrail; a legitimate note containing "ignore"/"override"/"system" is **not** filtered.

> **No keyword filtering, deliberately.** A real operator note can contain "ignore", "system" or "override", and
> discarding a genuine directive because it looked suspicious would lose the case outright. Defence is structural:
> escaped data block, explicit data-boundary instruction, closed schema, deterministic guardrails.

*Still needs credentials (O-01):* the actual paraphrase accuracy of the real model. Everything the measurement
depends on is verified; the measurement itself is one `python scripts/paraphrase_eval.py` away.

### P13 — Property & metamorphic tests `[x]`

- `[x] T-130` `tests/property/test_optimizer_properties.py` — a **seeded** random scenario generator (reproducible
  from the printed seed; `random.Random`, no new dependency) over 40 scenarios including negative tariffs,
  zero-capacity batteries and zero rate limits. Invariants per Guide §27: replayable plan, no simultaneous
  charge/discharge, `LP <= MILP`, every compiled bound respected, deterministic solving.
- `[x] T-131` Metamorphic relations: more solar never costs more; reducing solar never costs less; a grid cap pinned
  to the unconstrained peak never costs less; a reserve floor the plan already meets never costs less; removing a ban
  never costs more; a `no_op` changes nothing; **shuffling the request's hour order changes nothing**. Plus degenerate
  batteries (absent, pinned full, starts empty, cannot charge, cannot discharge) and an all-zero scenario.

*Verified:* 18 tests. The metamorphic constraints are constructed to be **feasible by construction** (pinned to the
unconstrained solution), because an arbitrary invented constraint can make a scenario infeasible and the property then
simply does not apply — a lesson carried over from P5.

> **This phase found a real, score-affecting bug.** `scipy.optimize.milp` inherits HiGHS's default 1e-4 relative MIP
> gap, so it stopped at a near-optimal solution *and still reported success*: adding a constraint appeared to lower
> the optimal cost, which is impossible for nested feasible sets. Now pinned to exact optimality with
> `MILP_RELATIVE_GAP=0.0`, with a regression test asserting `mip_gap == 0` and MILP == LP bound.

### P14 — Cache, budgets, resource protection `[x]`

- `[x] T-140` `cache/request_cache.py` — `TtlLruCache` (bounded LRU + TTL, lock-guarded, disabled cleanly at size 0),
  `parser_cache_key()`, `response_cache_key()`, `canonical_request_json()`. **The parser key hashes the literal
  prompt text** rather than a hand-listed set of fields, so every battery field, the note wording, the note order and
  any prompt edit necessarily change it — a field cannot be forgotten. Versions are hashed separately so a
  `PROMPT_VERSION` bump invalidates even when the rendered text is unchanged. Segments are length-prefixed, so
  `("ab","c")` and `("a","bc")` cannot collide.
- `[x] T-141` `ConcurrencyLimitMiddleware` — request-level semaphore that **queues rather than rejects**, plus a
  separate LLM semaphore inside `InterpretationRunner` (the provider has its own quota). `/health` bypasses the gate
  entirely. The middleware **starts the `Deadline` before queueing** and the route passes it into the service, so time
  spent waiting counts against the same 30 s the judge allows; a slot that cannot be had in budget yields a controlled
  503 `service_busy`. Body-size and note-length limits were already in place from P1.

*Verified:* 42 tests. Key correctness is the bulk of it: **all five** battery fields change the parser key (not just
capacity — all five reach the prompt), as do note text, note order, provider, model, prompt and schema versions, and a
prompt edit made *without* a version bump. The 24-hour matrix correctly does **not** affect the parser key (it never
reaches the model), while `scenario_id` and tariffs **do** affect the response key, and shuffled hours do not. Nothing
invalid is ever cached: guardrail failures, provider outages and infeasible interpretations all leave both caches
empty. A corrected interpretation from the feasibility repair replaces the cached one. LLM concurrency is capped
(peak ≤ 2 under 6 parallel requests), `/health` answers while the optimizer is saturated, and a saturated service
returns 503 rather than overrunning the timeout.

### P15 — Observability `[x]`

- `[x] T-150` `observability/logging.py` — `JsonLogFormatter` (one JSON object per line, `extra` fields merged),
  a **context-local** correlation ID, `QuietThirdPartyFilter`, and `redact_note()` / `redact_model_output()` which
  finally honour the `LOG_RAW_OPERATOR_NOTES` / `LOG_LLM_RAW_OUTPUT` flags defined back in P0 and unused until now.
  Replaces P1's `logging.basicConfig` placeholder.
- `[x] T-151` `observability/metrics.py` — a small Prometheus-compatible registry (Counter / Gauge / Histogram plus
  text exposition) covering the Guide §23 list, with `/metrics` on a **separate router** gated by `METRICS_ENABLED`.
  `observability/record.py` is the single bridge from pipeline results to trace and metrics;
  `observability/trace.py` holds the per-request `RequestTrace`.

*Verified:* 33 tests. Leak checks first: a note is redacted to a stable hash plus length, model output likewise, a
traceback never reaches a log line, and a full request's logs are asserted to contain none of its note text. Metrics
are proven to actually move under real traffic (request counters by status, duration histograms, LP/MILP timers, cache
hit/miss), the active gauge returns to zero, `/metrics` exposes the registry, and it can be switched off. The trace is
asserted to carry the Guide §23 diagnostics end to end (provider, model version, attempts, all three solver statuses,
validator status, versions), and a failure stamps its code.

> **No new dependency.** `prometheus_client` is not installed, and adding a package for three metric types would mean
> another wheel to pin and re-verify inside the image. The text exposition format is stable and the registry is ~120
> lines, so this stays swappable if that trade ever changes.

> **Latency buckets are chosen around the scored thresholds** — 4.5 s (internal target) and 5 s (full-credit cutoff)
> are explicit bucket bounds, so p95 reads against the rubric directly instead of being interpolated.

### P16 — Docker & deployment `[x]`

- `[x] T-160` **Pulled forward at the user's request (session 11)** — `Dockerfile` (pinned `python:3.12-slim-bookworm`,
  deps installed before source for layer caching, non-root uid 10001, `HEALTHCHECK` → `/health`, `$PORT` honored for
  Azure, no secrets in layers or build args), `docker-compose.yml`, and `DOCKER.md` (build, run, env var names,
  registry push, Azure Container Apps **and** App Service recipes, security checklist, troubleshooting).
- `[x] T-161` `scripts/verify_docker.py` — builds, runs, waits for `/health`, posts a real public case, **replays the
  returned plan**, then asserts non-root and no baked-in credentials. `scripts/verify_solver.py` runs **inside the
  image at build time** and fails the build if SciPy cannot actually solve an LP and a MILP;
  `scripts/healthcheck.py` reads `$PORT` so a platform-assigned port cannot look like a dead service.
  **Not yet executed:** no Docker daemon on the authoring machine — see the session log.
- `[x] T-162` Deployed to Azure App Service (Web App for Containers) — see Session 17 for the resource names, the
  digest-pinned image reference and the verification results. Both endpoints verified from outside Azure.
  `scripts/verify_docker.py` (T-161) has **still never been executed** — the image was built by ACR, not locally.

### P17 — Warm canary & latency `[x]`

- `[x] T-170` `scripts/warm_canary.py` — runs the exact production model, prompt version and schema version against
  three canary cases (the percentage-direction contrast, a window, a `no_op` distractor), checks credentials, schema
  parsing, guardrails **and** semantics, reports cold-vs-warm latency, and prints the release record to freeze.
  Separate from `/health` by design.
- `[x] T-171` `scripts/benchmark_latency.py` — external p50/p95/p99 with warm-up, optional concurrency, failure
  reporting, and the result mapped onto the rubric's latency bands (≤5 s = 3/3).

*Verified against the real configured model:* the canary **passes** — all three cases correct, warm p95 **1.9 s**
against a 4.5 s budget. It also proved its worth immediately by catching two real defects (see the session log).

### P18 — Demo layer `[x]`

- `[x] T-180` `demo/models.py` (demo-only types, never the canonical ones), `demo/service.py` (builds the views from
  a **real** pipeline run), `demo/routes.py` (`/demo`, `/demo/analyze`, `/demo/what-if`, `/demo/paraphrase`,
  `/demo/public-cases`, `/demo/config`, `/demo/sample-scenario`), `demo/page.py` (a self-contained dashboard).
  Covers the pipeline trace, 24-hour chart, constraint bands, validation proof, active-constraint inspector,
  honest cost comparison, what-if lab, paraphrase lab and the public-case runner.

*Verified:* 17 tests. The judged contract is unchanged with the demo enabled — same seven fields, same cost — and the
demo's numbers are asserted to **equal** the canonical response rather than being recomputed. Demo routes are absent
by default, stay out of the OpenAPI document, and the page is asserted to reference no CDN.

> **Gating uses both flags, deliberately.** Demo routes need `DEMO_MODE=true` **and** `JUDGE_MODE=false`, so a
> deployment that accidentally ships with `DEMO_MODE` set still exposes nothing to the judge. A warning is logged if
> `DEMO_MODE` is on while `JUDGE_MODE` is too, so the combination is never silently ignored. This finally gives both
> P0 flags a purpose.

> **The dashboard has no CDN dependency.** Charts are inline SVG drawn from the same JSON the API returns, because a
> container may have no outbound internet and a demo that loses its chart library in front of a reviewer is worse
> than no demo.

### P19 — CI `[-]` DROPPED

- `[-] T-190` GitHub Actions. **Dropped at the user's request (session 15); not deferred.**
  The checks the pipeline would have run all exist and are runnable locally, so nothing is lost but the automation:
  `ruff check .`, `pytest` (458 tests), `python scripts/run_public_cases.py`, `python scripts/verify_docker.py`,
  `python scripts/warm_canary.py`. Re-adding CI later means wiring those five commands into a workflow file — no
  code changes. Guide §33 lists CI as recommended, not as a scored requirement; the rubric scores the endpoint,
  the artefacts and the documentation.

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
[x] /health → 200 {"status":"ok"} externally, with no provider call
[ ] structural 400 / semantic 422 / internal 500 all verified by test
[x] 10/10 public interpretations correct (also verified live, real model)
[x] 10/10 public LPs feasible, 10/10 MILPs optimal, cost within 0.01 (live: max cost gap 0 across all 44)
[ ] LP <= MILP + tol on every regression case
[ ] every returned schedule replays PASS after serialization
[ ] percentage contrast corpus passes (to / by / reduction / operates-at / fractions)
[ ] time corpus passes (AM/PM / noon / midnight / 24 h / until / between / shared suffix)
[ ] factor=0 and grid-cap=0 cases pass
[ ] duplicate-hour and duplicate-note-index model output triggers repair, not silent dedupe
[x] prompt-injection notes stay data-only (live model: ADV-01..05 all 5/5)
[ ] provider refusal / truncation / 429 / 5xx / timeout are all controlled
[ ] cache keys include battery context + prompt/schema/model/optimizer versions
[x] p95 <= 4.5 s measured externally (44 cases from a non-Azure client: median 2.8 s, p95 3.2-3.5 s, max 4.1 s; the FIRST call after a restart is slower, see Session 17)
[ ] warm canary succeeds against the exact production model + prompt + schema
[ ] Docker: build, run, health, public sample, LP+MILP inside the image
[ ] no secret in repo, image layers, logs, or responses
[ ] README clean-environment reproduction succeeds
[ ] versions recorded and frozen; video accessible
[x] scripts/verify_contract.py passes against the DEPLOYED URL (not just localhost) — 104/104 warm, run 2026-09-18
```

**The last gate is the submission gate.** `scripts/verify_contract.py --base-url <deployed>` is a
black-box audit of exactly what the judge sees: one origin serving both endpoints, the exact
`/health` body, the exact Section 10 response shape with no extra fields, the closed directive
taxonomy, internal consistency of every number against the returned plan, the 400/422/500 error
mapping, and the absence of any secret or stack trace in an error body. It imports nothing from
`app`, so it cannot be fooled by a bug shared with the implementation. Exit code 0 means
conformant.

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

### 2026-09-18 — Session 5 (P3 — directive compiler and spec-gap policies)

- `T-030`/`T-031` complete. 106 tests green, `ruff check .` clean.
- Written from the Problem Statement §5.3 rules rather than by copying P2's `derive_envelope`, and with a different
  internal structure (NumPy arrays + provenance, versus plain lists). **The two now agree on every array across all 44
  reference cases** — that agreement is the real payoff of the P2 independence decision, and it is now a standing test.
- Extends P1's error taxonomy with `DirectiveCompilationFailure` (500). Reaching it means a guardrail admitted
  something it should have rejected, so it fails closed instead of clipping a value into range.
- I probed the cross-check for sensitivity before trusting it: a flipped boolean, an `inf`→finite cap, and a 0.001 kWh
  solar drift are all detected, while 1e-15 float noise is tolerated. A comparison that cannot fail proves nothing.
- **Known tension between D-09 and D-12, resolved deliberately:** the min-factor rule now exists in two places
  (`spec_gaps.compose_solar_factors` and `replay._compose_solar_factor`). D-12 wants policy isolated; D-09 wants the
  validator independent. The *policy value* is still single-sourced in config, so an organizer clarification remains a
  one-value change and both implementations follow it. Only a wholly new policy kind would need two edits. Do not
  resolve this by making replay import `app.policies` — the cross-check test is what keeps them honest.
- `expand_window()` is policy code with no production caller yet; it lands here because this is where the four
  provisional policies belong, and P8's prompt rules plus P18's paraphrase lab are generated from it. Tests separate
  the canonical §04.2 examples (never change) from the provisional ones (change if organizers clarify).
- Judgement call: a degenerate window (`expand_window(14, 14)`) returns `[]` rather than guessing "the whole day".
  Inventing 24 hours of constraint from an ambiguous phrase is the more expensive error.
- Next session starts at `T-040` (shared LP/MILP model): one variable layout and one constraint builder feeding both
  the relaxation and the authoritative MILP.

### 2026-09-18 — Session 6 (P4 — shared LP/MILP model)

- `T-040` complete. 122 tests green, `ruff check .` clean.
- Direct continuation of P3: `build_model(request, compiled)` takes the `CompiledConstraints` the compiler produces,
  and every directive reaches the solver as a **bound**. `model.py` never inspects a directive, so the taxonomy and
  the mathematics stay on opposite sides of a clean seam.
- **No `stage` parameter, deliberately.** LP and MILP share one objective, one `a_eq`/`b_eq`, one `a_ub`/`b_ub`, and
  one set of bounds; the only difference is whether `integrality` is applied. If the two stages could be built
  separately, `LP_cost <= MILP_cost` would compare two different problems and the invariant would be worthless.
- Verified against organizer data rather than my own arithmetic: all 44 published reference schedules are feasible
  points of the model (residuals < 1e-9) and the objective reproduces every published cost to 1e-6. As in P3, I probed
  the check for sensitivity first — a +5 kWh grid nudge and a +12 kWh capacity breach are both measured exactly.
- A ban pins **both** `c[h]` and `yc[h]` to zero (not just the amount). Leaving `yc` free would let the relaxation hold
  fractional permission to charge, which is harmless for the objective but muddies the LP diagnostics P5 depends on.
- Ran an out-of-band solver probe to de-risk P5: `linprog(method="highs")` and `scipy.optimize.milp` solve all 44
  cases, `LP <= MILP` holds everywhere, and the MILP objective equals the published optimum on every case. So the
  matrices are right *before* any solver module exists; P5 turns that probe into committed regression tests.
- Next session starts at `T-050`/`T-051`/`T-052`: LP relaxation (including the pre-LLM baseline feasibility screen),
  the authoritative MILP, and the hybrid orchestration that asserts the `LP <= MILP + tol` invariant and solver status.

### 2026-09-18 — Session 7 (P5 — solvers)

- `T-050`/`T-051`/`T-052` complete. 144 tests green, `ruff check .` clean. The P4 solver probe is now committed
  regression coverage.
- Consumes P3 and P4 unchanged: `hybrid_solve` compiles (P3), builds (P4), solves, and checks. Nothing earlier needed
  editing, which is the payoff of keeping the compiler free of solver concerns and the model free of directive logic.
- **Failures are statuses, not exceptions.** `SolveStatus` has four values because the pipeline needs three different
  *responses* to failure: a baseline-infeasible scenario is a 422, a directive-infeasible one earns a bounded semantic
  reparse in P10, and a solver fault is a 500. Raising a single exception would have collapsed that distinction and
  forced the service to parse error strings. P6/P10 consume the enum.
- **A time-limited but feasible MILP incumbent is accepted** (`FEASIBLE_NOT_PROVEN`), with `proven_optimal=False`
  recorded. Reasoning from the rubric: a valid, slightly suboptimal plan still earns the 25 directive-application
  points and partial optimization credit, whereas a 500 earns nothing on that case. Validity is never traded away —
  the independent replay still has the final say. Guide §12.2's "require optimal" is the happy path, not the only one.
- **Why MILP-infeasible-after-feasible-LP is a `SOLVER_FAILURE`, not a directive problem:** any relaxed solution that
  charges and discharges in the same hour can be rewritten as the net movement, with identical energy balance, battery
  state, and cost, and within the same rate limits. So a feasible relaxation always implies a feasible integral
  solution here. Reaching that branch means the model or the solver is wrong. The same argument explains the observed
  **zero LP→MILP gap on all 44 cases**: the binaries buy an *expressible* schedule (one `battery_action` per hour),
  not a cheaper one. That is a property of this problem, not a shortcut — the MILP is still solved and still returned.
- One test of mine was wrong, not the code: an invented 120 kWh evening cap genuinely makes SAMPLE-01 infeasible, so
  the monotonicity property did not apply. Replaced with tightenings that are known-feasible (the organizers' own
  directives, and a cap pinned to the unconstrained peak). Also renamed a test whose name claimed "infeasible" while
  it asserted the opposite.
- Solve path measured at ~39 ms worst case end to end, so the latency budget is essentially all LLM.
- Next session starts at `T-060`/`T-061`/`T-062`: eps-canonicalization, per-hour action derivation, sequential state
  reconstruction, 6–8 decimal serialization, parse-back, deterministic `plan_summary`, and wiring the service so the
  P2 replay validator finally guards a real response.

### 2026-09-18 — Session 8 (P6 — canonicalizer, response builder, service wiring)

- `T-060`/`T-061`/`T-062` complete. 173 tests green, `ruff check .` clean. Every phase since P1 is now connected: a
  request validated by P1's schemas is screened by P5, compiled by P3, solved through P4/P5, canonicalized here, and
  cleared by P2's replay before it can leave.
- **The rounding trap in Guide §14 is real, and my own replay validator caught it.** Rounding each field independently
  to 6 dp breaks a valid plan on inputs with long decimals: the rounded battery movements no longer cancel over 24
  hours, so the end-of-day balance drifts ~1e-6 and the battery clips capacity — both past the 1e-7 internal
  tolerance. Fixed structurally: only charge, discharge and solar-used are rounded, while `battery_energy_after_kwh`
  and `grid_kwh` are *derived* from them, and the builder walks a `(6, 9, None)` precision ladder, keeping the first
  rung that replays clean. A test reproduces the 6 dp failure on purpose so the ladder cannot be quietly removed.
- Corrupting the solver's `E` or `g` blocks provably changes nothing in the response — proof that the state and grid
  values really are re-derived rather than copied out of the solution vector.
- **Fails closed rather than clipping.** Overshoot inside 1e-6 is a rounding artifact and is clipped; anything larger,
  plus activity in a banned hour or simultaneous charge/discharge, raises `SolverFailure`. Silently zeroing a banned
  hour would have produced a valid-*looking* plan that hides a solver fault.
- One real robustness gap surfaced through a bad test of mine: a reconstruction that drives the battery negative threw
  a raw Pydantic `ValidationError` into the generic 500 handler. Now wrapped as a classified `SolverFailure` with a
  sanitized message, so the failure is diagnosable rather than anonymous.
- Added `DirectiveInfeasible` (500) so an impossible *interpretation* stays distinguishable from a solver fault all the
  way to the HTTP layer. P10 inserts its bounded reparse in front of it. Removed `PipelineNotImplemented`, now dead.
- The interpreter seam raises `InterpretationUnavailable` rather than falling back to keyword matching — a regex
  fallback would fail the mandatory-LLM requirement outright, so failing closed is the only honest option.
- Optimization quality on all known data: `min(1, optimal/team)` = **1.000000** on all 44 cases.
- **Fixed both open findings from `CODE_REVIEW.md` Review 1** (they landed in the repo during this session):
  - **R1-1 (High)** was a real bug in my P2/P3 code: `compile_directives()` sorted by `note_index` while
    `derive_envelope()` trusted list order, so under `SOLAR_OVERLAP_POLICY=last_wins` the same directives in a
    different order resolved to different effective solar (reproduced: 39.0 vs 104.0). A valid plan could then have
    been rejected by its own validator. `derive_envelope()` now sorts by `note_index` too, so "last" means "highest
    `note_index`" on both sides and the result is order-independent. Regression test added to the agreement suite.
    The default `min_factor` policy is commutative, which is exactly why the existing tests missed it.
  - **R1-2 (Low)** the unreachable `elif end_hour == HOURS_IN_DAY` branch in `expand_window()` is deleted, with a
    comment explaining why the forward case already covers it.
  - Both findings are annotated in `CODE_REVIEW.md` as *fix applied, pending verification*; their status stays
    `OPEN` because that file's protocol reserves `FIXED` for confirmation in a later review pass.
- Next session starts at `T-070`: `scripts/run_public_cases.py`, the standalone regression runner that reports
  interpretation, validity, cost gap, and latency per case.

### 2026-09-18 — Session 9 (P7 + P8 — regression runner and LLM interpreter)

- `T-070`, `T-080`, `T-081`, `T-082` complete. 237 tests green (2 `live` deselected), `ruff check .` clean.
- **The pipeline is now complete end to end.** With a stubbed provider, a public case goes request → model → shape
  gate → compiler → solvers → canonicalizer → replay → 200, at the published optimal cost. Only the guardrail
  classification (P9) and the retry policy (P10) are missing between the model and the compiler.
- P7 reuses everything: the runner calls the P6 service, replays with P2, and compares interpretations with a new
  comparator that checks what the organizers check and ignores explanation wording. One runner serves both the
  offline optimizer regression and (via `--endpoint`) the live LLM path P11/P16 will need.
- **O-01 deliberately left open.** No credentials exist in this environment, so instead of guessing a provider I built
  two adapters — OpenAI-compatible and Anthropic — behind one protocol, selected by `LLM_PROVIDER`. That also gives
  O-02's backup seam for free. Pinning the exact model snapshot is a config change plus a `pytest -m live` run.
- **Failure classes are modelled as types, not strings**, because P10 must branch on them: a 429 carries its
  `retry_after`, a refusal is not malformed output, a timeout is not a 5xx. Every one is covered offline with
  `httpx.MockTransport`, so the retry policy can be built against tested behaviour rather than assumptions.
- The prompt is contrastive by design: the two expensive errors are the `by`/`to` factor inversion and the
  end-exclusive window boundary, and both are shown as explicit contrasts rather than described. Provisional
  spec-gap policies are generated from config, so an organizer clarification changes the prompt through a setting.
- **D-05 is now enforced by test, not just by intent**: the payload must contain no `demand_kwh`, `solar_kwh`, or
  `tariff`. Sending the 24-hour matrix would cost tokens and latency and invite the model to copy an unrelated
  number into a directive.
- Prompt injection is handled structurally rather than by filtering: notes are JSON-escaped values inside a delimited
  data block, the system prompt states they cannot change the rules, and the schema simply has no variant for an
  invented directive type. A test asserts an injected note cannot widen the schema.
- Anthropic returning prose instead of the forced tool call is classified as `ModelRefusal`, not malformed output —
  the model declined; it did not emit broken JSON. That routing matters in P10.
- Live smoke test added behind `-m live` and excluded from default runs, so CI stays offline and free.
- Next session starts at `T-090`/`T-091`: the deterministic guardrails that replace `coerce_to_canonical`'s shape gate
  with classified checks (count, note_index coverage, hours, applies semantics, reserve-vs-capacity, finiteness) plus
  the narrow safe normalizations — and nothing else.

### 2026-09-18 — Session 10 (P9 + P10 — guardrails and the repair policy)

- `T-090`, `T-091`, `T-100`, `T-101` complete. 301 tests green (2 `live` deselected), `ruff check .` clean,
  regression 44/44.
- **The judge-path pipeline is now feature-complete.** Everything from P1 to P10 is connected: validate → baseline
  screen → interpret (with bounded repair) → classified guardrails → compile → LP → MILP → canonicalize → serialize →
  parse back → replay → response. What remains is coverage, hardening, and delivery (P11-P20), not new pipeline stages.
- P9 validates the **raw payload**, deliberately before Pydantic. The union rejects an unknown directive type and a
  duplicate hour with the same opaque error, and that difference is precisely what P10 needs in order to choose
  between a structural repair and a semantic one. It also collects every failure rather than the first, because a
  repair listing all the problems has a far better chance of landing in the one retry the budget allows.
- **A real bug caught by its own test:** on a 429 with an unfittable `retry_after`, the runner fell back to the backup
  provider *and still slept the primary's hint*, burning the budget so the fallback could not land. A different
  provider is not the one rate-limiting us. Fixed by making the wait part of the routing decision (`_Decision`)
  instead of a property of the exception — so a refusal, truncation or schema failure now retries immediately, which
  is both more correct and faster.
- `conflict_checks.py` was **dropped rather than written as filler** — every cross-field rule is scenario-local and
  belongs in the validator, ambiguity flags come from the compiler, and feasibility is the LP's job.
- Two deliberate, documented policy calls in the guardrail: unique-but-unsorted hours are **sorted** (a window is a
  set; rejecting would spend a repair on a difference that cannot change the constraint), and a missing or non-string
  `explanation` is **filled** (free text the rubric does not match; failing a case over it trades real points for
  nothing). The second is a fifth normalization beyond Guide §9's four, taken knowingly.
- The feasibility retry keeps the **first** outcome when the second reading is also infeasible. A second wrong answer
  is not an improvement, and reporting the original failure keeps diagnosis honest.
- Next session starts at `T-110`: the end-to-end public regression through the real endpoint, which needs a pinned
  provider (O-01) to run against a live model — `scripts/run_public_cases.py --endpoint URL` already supports it.

### 2026-09-18 — Session 11 (Docker pulled forward, then P11 + P12 + P13)

- Docker (`T-160`/`T-161`) was **pulled out of P16 at the user's request** — a teammate needs it now to deploy on
  Azure from a different machine. `Dockerfile`, `docker-compose.yml`, `DOCKER.md`, `verify_docker.py`,
  `verify_solver.py` and `healthcheck.py` are written.
  **Honest limitation: the image has never been built.** This machine has the Docker CLI but no running daemon. What
  *was* verified locally: the build-time solver check passes, the healthcheck script returns 0 when healthy and 1 on a
  wrong port, and `.dockerignore` keeps `.env`/`.git`/`tests`/`docs` out while keeping everything the image needs in.
  `scripts/verify_docker.py` exists precisely to close that gap on a machine with a daemon.
- **One Docker bug was caught before it shipped:** `python scripts/verify_solver.py` puts `scripts/` on `sys.path`,
  not the working directory, so `import app` failed — it would have broken the image build. Both scripts now bootstrap
  the repo root explicitly, the same way `run_public_cases.py` does.
- `$PORT` is honored throughout (Dockerfile CMD, healthcheck, compose) because Azure assigns the port. A container
  hard-coded to 8000 would have looked dead to the platform's probe.
- **P13 found a real, score-affecting bug in P5's solver.** A metamorphic test reported that *adding* a constraint
  lowered the optimal cost — impossible for nested feasible sets. Root cause: `scipy.optimize.milp` inherits HiGHS's
  default **1e-4 relative MIP gap**, so it stops at a provably near-optimal solution and still returns `status=0`,
  which this service was mapping to `proven_optimal=True`. On one seed it returned 21544.38 against a true optimum of
  21543.34. Optimization credit is `min(1, optimal/team_cost)`, so that was free score being given away — and the
  "proven optimal" claim was false. Fixed with `MILP_RELATIVE_GAP=0.0` plus a regression test asserting
  `mip_gap == 0` and MILP == LP bound on every public case. This is exactly what property tests are for: 44 reference
  cases never exposed it.
- P11's stub provider **asserts it received the production prompt and schema**, so the end-to-end suite cannot quietly
  degrade into testing a bypassed interpreter. Two spend guards are asserted there too: neither a structurally invalid
  request nor a baseline-infeasible scenario ever reaches the model.
- P12 keeps three separately scored buckets and **excludes the provisional one from the pass threshold** — a "failure"
  on an undefined case may only mean the organizers chose the other reading, and letting that move the headline number
  would mask a real regression. The scorer is itself tested for the ability to fail.
- Rejected keyword filtering of injected notes: a genuine operator note can contain "ignore", "system" or "override",
  and dropping a real directive because it looked suspicious would lose the case. Defence is structural instead.
- Next session starts at `T-140`: parser/response caching with version-aware keys, request budgets, and concurrency
  limits. **O-01 (provider + pinned model) is now the main blocker** for live semantic accuracy and deployment.

### 2026-09-18 — Session 12 (P14 — caching, budgets, concurrency)

- `T-140`/`T-141` complete. 408 tests green (2 `live` deselected), `ruff check .` clean, regression 10/10.
- **The parser cache key hashes the prompt text itself.** Guide §21 says to include "relevant battery context", but I
  checked what the prompt actually carries and it is *all five* battery fields, not just capacity. Enumerating them by
  hand is a bug waiting to happen — add a field to the prompt later and the key silently stops covering it. Hashing
  the rendered prompt makes the key correct by construction, and it also catches a prompt edit that shipped without a
  `PROMPT_VERSION` bump. Versions are still hashed separately so an explicit bump invalidates regardless.
- Deliberate asymmetry between the two caches, and it is worth understanding before changing either: the **parser**
  key ignores the 24-hour matrix (it never reaches the model, so two scenarios with identical notes and battery share
  an interpretation), while the **response** key covers the whole scenario including `scenario_id` and tariffs. A test
  pins each half, because collapsing them either way is a real bug — sharing a response across scenario ids would
  echo the wrong id.
- Nothing invalid is ever cached: the parser stores only post-guardrail interpretations, the response cache only
  post-replay responses. Guardrail failures, provider outages and infeasible interpretations all leave both empty,
  each asserted. A successful feasibility repair **overwrites** the cached interpretation, so a repeat request does
  not pay for the same reparse twice.
- **The concurrency gate queues rather than rejects**, and `/health` bypasses it completely. Rejecting judge traffic
  to protect the provider would be trading a scored requirement for an unscored one, and a health probe stuck behind a
  saturated optimizer would make the platform restart a perfectly healthy instance.
- The `Deadline` now starts in the middleware, *before* queueing, and flows through the route into the service. Had it
  started after the wait, a queued request could have taken its full 28 s of work on top of an unknown wait and blown
  the organizer's 30 s limit.
- One test of mine was wrong, not the code: I varied the note *count* while the canned provider answer still had two
  entries, so the guardrail correctly rejected it. Fixed the fixture to vary wording while keeping one entry per note.
- Next session starts at `T-150`/`T-151`: structured JSON logging with correlation IDs and the Guide §23 field list,
  plus Prometheus-style counters and histograms. Telemetry the layers below already collect —
  `InterpretationRun` (attempts, repairs, cache_hit, model version), `SolveOutcome`, `ValidationReport`, and both
  `CacheStats` — is waiting to be surfaced.

### 2026-09-18 — Session 13 (P15 — observability)

- `T-150`/`T-151` complete. 441 tests green (2 `live` deselected), `ruff check .` clean, regression 10/10.
- Checked for collisions before writing anything, and found five: P1's `logging.basicConfig` placeholder, the two
  `LOG_RAW_*` flags defined in P0 and never used, `extra=` log fields in `errors.py` and `repair.py` that a plain
  formatter silently discards, and no `prometheus_client` in the pinned dependency set.
- **A latent concurrency bug from P10 was fixed, not built upon.** `OptimizeService._last_run` stored per-request
  telemetry on a *process-wide singleton*, so two concurrent requests would overwrite each other's diagnostics.
  Harmless while nothing read it — but P15's whole job is reading it. Replaced with a context-local `RequestTrace`
  (context variables are task-local under asyncio), and a test runs two overlapping requests to prove the traces stay
  separate. `last_run` was removed rather than left as a racy convenience.
- The correlation ID travels in a `ContextVar` rather than through every function signature, so a line logged deep in
  the optimizer still carries the right request's ID.
- **Third-party log quieting is prefix-based, and that mattered:** the installed client registers as `httpx2`, which
  an exact-name list missed entirely — the first smoke test was still full of per-request httpx lines. It is now a
  handler filter, so loggers created *after* configuration are covered too.
- Deliberately no new dependency for metrics. A ~120-line registry beats another wheel to pin, install and re-verify
  inside the image. Latency buckets include 4.5 s and 5 s so p95 can be read straight against the rubric.
- `/metrics` lives on its own router behind `METRICS_ENABLED` and is asserted to be switchable off: the judged
  surface stays exactly the two endpoints the Problem Statement defines.
- `/health` is counted in metrics but **not** trace-logged — the probe runs constantly and would drown real traffic.
- Next session is the rest of P16: `T-162`, deploying and verifying from an external network. The image, compose file,
  `DOCKER.md` and `verify_docker.py` already exist from session 11. **O-01 (provider + pinned model snapshot) and
  O-03 (hosting platform) are the remaining blockers.**

### 2026-09-18 — Session 14 (P17 + P18; P16 deployment delegated)

- P16's remaining task (`T-162`, deploy) is **delegated to a teammate** at the user's request; the Docker artefacts
  from session 11 are what they need. `T-170`, `T-171` and `T-180` are complete. 458 tests green, `ruff` clean.
- **O-01 is effectively resolved:** provider `openai`, model `gpt-5.6-luna`. The warm canary passes against it —
  all three canary cases correct, warm p95 **1.9 s** against the 4.5 s budget — and a full `/demo/analyze` on
  SAMPLE-01 returned the published ground-truth directive (`solar_reduction [12,13] factor 0.25`) and the exact
  published optimum (38365.0), replay clean and proven optimal.
- **The canary earned its keep immediately by finding two real defects:**
  1. `temperature=0.0` is rejected by this model (`only the default (1) is supported`), so every call returned 400.
     The adapter was discarding the provider's error body, making it undiagnosable; it now surfaces the safe error
     *metadata* (`type`, `code`, `param`, truncated message), which is what named the problem. API clients still see
     only a sanitized 500.
  2. Worse: `.env.example` documented "leave blank to omit" for `LLM_TEMPERATURE`, and **a blank value crashed the
     service at startup** — an empty env string is not a valid `float | None`. The documented escape hatch was a
     landmine. Fixed with a `mode="before"` validator that treats blank/`none`/`null`/`default` as `None`.
     The user's local `.env` was updated accordingly (one line; backup at `.env.bak`).
- Also fixed a loop-lifetime bug in the canary: closing the provider's pooled client in a second `asyncio.run` raised
  "Event loop is closed". The client belongs to the loop that created it.
- **A test-hygiene bug that had become a real one:** with credentials present in `.env`, the default `OptimizeService`
  built a *live* interpreter, so the ordinary test suite was making billable provider calls and its results depended
  on whose machine it ran on. `tests/conftest.py` now clears provider credentials at import time; the live checks
  opt back in with `GRIDWISE_TEST_ALLOW_LIVE=1`.
- P18 gating uses **both** P0 flags: `DEMO_MODE=true` *and* `JUDGE_MODE=false`. A deployment that accidentally ships
  with `DEMO_MODE` set still exposes nothing, and a warning is logged so the combination is never silently ignored.
- The demo reads the artefacts earlier phases already produce — P3's `ConstraintTrace` provenance, P5's solver
  statuses, P2's replay residuals — rather than recomputing them. A demo with its own arithmetic could show a
  convincing story while the judged path did something else. A test asserts the demo's numbers equal the canonical
  response exactly.
- The no-storage cost comparison is **labelled infeasible** when a grid cap makes it impossible, rather than quoting a
  saving against a plan nobody could legally run.
- P19 (CI) is **dropped** at the user's request; the checks it would have automated all run locally.

### 2026-09-18 — Session 15 (P19 dropped; full P0-P18 verification)

- **P19 dropped, not deferred.** Every check the workflow would have run exists as a local command:
  `ruff check .`, `pytest`, `run_public_cases.py`, `verify_docker.py`, `warm_canary.py`. Guide §33 lists CI as
  recommended; the rubric scores the endpoint, the artefacts and the documentation, none of which need a workflow.
- **Audited P0-P18 against disk rather than against this file.** All 50 manifest entries exist. 19 acceptance
  criteria re-checked directly in one pass: reference responses parse, 44 plans replay clean at 1e-9, compiler and
  independent envelope agree on 44 cases, 44 cases reach the published optimum with optimality proven, responses
  build and replay, the regression runner passes 10/10, the prompt carries the contrast rules and withholds the
  24-hour matrix, the schema exposes exactly six variants, guardrails classify correctly, repair covers every failure
  class, cache keys separate on battery, notes redact, and demo gating needs both flags. **19/19 passed.**
- 458 tests green, `ruff` clean.
- **End-to-end against the real model and the real endpoint: 10/10 public cases correct** — every interpretation
  matched ground truth and every cost matched the published optimum exactly. Repeated over three uncached passes:
  30/30 correct.
- **Latency finding worth acting on.** The first request after start cost **8.2 s** (cold model/schema compile),
  which alone would put p95 in the 2/3 band. Warm, uncached steady state is **p50 2.6-2.7 s, p95 3.1-3.4 s** — the
  3/3 full-credit band. So `scripts/warm_canary.py` is not optional polish: **run it after deploy and before judging**,
  or the first judged request pays the cold cost. This is now the single most important operational step.
- Secret hygiene re-verified: `.env` and `.env.bak` are both git-ignored and both excluded from the Docker build
  context; the only tracked env file is `.env.example`, which holds no values.
- Remaining work is **P20**, owned by teammates (README, video) plus `T-202` release freeze, and the P16 deploy.

### 2026-09-18 — Session 16 (frontend pass + two deployment-blocking config bugs)

- Frontend reduced to exactly the documented surface (Problem Statement §10): `scenario_id`, `total_grid_kwh`,
  `total_cost_bdt`, `peak_grid_kwh`, `plan_summary`, `directive_interpretation`, `hourly_plan`. The hourly chart
  component was deleted — a chart is not a documented response field. Light-only claymorphism theme; tables fold to
  cards below 640px via `data-label`. `npm run lint` and `npm run build` pass, browser console clean.
- **Chased a frontend 500 that was not a frontend bug at all.** The UI showed `interpretation_unavailable` while the
  identical request sent to `127.0.0.1:8000` returned 200. Cause: **three processes were listening on port 8000** —
  the uvicorn dev server on `127.0.0.1` (IPv4 only), and a published Docker container on `::1`/`::`. Node resolves
  `localhost` to IPv6 first, so the Vite proxy was forwarding every call to a stale container, not to the dev server.
  Fixed by pinning the dev proxy default target to `http://127.0.0.1:8000` in `frontend/vite.config.ts`.
- **Bug 1 (deployment-blocking): `LLM_TEMPERATURE=0.0` fails every request.** The pinned model answers
  `400 unsupported_value: 'temperature' does not support 0.0 with this model` on *every* call, so the service
  returns `interpretation_unavailable` in ~1.1 s for every scenario. `.env` had already been fixed, but the code
  default in `app/config.py` and the value shipped in `.env.example` were both still `0.0` — so a clean deploy that
  copies `.env.example`, or one that simply does not set the variable, breaks 100% of requests. **The default is now
  `None` (parameter omitted), which works against every supported provider.**
- **Bug 2 (deployment-blocking): a blank `LLM_TEMPERATURE` crashed startup in the previously built image.** The
  `mode="before"` validator that accepts a blank value postdates that image. Consequence: **the image must be
  rebuilt, not just restarted.** Verified by rebuilding from current source and running the public cases against the
  container — SAMPLE-02 and SAMPLE-06 both returned the published optimum.
- **Docker healthcheck cannot catch either bug.** It only probes `/health`, which by design makes no LLM call, so a
  container failing every `/optimize-energy` still reports `healthy`. Treat "container healthy" as necessary, not
  sufficient — run `scripts/run_public_cases.py` against the deployed URL before judging.
- Raised `llm_attempt_timeout_seconds` 3.2 → 12.0. This was *not* the cause of the 500 (that was the temperature
  bug), but 3.2 s sat below the measured 8.2 s cold call and barely above the 3.1 s warm p95, so a single slow call
  became a timeout, a retry, and doubled latency. The per-request `Deadline` still caps it, so the 28 s hard
  deadline is unchanged.
- Accessibility issues cleared: three unbound `<label>` group headings became spans, and all 78 form inputs gained
  `id`/`name`. Chrome's issues panel is now empty.
- 458 tests green, `ruff` clean.
- Added **`scripts/verify_contract.py`** to answer "how do we know the deployed service meets the
  API-service requirement?" It is a black-box contract audit against a running base URL: both
  endpoints on one origin, `/health` returning exactly `{"status":"ok"}` fast enough to be a
  readiness probe, the exact Section 10.1/10.2/10.3 field sets with **no undocumented fields**,
  the closed directive taxonomy, `applies`/`no_op`/`structured_adjustment` agreement, the 24-hour
  plan replayed for balance/continuity/bounds/rate limits, totals recomputed from the plan, the
  400 (and advisory 422) error mapping, and no secret or stack trace in any error body.
  **279/279 checks pass against the local service across all 10 public cases.** Verified it has
  teeth by pointing it at the broken container: it correctly failed with exit code 1 on exactly
  the case the Docker healthcheck cannot see (`/health` fine, `/optimize-energy` 500).

### 2026-09-18 — Session 17 (Azure deployment + live corpus verification)

**Deployed. URL: `https://gridwise-api.azurewebsites.net`** (`GET /health`, `POST /optimize-energy`).

- **Azure layout** (subscription "Azure for Students", resource group `gridwise-rg`, Southeast Asia):
  ACR `gridwiseacr50329` (Basic, **admin disabled**) → App Service plan `gridwise-plan` (Linux B1) → Web App
  `gridwise-api` (Web App for Containers, Always On, `WEBSITES_PORT=8000`). The app pulls with its **system-assigned
  managed identity** (`AcrPull` on the registry, `acrUseManagedIdentityCreds=true`), so no registry password exists.
  The app runs the image **by digest**, not by tag (O-04): `gridwiseacr50329.azurecr.io/gridwise@sha256:4a965aed…12b6`
  (tag `1.0.3`, commit `7fadf96`). `APP_COMMIT_SHA` is set to the commit.
- **Image built by ACR, not locally** (`az acr build`) because this machine has no running Docker daemon.
  `verify_solver.py` runs in that build, so a SciPy without a working HiGHS would have failed the build.
  `scripts/verify_docker.py` has still never run.
- **Why App Service and not Container Apps:** Azure for Students allows **one** Container Apps environment per
  subscription and another project (`medora-env-us`) already holds it. Not touched. The first Container Apps attempt
  was deleted (`gridwise-env` and its Log Analytics workspace may remain in `gridwise-rg`; harmless).
- **Config.** App settings were loaded from the local `.env` (44 keys), **including `LLM_API_KEY` and
  `BACKUP_LLM_API_KEY`, as plain App Service settings** — encrypted at rest and hidden from the image, but not Key
  Vault references. Two settings deliberately differ from `.env`: `LLM_ATTEMPT_TIMEOUT_SECONDS=12` (upstream raised the
  default from 3.2 because a cold model call measures ~8 s; the `.env` copy had pinned the old 3.2 and would have
  silently overridden the new default) and **no `LLM_TEMPERATURE`** (code default is now `None`).
- **Root cause of the first live 500s** was the same bug as Session 16 Bug 1: the pinned model rejects
  `temperature=0.0` with a 400. Diagnosed by replaying the exact `/chat/completions` call with `curl`. Container logs
  only show `request failed: interpretation_unavailable` — by design no provider detail is logged — so **reproduce the
  provider call directly rather than hunting in the logs.**
- **Merge:** local `main` had diverged from `origin/main` (7 upstream commits: cache, observability, demo layer,
  frontend). One conflict in `app/config.py`, where both sides had written the same blank-temperature validator;
  upstream's broader version was kept. Merge commit `27ada5d`, pushed. No co-author trailer on any commit (user
  instruction). `git pull` later brought in `7fadf96` (Session 16 work) and the deployment was rebuilt from it.

**Live verification against the deployed URL (real model, not the offline fakes):**

| Corpus | Result |
|---|---|
| `sample_cases.json` + `--extended` (10 public + 34 hidden-like) | **44 / 44** interpretation PASS, validity PASS, max cost gap 0; latency median 2.8 s, p95 3.2–3.5 s, max 4.1 s |
| `paraphrase_eval.py` — 58 semantic variations (incl. 10 no_op distractors) | **58 / 58** matched, 58 guardrail-clean |
| adversarial prompt-injection notes ADV-01..05 | **5 / 5** |
| provisional spec-gap cases (AMB-01/02/04-style) | 2 / 2 (only 2 of the pack's 4 carry a single provisional answer; AMB-03 lists competing readings and is unit-tested instead) |
| 11 `invalid_request_cases` + 2 `raw_invalid_cases` | **13 / 13** expected HTTP status (400 / 422), no stack trace or key in any body |
| 14 `guardrail_output_cases` | GR-01..12 asserted by id in `tests/unit/test_guardrails.py`; GR-13/14 (refusal, truncation) covered in `tests/unit/test_llm_interpreter.py`; offline, no LLM needed |
| `scripts/verify_contract.py --base-url <deployed> --fresh` | **104 / 104** |

- **Cold start is the one real risk.** Right after a restart, `/health` and the first `/optimize-energy` timed out in
  `verify_contract.py` (first optimize 10.8 s); the same audit passed 104/104 a minute later. Always On is enabled and
  the warm canary exists, but **after any redeploy or restart, send a warm-up request before a judge can**, and never
  restart during judging. Not yet measured with `scripts/benchmark_latency.py`.
- Not covered by any corpus: the 10 `metamorphic_relations` entries are exercised by the property tests, not by id.

**Redeploy recipe (no secrets):**
```
az acr build --registry gridwiseacr50329 --image gridwise:<ver> --no-logs .          # --no-logs: az's log streamer crashes on Windows cp1252
DIGEST=$(az acr repository show --name gridwiseacr50329 --image gridwise:<ver> --query digest -o tsv)
az webapp config container set -n gridwise-api -g gridwise-rg \
  --container-image-name gridwiseacr50329.azurecr.io/gridwise@$DIGEST --container-registry-url https://gridwiseacr50329.azurecr.io
az webapp restart -n gridwise-api -g gridwise-rg      # then warm it: run scripts/run_public_cases.py --endpoint <url>
```
**Windows gotchas hit:** in Git Bash, set `MSYS_NO_PATHCONV=1` for any command taking a `/subscriptions/...` id (it
was rewritten to `C:/Program Files/Git/...`); the `az` process is native Windows, so give it Windows-style paths, not `/tmp`;
a "Container Apps express environment" cannot use managed-identity registry pull (`ExpressEnvironmentFeatureNotSupported`).

**Open items from this session:** (1) API keys are plain App Service settings — move to Key Vault references if time
allows; (2) `benchmark_latency.py` p95 against the deployed URL; (3) freeze versions (`T-202`) and record the digest in the README;
(4) the local `.env` still has `LLM_TEMPERATURE=0.0` (rejected by the pinned model — run local live tools with `LLM_TEMPERATURE=` or blank it) and `LLM_ATTEMPT_TIMEOUT_SECONDS=3.2`, unlike the deployed config; (5) B1 is a
single instance with no autoscale.
