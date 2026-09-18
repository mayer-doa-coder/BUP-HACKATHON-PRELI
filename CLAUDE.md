# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository state

This is a **greenfield repo**: only `LICENSE` and `docs/` exist. No application code, `pyproject.toml`, `requirements.txt`, tests, or README yet. The service described below has to be built from scratch following [docs/IMPLEMENTATION_GUIDE.md](docs/IMPLEMENTATION_GUIDE.md).

Project: **GridWise** — an LLM-assisted smart-campus energy optimizer for the BUP CSE Fest 2026 hackathon preliminary. One HTTP service, judged by an automated harness.

**Start every session by reading [IMPLEMENTATION_TRACKER.md](IMPLEMENTATION_TRACKER.md).** It carries the live status, the locked/open decisions, the phased task board (`T-001`..`T-202`), and the session log, so work can resume in a new chat without re-reading `docs/`. Update it as part of every task — the task marker, the status snapshot, and a session-log entry.

## Source document hierarchy

| Document | Authority |
|---|---|
| [docs/BUP_CSE_FEST_2026_Preliminary_Problem_Statement_GridWise_LLM.md](docs/BUP_CSE_FEST_2026_Preliminary_Problem_Statement_GridWise_LLM.md) | **Canonical** — API schema, directives, guardrails, battery/energy rules, validity |
| [docs/BUP_CSE_FEST_2026_Participant_Guide_%26_Evaluation_Rubric_GridWise_LLM.md](docs/BUP_CSE_FEST_2026_Participant_Guide_%26_Evaluation_Rubric_GridWise_LLM.md) | **Canonical** — deployment, scoring, penalties, latency, submission |
| [docs/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json](docs/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json) | 10 worked cases — regression seed only, **not** the hidden judge set |
| [docs/PRD.md](docs/PRD.md) | Team product spec (FR-01..FR-14, NFRs, risks) |
| [docs/IMPLEMENTATION_GUIDE.md](docs/IMPLEMENTATION_GUIDE.md) | Team build guide (module layout, code skeletons, config, CI, Docker) |
| [docs/GridWise-Deep-Research.md](docs/GridWise-Deep-Research.md) | Supplementary research — never overrides organizer docs |

The organizer documents in `docs/` are **read-only**. Do not edit, reformat, or "fix" them; if the Problem Statement and any other document disagree, the Problem Statement wins.

## Non-negotiable rules

- **The LLM never creates the energy schedule.** It only translates operator notes into a fixed directive schema. The optimizer produces every kWh number.
- **Never invent directive types.** The taxonomy is closed (see below). An unknown type from the model is a guardrail rejection, never a silent coercion.
- **Never change the official API response schema.** No debug, confidence, solver, trace, or demo fields inside the `/optimize-energy` body.
- **MILP is the authoritative final optimizer.** LP is relaxation / feasibility screening / lower bound only; never return the LP plan.
- **Never hard-code public sample wording, IDs, values, or schedules.** Hidden notes paraphrase. A regex/keyword matcher may never be the semantic fallback — that fails the mandatory-LLM requirement outright.
- **Every implementation step ships with tests**, and tests are run after each meaningful change.
- LLM output is untrusted data until deterministic guardrails pass. Fail closed; never crash.

## Pipeline

```
HTTP Request
  -> Pydantic validation + hour canonicalization (sort by `hour`, don't trust array order)
  -> Baseline feasibility LP (no directives)       -> infeasible => controlled 422
  -> LLM directive interpreter (ONE structured call for all notes)
  -> Deterministic guardrails                      -> reject / one bounded repair
  -> Directive compiler (per-hour parameters)
  -> LP relaxation of directive-constrained model  -> infeasible => one focused reinterpretation
  -> Final MILP (authoritative)                    -> assert LP_cost <= MILP_cost + tol
  -> Canonicalize + serialize + parse back
  -> Independent replay of the exact response values -> fail => controlled 500
  -> Exact API response
```

Replay failure is an invariant failure: never retry semantics blindly, never return HTTP 200.

## Directive taxonomy (closed set)

| type | `structured_adjustment` | optimizer effect |
|---|---|---|
| `solar_reduction` | `{"hours":[...], "factor": n}` | `effective_solar[h] = solar[h] * factor` |
| `minimum_battery_reserve` | `{"hours":[...], "minimum_energy_kwh": n}` | `E[h] >= max(base_min, directive_min)` |
| `no_charge_window` | `{"hours":[...]}` | `c[h] = 0` |
| `no_discharge_window` | `{"hours":[...]}` | `d[h] = 0` |
| `max_grid_window` | `{"hours":[...], "max_grid_kwh": n}` | `g[h] <= max_grid_kwh` |
| `no_op` | `null` | none |

Semantic rules that cost points when wrong:

- `factor` is the **fraction remaining**: "reduced to 20%" and "80% reduction" both map to `0.2`; "reduced by 20%" / "operating at 80%" map to `0.8`.
- Time windows are **start-inclusive, end-exclusive**: 1 PM–3 PM -> `[13,14]`; "6 until 9 PM" -> `[18,19,20]`.
- `hours` must be unique ints 0–23 in **ascending** order.
- `applies=false` **only** with `no_op` + `structured_adjustment=null`; every other directive has `applies=true`.
- Exactly one interpretation entry per note, emitted in `note_index` order 0..N-1.
- `factor=0.0` and `max_grid_kwh=0.0` are valid — never lose them to truthiness checks.
- Percentage reserves resolve against battery capacity, so the prompt needs battery context (but **not** the 24-hour demand/solar/tariff matrix).

Guardrails may only sort by `note_index`, sort an already-unique hour set, normalize `-0.0`, and trim whitespace. They must never deduplicate hours, clip out-of-range numbers, or repair semantics.

## Energy model

```
g[h] + s[h] + d[h] = demand[h] + c[h]          # balance, every hour
E[0] = initial + c[0] - d[0];  E[h] = E[h-1] + c[h] - d[h]
E[23] = initial_energy_kwh                     # end-of-day neutrality
active_min[h] <= E[h] <= capacity
0 <= s[h] <= effective_solar[h]                # curtailment allowed, no export
0 <= c[h] <= max_charge * yc[h];  0 <= d[h] <= max_discharge * yd[h];  yc[h] + yd[h] <= 1
minimize  sum(g[h] * tariff[h])
```

`idle` is derived when both magnitudes are zero. No efficiency loss, degradation cost, or export revenue on the judge path — the organizer doesn't define them.

Totals (`total_grid_kwh`, `total_cost_bdt`, `peak_grid_kwh`) are always recomputed from the returned plan, never taken from the LLM. Judge tolerance is 0.01 kWh / 0.01 BDT; internal tolerance should be tighter. Do not round energy fields to two decimals — serialize with enough precision and reconstruct dependent state consistently.

Directive composition: reserves combine with pointwise `max`, grid caps with pointwise `min`, charge/discharge bans as hard booleans (both on the same hour forces idle).

## API contract

- `GET /health` -> `200 {"status":"ok"}`. No LLM or solver call; readiness only.
- `POST /optimize-energy` -> `scenario_id`, `directive_interpretation`, `hourly_plan` (24 entries), `total_grid_kwh`, `total_cost_bdt`, `peak_grid_kwh`, `plan_summary`.

Error mapping — FastAPI defaults to 422 for body-validation errors, so override explicitly:

```
malformed JSON / missing field / wrong type / bad hour set  -> 400
cross-field semantic invalidity, baseline-infeasible        -> 422
LLM unusable after budget, solver failure, replay failure   -> 500 (sanitized, correlation ID only)
```

Never leak stack traces, prompts, provider payloads, or secrets in responses or logs.

## Planned stack and commands

Nothing is wired up yet. When scaffolding, follow sections 2–4 and 34 of the implementation guide: Python 3.12, FastAPI, Pydantic v2, NumPy, `scipy.optimize.linprog(method="highs")` for LP and `scipy.optimize.milp` for MILP, pytest, ruff, Docker.

Intended commands (create these as part of scaffolding):

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000     # run service
pytest                                              # full suite
pytest tests/unit/test_x.py::test_y                 # single test
ruff check .                                        # lint
python scripts/run_public_cases.py public_cases/sample_cases.json   # 10-case regression
python scripts/benchmark_latency.py                 # p95 check
docker build -t gridwise . && docker run -p 8000:8000 --env-file .env gridwise
```

Config lives in `.env` (`.env.example` committed, real `.env` gitignored). `PROMPT_VERSION`, `SCHEMA_VERSION`, the exact pinned model ID, `OPTIMIZER_VERSION`, and commit SHA belong in cache keys and diagnostics — a parser cache keyed only on note text is a correctness bug.

## Build order

Optimizer before LLM. Per section 43 of the guide: schemas + error mapping -> replay validator -> directive compiler -> shared LP/MILP model -> solvers -> canonicalizer + serialized replay -> public-case regression -> LLM interpreter -> guardrails -> repair logic -> end-to-end regression -> adversarial corpus -> property/metamorphic tests -> caching/limits -> metrics -> Docker/deploy -> demo layer -> CI/docs.

## Testing expectations

- All 10 public cases must pass interpretation semantics, LP feasibility, MILP optimality, `LP <= MILP + tol`, serialized replay, and reference cost within tolerance. Action sequences need not match the reference — equivalent optimal schedules are accepted.
- Guardrail fixtures inject malformed model output: unknown type, duplicate/missing `note_index`, duplicate or unsorted hours, `factor` above 1 / negative / NaN, reserve above capacity, negative grid cap, wrong `applies`, non-null `no_op` adjustment, refusal, truncation.
- Semantic corpus (hundreds of fixtures): 12h/24h phrasing, noon/midnight, shared AM/PM suffix, `until`/`between`/number words, unicode dashes, fractions and decimal percentages, the `to`/`by`/`reduction`/`operates at` contrast set, zero factor and zero grid cap, capacity-relative reserves, distractors containing energy vocabulary, prompt injection.
- Metamorphic properties: more available solar cannot raise optimal cost; tightening a feasible reserve or grid cap cannot lower it; removing a hard constraint cannot worsen the objective.

## Provisional policies (spec gaps — not organizer rules)

Keep these isolated and config-flagged so organizer clarification is a one-line change; never describe them as canonical:

- cross-midnight windows -> modulo-24 expansion, serialized ascending (`11 PM–2 AM` -> `[0,1,23]`)
- `through` wording -> end-exclusive
- single-hour phrasing ("the 4 PM hour") -> `[16]`
- overlapping differing solar factors -> most restrictive `min(factor)` plus an internal ambiguity flag
- negative tariff is **not** rejected — the request schema never forbids it

## Scoring context

100 points: 25 interpretation + 25 directive application/constraint correctness + 10 optimization quality + 10 API contract + 10 performance/reliability + 10 deployment/Docker + 10 documentation. Optimization credit is `min(1, organizer_optimal / team_cost)` and is **zero** for any case that fails validity — correctness strictly precedes cost. `/optimize-energy` must answer within 30s; p95 at or under 5s earns full latency credit (internal target around 4.5s).
