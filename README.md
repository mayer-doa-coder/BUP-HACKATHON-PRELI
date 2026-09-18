# GridWise

LLM-assisted smart-campus energy optimizer built for the BUP CSE Fest 2026 hackathon preliminary. A single HTTP
service that turns free-text operator notes plus a 24-hour demand/solar/tariff/battery scenario into an optimal
grid/battery dispatch plan, judged by an automated harness.

> **This README reflects work-in-progress state, not a finished product.** For the authoritative, up-to-date build
> status, decision log, and task board, see [IMPLEMENTATION_TRACKER.md](IMPLEMENTATION_TRACKER.md). This file is a
> snapshot of what exists today.

## Status: P0–P6 complete — the optimizer path is finished and provably optimal; the LLM interpreter is the one thing standing between this and a working endpoint

Seven phases are done: **P0 — Scaffolding**, **P1 — Schemas, endpoints, error mapping**, **P2 — Independent replay
validator**, **P3 — Directive compiler**, **P4 — Shared LP/MILP model**, **P5 — Solvers**, and **P6 — Canonicalizer,
response builder, service wiring**.

Everything from a validated request to a replay-cleared response now works. Given directives, the service compiles
them into per-hour constraints, screens feasibility with an LP, solves the authoritative MILP, builds the seven-field
response, serializes it, parses it back, and validates it with an independently written replay validator — and on
all 44 known reference cases it reaches the published optimal cost exactly (`min(1, optimal/team_cost)` = 1.000000).

**The endpoint is nevertheless not usable end to end yet.** A real `POST /optimize-energy` still returns a controlled
`500 InterpretationUnavailable`, because the one stage that produces directives — the LLM interpreter (P8) and its
guardrails (P9) — does not exist. The seam deliberately fails closed rather than falling back to keyword matching,
which would defeat the mandatory-LLM requirement. Inject a stub interpreter and the same endpoint returns a full,
valid 200.

## What is actually done

**P0 — Scaffolding**

- Project tooling (`pyproject.toml`, `requirements.txt`, `requirements-dev.txt`, `.gitignore`, `.dockerignore`) and
  the `app/` package tree.
- **`app/config.py`** — a typed Pydantic `Settings` object (incl. `OVERSIZED_REQUEST_STATUS`,
  `REJECT_NEGATIVE_ENERGY_INPUTS`). API keys are `SecretStr` and never appear in `repr`/`str`. `.env.example` is
  committed; `.env` is gitignored.
- **`public_cases/sample_cases.json`** — the organizer's 10-case sample pack, copied byte-identical from `docs/`
  (verified by SHA-256) as the regression seed.

**P1 — Schemas, endpoints, error mapping**

- **`app/schemas/request.py`** — strict (`extra="forbid"`) request models: `OptimizeRequest` (1–3 non-empty notes,
  exactly 24 hours, hour set exactly `{0..23}`), `HourInput`, `BatteryInput`, a `Finite` float type rejecting
  NaN/Inf, and `canonical_hours()` which orders by the `hour` field so array position is never trusted. Domain-sanity
  checks (e.g. negative energy) are deliberately kept separate in `validation/request_semantics.py` so they surface
  as 422, not 400.
- **`app/schemas/directive.py`** — the closed six-variant directive taxonomy as a discriminated union
  (`Literal`-tagged), with an `HourSetAdjustment` base enforcing unique/ascending/in-range/non-empty hours.
- **`app/schemas/response.py`** — `HourPlan` + `OptimizeResponse` with exactly the seven canonical response fields
  and fail-closed validators (plan covers hours 0–23 in order, `note_index` is 0..N-1 in order, `idle` carries zero
  magnitude).
- **`app/api/errors.py`** — the `GridWiseError` taxonomy (`StructurallyInvalidRequest` → 400,
  `SemanticallyInvalidRequest` → 422, `RequestTooLarge` → configurable status, `InterpretationUnavailable` /
  `DirectiveInfeasible` / `SolverFailure` / `ReplayInvariantFailure` → 500) with handlers that override FastAPI's
  default 422-for-everything behavior. 500 responses carry only a correlation ID — no stack traces, prompts, or
  payloads.
- **`app/api/middleware.py`** — correlation-ID injection and a request body-size guard.
- **`app/api/routes.py` + `app/main.py`** — `/health` (no LLM/solver call) and `/optimize-energy` wired through a
  `get_optimize_service` dependency seam.

Verified: all 11 `invalid_request_cases` and both `raw_invalid_cases` from the adversarial corpus map to their
expected HTTP status; all 10 public + 34 extended-corpus request/response bodies round-trip through the canonical
models unchanged; `no_op` directives serialize with an explicit `"structured_adjustment": null`; negative tariff is
correctly *not* rejected.

**P2 — Independent replay validator**

- **`app/validation/replay.py`** — `replay()`, an independent re-check of a plan's arithmetic and constraints: a
  `ViolationCode` enum (21 stable codes), `Violation`, `ValidationReport`, and `ConstraintEnvelope`. It **derives
  its own constraint envelope** from the request rather than calling the optimizer's directive compiler, so it
  cannot inherit a bug from the code it is meant to catch (deliberate duplication — `IMPLEMENTATION_TRACKER.md`
  D-09). An AST-level test asserts `replay.py` imports nothing from `app.optimizer`.
- **`app/validation/totals.py`** — `recalculate_totals()`, recomputing `total_grid_kwh` / `total_cost_bdt` /
  `peak_grid_kwh` from the plan itself (via `math.fsum`, keyed by hour number, never array position).

Verified: all 44 reference plans replay clean at 0.01, at 1e-6, and still at 1e-9 — agreement with organizer ground
truth at machine precision, not merely inside judge tolerance. 20 mutation fixtures each fail with the expected
violation code, so the validator is proven to catch bad plans, not just pass good ones.

**P3 — Directive compiler**

- **`app/optimizer/compile_directives.py`** — `CompiledConstraints` (NumPy arrays: `effective_solar`, `min_energy`,
  `charge_allowed`, `discharge_allowed`, `grid_upper`), a `ConstraintTrace` recording per-hour provenance, and
  `_assert_compiled_invariants()` which fails closed rather than silently clipping an out-of-range value.
- **`app/policies/spec_gaps.py`** — the provisional spec-gap policies as isolated, config-flagged functions:
  `compose_solar_factors()`, `expand_window()` (the single source of truth for the time-window convention),
  `through_is_end_exclusive()`, `single_hour_window()`, and `policy_summary()`.

Verified: the compiler and P2's independently-written `derive_envelope()` agree on all five constraint arrays across
all 44 reference cases — two separate implementations of the same rules reaching the same answer. That agreement
check was itself probed to confirm it is sensitive to a flipped boolean, an `inf`→finite cap, and a 0.001 kWh drift.
`factor=0.0` and `max_grid_kwh=0.0` survive compilation; a reserve above capacity fails closed.

**P4 — Shared LP/MILP model**

- **`app/optimizer/model.py`** — `OptimizationModel`: one variable layout (`g, s, c, d, E, yc, yd` — 168 variables,
  49 equality rows, 72 inequality rows) and one constraint builder shared by both stages. Deliberately **has no
  `stage` parameter** — the LP and MILP cannot be handed different problems, which is what makes the
  `LP_cost <= MILP_cost` invariant meaningful rather than trivially true. Directives enter purely as variable
  bounds; the model never inspects a directive.

Verified: all 44 published reference schedules are feasible points of the model (equality, inequality, and bound
residuals below 1e-9), and the objective reproduces every published `total_cost_bdt` to 1e-6.

**P5 — Solvers**

- **`app/optimizer/lp_relaxation.py`** — `solve_lp_relaxation()` via `linprog(method="highs")`, with the mode
  variables left continuous in `[0,1]`. Used for feasibility screening, as a lower bound, and for diagnostics;
  never returned as a schedule.
- **`app/optimizer/milp_solver.py`** — `solve_milp()` via `scipy.optimize.milp` with binary mode variables and a
  time limit, capturing `mip_gap` and `dual_bound`. A time-limited but feasible incumbent counts as *usable*: a
  valid, slightly suboptimal plan still earns directive-application and partial optimization credit, whereas a 500
  earns nothing. Validity is never traded away — the replay validator still has the final say.
- **`app/optimizer/hybrid_solve.py`** — `screen_baseline_feasibility()` (the pre-LLM screen, so an impossible
  scenario never spends a paid call) and `hybrid_solve()`. **Solver problems are returned as statuses, never
  raised**, because the pipeline needs three different responses to failure: `BASELINE_INFEASIBLE` → 422,
  `DIRECTIVE_INFEASIBLE` → a bounded semantic reparse in P10, `SOLVER_FAILURE` → 500. Three invariants gate every
  solution: `LP <= MILP + tol`, model residuals within 1e-6, and no hour both charging and discharging.

Verified: all 44 reference cases reach the published optimum exactly, MILP optimality proven on every one,
`LP <= MILP` everywhere. Edge cases covered: zero-capacity battery, zero charge rate, a fully rigid battery,
negative tariff (solves, cost goes negative, stays bounded), `factor=0.0`, both bans on one hour, and a zero grid
cap (→ `DIRECTIVE_INFEASIBLE`). Failure injection confirms a crashing solver surfaces as `SOLVER_FAILURE` rather
than a traceback.

*Latency headroom:* baseline screen p50 3.3 ms, LP 3.0 ms, MILP 15.6 ms; worst observed total **39 ms** against a
4,500 ms budget. The LLM call will be the only meaningful latency cost in the pipeline.

**P6 — Canonicalizer, response builder, service wiring**

- **`app/optimizer/result.py`** — `build_hourly_plan()` rounds **only the independent decisions** (charge, discharge,
  solar used) and then *derives* the rest: `battery_energy_after_kwh` is rebuilt sequentially from the rounded
  movements and `grid_kwh` is recomputed from the energy balance, so the balance closes by construction. Rounding
  overshoot within 1e-6 is clipped as an artifact; anything larger fails closed as `SolverFailure`, as does activity
  in a banned hour or simultaneous charge/discharge.
- **`app/services/plan_summary.py`** — `build_plan_summary()`, deterministic and adaptive: it does not claim the
  battery shifted energy on a day when the battery never moved.
- **`app/services/optimize_service.py`** — the real pipeline: `validate` → `screen_feasibility` → `interpret`
  (the P8 seam) → `solve_and_build`. `SolveStatus` becomes an HTTP outcome here and nowhere else. The response is
  serialized, **parsed back**, and replayed before it is returned; a replay failure is a controlled 500, never a
  retry and never a 200.

Verified: all 44 reference cases build a replay-clean response at the published optimal cost — quality ratio
`min(1, optimal/team_cost)` is **exactly 1.000000 on every case**. Corrupting the solver's own `E` or `g` blocks
changes nothing in the response, proving both really are re-derived rather than copied out of the solution vector.
Deterministic across repeated solves.

> **The precision ladder is load-bearing, not decoration.** Rounding to 6 dp is enough to break a valid plan when
> inputs carry long decimals: the rounded battery movements stop cancelling over the day and the end-of-day balance
> drifts past the 1e-7 internal tolerance. The builder therefore tries `(6, 9, None)` decimal places and keeps the
> first rung that replays clean. A regression test reproduces the 6 dp failure deliberately. Do not collapse it.

## What is not done yet

The LLM directive interpreter and prompts (P8), deterministic guardrails on LLM output (P9), repair/retry and
feasibility-aware reinterpretation (P10), the public-case regression runner `scripts/run_public_cases.py` (P7), the
semantic/adversarial corpus (P12), property and metamorphic tests (P13), caching (P14), observability (P15), Docker
packaging and deployment (P16), the warm canary and latency benchmark (P17), the demo layer (P18), CI (P19), and the
submission README/video/release freeze (P20). There is no `scripts/` directory and no `Dockerfile` yet.

See the phase board in `IMPLEMENTATION_TRACKER.md` §6 for the full remaining scope, and §1 for the live status
snapshot.

Both findings from the first `/code-review` pass (an ordering disagreement between `compile_directives()` and
`derive_envelope()` under a non-default overlap policy, and a dead branch in `expand_window()`) are **fixed and
verified in the code**. Note that the P4–P6 code above has never been through a review pass — see
[CODE_REVIEW.md](CODE_REVIEW.md).

## Repository layout

```
app/
  api/            HTTP routes, error mapping, middleware        — implemented (P1)
  schemas/        Pydantic request/response/directive models    — implemented (P1)
  optimizer/      Directive compiler, shared model, LP, MILP,
                  hybrid orchestration, response builder        — implemented (P3–P6)
  validation/     Request semantics, replay validator, totals   — implemented (P1–P2)
  services/       Pipeline orchestration + plan summary         — implemented (P6); interpret() seam fails closed
  policies/       Config-flagged spec-gap policies              — implemented (P3)
  llm/            LLM interpreter, prompts, provider adapters    (not yet implemented — P8)
  guardrails/     Deterministic validation of LLM output         (not yet implemented — P9)
  observability/  Structured logging, metrics                    (not yet implemented — P15)
  cache/          Request/response caching                       (not yet implemented — P14)
  demo/           Optional demo routes behind DEMO_MODE          (not yet implemented — P18)
  config.py       Typed Settings — implemented (P0)
  main.py         FastAPI app entrypoint — implemented (P1)

docs/              Organizer documents and team specs — read-only, never edited
public_cases/      Copy of the organizer's 10-case sample pack (regression seed)
tests/unit/        Config, schema, replay, compiler, spec-gap, model, solver, result-builder tests
tests/integration/ API contract / error mapping, and full-pipeline tests
IMPLEMENTATION_TRACKER.md   Live status, locked/open decisions, phase board, session log
CODE_REVIEW.md     Running /code-review findings log — status tracked across passes
CLAUDE.md          Repository instructions and non-negotiable rules for AI-assisted work
```

## Running what exists today

```bash
pip install -r requirements.txt -r requirements-dev.txt

pytest                                              # 174 passing
ruff check .                                        # lint gate
uvicorn app.main:app --host 0.0.0.0 --port 8000     # run the service
curl http://localhost:8000/health                   # -> {"status":"ok"}
```

`/health` works. `POST /optimize-energy` validates the request, screens feasibility, and then returns a controlled
`500 InterpretationUnavailable`, since directives can only come from the LLM interpreter that P8 will add. The
optimizer path behind that seam is fully exercised by `tests/integration/test_optimize_pipeline.py`, which feeds
ground-truth directives straight into `OptimizeService.solve_and_build`.

> Verified in this environment on 2026-09-18: **174 tests pass in 9.35 s**. `ruff` was *not* verified — it is not
> installed on either available interpreter despite `IMPLEMENTATION_TRACKER.md` listing it as present. Run
> `pip install -r requirements-dev.txt` first.

The commands below are the **intended** interface once later phases land — they do not work yet:

```bash
python scripts/run_public_cases.py public_cases/sample_cases.json   # 10-case regression (P7)
python scripts/benchmark_latency.py                                 # p95 check (P17)
docker build -t gridwise . && docker run -p 8000:8000 --env-file .env gridwise   # (P16)
```

## Key design decisions already locked

These govern everything built from here on (full list with rationale in `IMPLEMENTATION_TRACKER.md` §2):

- The LLM only translates operator notes into a fixed, closed set of 6 directive types — it never computes kWh
  values, costs, or schedules. The optimizer produces every number.
- LP is relaxation/feasibility screening only; **MILP is the authoritative final optimizer**.
- LLM output is untrusted until it passes deterministic guardrails; guardrails may only sort/normalize, never
  repair or coerce semantics.
- Build order is optimizer-first, LLM second.
- The independent replay validator shares no code with the model builder or canonicalizer.
- Nothing is returned that has not been serialized, parsed back, and replayed.
- Testing is targeted at correctness-critical surfaces rather than blanket coverage.

## Where to look for more detail

| Question | Where |
|---|---|
| Live build status, task board, session history | [IMPLEMENTATION_TRACKER.md](IMPLEMENTATION_TRACKER.md) |
| Open/fixed `/code-review` findings, tracked across passes | [CODE_REVIEW.md](CODE_REVIEW.md) |
| Repository rules for AI-assisted development | [CLAUDE.md](CLAUDE.md) |
| Canonical API schema, directives, guardrails, energy rules | [docs/BUP_CSE_FEST_2026_Preliminary_Problem_Statement_GridWise_LLM.md](docs/BUP_CSE_FEST_2026_Preliminary_Problem_Statement_GridWise_LLM.md) |
| Deployment, scoring, penalties, latency, submission | [docs/BUP_CSE_FEST_2026_Participant_Guide_%26_Evaluation_Rubric_GridWise_LLM.md](docs/BUP_CSE_FEST_2026_Participant_Guide_%26_Evaluation_Rubric_GridWise_LLM.md) |
| Product requirements | [docs/PRD.md](docs/PRD.md) |
| Build guide, module layout, code skeletons | [docs/IMPLEMENTATION_GUIDE.md](docs/IMPLEMENTATION_GUIDE.md) |

A complete, submission-ready README (env var reference, curl examples, Docker instructions, known limitations,
secret handling) is planned as task `T-200` in the final documentation phase, once the service is functional.
