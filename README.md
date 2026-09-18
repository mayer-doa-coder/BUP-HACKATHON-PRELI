# GridWise

LLM-assisted smart-campus energy optimizer built for the BUP CSE Fest 2026 hackathon preliminary. A single HTTP
service that turns free-text operator notes plus a 24-hour demand/solar/tariff/battery scenario into an optimal
grid/battery dispatch plan, judged by an automated harness.

> **This README reflects work-in-progress state, not a finished product.** For the authoritative, up-to-date build
> status, decision log, and task board, see [IMPLEMENTATION_TRACKER.md](IMPLEMENTATION_TRACKER.md). This file is a
> snapshot of what exists today.

## Status: P0–P4 complete — schemas, endpoints, error mapping, the replay validator, the directive compiler, and the shared LP/MILP model exist; no solvers or LLM integration yet

The project is a greenfield build following [docs/IMPLEMENTATION_GUIDE.md](docs/IMPLEMENTATION_GUIDE.md), tracked
task-by-task in `IMPLEMENTATION_TRACKER.md`. Five phases are done: **P0 — Scaffolding**, **P1 — Schemas, endpoints,
error mapping**, **P2 — Independent replay validator**, **P3 — Directive compiler**, and **P4 — Shared LP/MILP
model**. The service runs and answers HTTP requests with correctly validated errors, there is a standalone module
that can catch an invalid plan after the fact, directives compile into per-hour solver constraints, and there is
now one shared variable layout and constraint builder that both the LP and MILP stages will use — but
`/optimize-energy` still does not produce a real plan: a structurally and semantically valid request currently
returns a controlled `500 PipelineNotImplemented`, because no solver module calls the model yet and the LLM
interpreter doesn't exist.

## What is actually done

**P0 — Scaffolding**

- Project tooling (`pyproject.toml`, `requirements.txt`, `requirements-dev.txt`, `.gitignore`, `.dockerignore`) and
  the `app/` package tree (`api/`, `schemas/`, `llm/` incl. `providers/`, `guardrails/`, `optimizer/`,
  `validation/`, `services/`, `observability/`, `cache/`, `demo/`, `policies/`).
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
  `SolverFailure` / `ReplayInvariantFailure` / `PipelineNotImplemented` → 500) with handlers that override
  FastAPI's default 422-for-everything behavior. 500 responses carry only a correlation ID — no stack traces,
  prompts, or payloads.
- **`app/api/middleware.py`** — correlation-ID injection and a request body-size guard.
- **`app/api/routes.py` + `app/main.py`** — `/health` (no LLM/solver call) and `/optimize-energy` wired through a
  `get_optimize_service` dependency seam to `app/services/optimize_service.py`, which currently runs request-limit
  and semantic checks and then raises `PipelineNotImplemented` (a valid request → controlled 500, not a fake plan).

Verified: all 11 `invalid_request_cases` and both `raw_invalid_cases` from the adversarial corpus map to their
expected HTTP status; all 10 public + 34 extended-corpus request/response bodies round-trip through the canonical
models unchanged; `no_op` directives serialize with an explicit `"structured_adjustment": null`; negative tariff is
correctly *not* rejected; `/openapi.json` and `/docs` render; a live `uvicorn` smoke test passed the health, 400,
422, and 500 paths.

**P2 — Independent replay validator**

- **`app/validation/replay.py`** — `replay()`, an independent re-check of a plan's arithmetic and constraints: a
  `ViolationCode` enum (21 stable codes), `Violation`, `ValidationReport`, and `ConstraintEnvelope`. It **derives
  its own constraint envelope** from the request rather than calling the optimizer's directive compiler, so it
  cannot inherit a bug from the code it is meant to catch — a composition bug that builds a bad plan and then
  "approves" it is exactly what this separation is designed to prevent (deliberate duplication, not an oversight;
  see `IMPLEMENTATION_TRACKER.md` D-09). An AST-level test asserts `replay.py` imports nothing from `app.optimizer`.
- **`app/validation/totals.py`** — `recalculate_totals()`, recomputing `total_grid_kwh` / `total_cost_bdt` /
  `peak_grid_kwh` from the plan itself (via `math.fsum`, keyed by hour number, never array position) rather than
  trusting any upstream value.

Verified: all 10 public **and** all 34 extended-corpus reference plans replay clean at 0.01, at 1e-6, and still at
1e-9 — agreement with organizer ground truth at machine precision, not merely inside judge tolerance — across every
directive type (solar, grid cap, no_op, no-charge, reserve, no-discharge). 20 mutation fixtures (charge during a
ban, discharge during a ban, grid over cap, dip below a directive reserve, pre-reduction solar overuse, etc.) each
fail with the expected violation code, so the validator is proven to actually catch bad plans, not just pass good
ones.

**P3 — Directive compiler**

- **`app/optimizer/compile_directives.py`** — `CompiledConstraints` (NumPy arrays: `effective_solar`, `min_energy`,
  `charge_allowed`, `discharge_allowed`, `grid_upper`, plus `original_solar`/`solar_factor` for the future demo
  layer), a `ConstraintTrace` recording per-hour provenance, and `_assert_compiled_invariants()` which fails closed
  with a new `DirectiveCompilationFailure` (500) rather than silently clipping an out-of-range value. Directives are
  processed in `note_index` order so compilation is deterministic.
- **`app/policies/spec_gaps.py`** — the provisional spec-gap policies as isolated, config-flagged functions:
  `compose_solar_factors()`, `expand_window()` (the single source of truth for the time-window convention, also
  destined to back the P8 prompt and the P18 paraphrase lab), `through_is_end_exclusive()`, `single_hour_window()`,
  and `policy_summary()`.

Verified: **the compiler and P2's independently-written `derive_envelope()` agree on all five constraint arrays
across all 44 reference cases** — two separate implementations of the same rules reaching the same answer. That
agreement check was itself probed to confirm it's sensitive (a flipped boolean, an `inf`→finite cap, and a 0.001
kWh solar drift are each caught) while tolerating 1e-15 float noise. Composition tests cover reserve `max`, cap
`min`, ban union, ban+ban ⇒ forced idle, and differing solar factors ⇒ `min(factor)` + ambiguity flag;
`factor=0.0` and `max_grid_kwh=0.0` survive compilation and are recorded in the trace; a reserve above capacity
fails closed. **106/106 tests pass**, `ruff check .` is clean.

**P4 — Shared LP/MILP model**

- **`app/optimizer/model.py`** — `OptimizationModel`: one variable layout (`g, s, c, d, E, yc, yd` — 168 variables,
  49 equality rows, 72 inequality rows) and one constraint builder shared by both the LP relaxation and the final
  MILP (Guide §12). It carries the objective, both constraint blocks, bounds, and the `integrality` vector, plus
  `scipy_bounds()`, `cost_of()`, `split()`, and `residuals()` helpers. Deliberately **has no `stage` parameter** —
  the LP and MILP cannot be handed different problems, which is what makes the `LP_cost <= MILP_cost` invariant
  (D-02) meaningful rather than trivially true. Directives enter purely as variable bounds; the model itself never
  inspects a directive.

Verified: all 44 published reference schedules are feasible points of the model as built (equality, inequality,
and bound residuals all below 1e-9), and the objective reproduces every published `total_cost_bdt` to 1e-6. The
residual check was probed to confirm it actually reacts to a bad plan (a +5 kWh grid nudge and a +12 kWh capacity
breach are both measured exactly, not silently absorbed). An uncommitted solver probe — driving these matrices
through `linprog(method="highs")` and `scipy.optimize.milp` directly — already solves all 44 cases with
`LP <= MILP` holding everywhere and the MILP objective matching the published optimum exactly; P5 will turn that
probe into the real solver modules. **122/122 tests pass**, `ruff check .` is clean.

## What is not done yet

The LP relaxation and MILP solver modules (`optimizer/lp_relaxation.py`, `optimizer/milp_solver.py`,
`optimizer/hybrid_solve.py`), the plan canonicalizer/response builder, the LLM directive interpreter, deterministic
guardrails, repair/retry logic, caching, observability, Docker packaging, deployment, the demo layer, and CI. See
the phase board in `IMPLEMENTATION_TRACKER.md` §6 (`P5`–`P20`) for the full remaining scope and
`IMPLEMENTATION_TRACKER.md` §1 for the live status snapshot.

> A known correctness issue was found by `/code-review` in the P3 directive-compiler code (an ordering disagreement
> between `compile_directives()` and `derive_envelope()` under a non-default overlap policy) — tracked in
> [CODE_REVIEW.md](CODE_REVIEW.md), not yet fixed.

## Repository layout

```
app/
  api/            HTTP routes, error mapping, middleware        — implemented (P1)
  schemas/        Pydantic request/response/directive models    — implemented (P1)
  llm/            LLM interpreter, prompts, provider adapters    (not yet implemented)
  guardrails/     Deterministic validation of LLM output         (not yet implemented)
  optimizer/      Directive compiler, LP relaxation, MILP solver — compile_directives.py (P3) + model.py shared variable layout (P4) implemented; LP/MILP solver modules not yet implemented
  validation/     Independent replay validator, totals           — implemented (P1 request_semantics.py + P2 replay.py/totals.py)
  services/       Orchestration of the full request pipeline     — stub: validates, then raises PipelineNotImplemented (P1)
  observability/  Structured logging, metrics                    (not yet implemented)
  cache/          Request/response caching                       (not yet implemented)
  demo/           Optional demo routes behind DEMO_MODE           (not yet implemented)
  policies/       Config-flagged spec-gap policies                — implemented (P3)
  config.py       Typed Settings — implemented
  main.py         FastAPI app entrypoint — implemented (P1)

docs/             Organizer documents and team specs — read-only, never edited
public_cases/     Copy of the organizer's 10-case sample pack (regression seed)
tests/unit/       Schema, config, replay-validator, directive-compiler, spec-gap-policy, optimization-model unit tests
tests/integration/ API contract / error-mapping tests
IMPLEMENTATION_TRACKER.md   Live status, locked/open decisions, phase board, session log
CODE_REVIEW.md    Running /code-review findings log — status tracked across passes
CLAUDE.md         Repository instructions and non-negotiable rules for AI-assisted work
```

## Running what exists today

The service now starts and answers `/health` and `/optimize-energy`, though the latter always returns a controlled
500 (`PipelineNotImplemented`) for a valid request, since there is no optimizer or LLM interpreter behind it yet.

```bash
pytest                                              # 122/122 passing
ruff check .                                        # clean
uvicorn app.main:app --host 0.0.0.0 --port 8000     # run the service
curl http://localhost:8000/health                   # -> {"status":"ok"}
```

The commands below are the **intended** interface once later phases land (see
[docs/IMPLEMENTATION_GUIDE.md](docs/IMPLEMENTATION_GUIDE.md) and `IMPLEMENTATION_TRACKER.md` §7) — they do not work
yet:

```bash
python scripts/run_public_cases.py public_cases/sample_cases.json   # 10-case regression
python scripts/benchmark_latency.py                 # p95 check
docker build -t gridwise . && docker run -p 8000:8000 --env-file .env gridwise
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
- Testing is targeted at correctness-critical surfaces (guardrails, replay, compiler, solvers, error mapping,
  semantics) rather than blanket coverage.

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
etc.) is planned as task `T-200` in the final documentation phase, once the service is functional.
