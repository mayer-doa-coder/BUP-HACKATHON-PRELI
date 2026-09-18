# GridWise

LLM-assisted smart-campus energy optimizer for the **BUP CSE Fest 2026 Hackathon Preliminary**.

One HTTP service. It reads 1–3 free-text operator notes plus a 24-hour demand / solar / tariff / battery
scenario, and returns a cost-optimal 24-hour grid-and-battery dispatch plan.

The split of responsibility is the whole design:

> **The language model never produces a kilowatt-hour.** It only translates operator notes into a closed,
> typed directive schema. Every number in the response comes from a deterministic MILP optimizer.

---

## Status

Complete and verified end to end.

| Check | Result |
|---|---|
| Test suite | **458 passed**, `ruff` clean |
| Public sample cases (live, through the real model) | **10/10**, cost gap **+0.00** on every case |
| API contract audit | **279/279** checks, exit code 0 |
| Latency, cold caches, every case a real model call | p50 ~2.5 s, **p95 3.26 s** (rubric: ≤5 s for full credit) |
| Docker | builds, runs, healthy, passes all of the above inside the container |

`+0.00` means the exact published optimum, not merely within the 0.01 tolerance.

Owned elsewhere by teammates: the Azure deployment and the submission video.

---

## Quick start

### Docker (recommended — this is what gets deployed)

```bash
cp .env.example .env      # then fill in LLM_MODEL and LLM_API_KEY
docker compose up -d --build
```

The API is on **http://localhost:8000**. See [DOCKER.md](DOCKER.md) for image details and Azure notes.

### Local Python

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env      # then fill in LLM_MODEL and LLM_API_KEY
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Python **3.12** in the image; 3.14 also works for local development.

### After deploying — do not skip this

```bash
python scripts/warm_canary.py
```

The first request against a cold model costs roughly **8 seconds** (connection setup plus model/schema
warm-up); warm requests cost about 2.5 s. The canary pays that cost on your behalf and verifies credentials,
schema, guardrails and semantics against the real provider. **Run it after deploy and before judging**, or the
first judged request pays the cold cost.

---

## API

Two endpoints, one service, one origin.

### `GET /health`

Readiness only — makes no LLM or solver call.

```json
{ "status": "ok" }
```

### `POST /optimize-energy`

Request (abbreviated — 24 hour entries required):

```json
{
  "scenario_id": "SAMPLE-02",
  "operator_notes": ["The battery charger will be isolated from 2 AM until 5 AM for electrical maintenance."],
  "hours": [{ "hour": 0, "demand_kwh": 100, "solar_kwh": 0, "tariff_bdt_per_kwh": 6 }],
  "battery": {
    "capacity_kwh": 200, "initial_energy_kwh": 70, "minimum_energy_kwh": 30,
    "max_charge_kwh_per_hour": 55, "max_discharge_kwh_per_hour": 55
  }
}
```

Response — exactly seven top-level fields, no more:

```json
{
  "scenario_id": "SAMPLE-02",
  "directive_interpretation": [{
    "note_index": 0, "applies": true, "directive_type": "no_charge_window",
    "structured_adjustment": { "hours": [2, 3, 4] },
    "explanation": "Battery charging is unavailable during maintenance."
  }],
  "hourly_plan": [{
    "hour": 0, "grid_kwh": 120.0, "solar_used_kwh": 0.0,
    "battery_action": "charge", "battery_kwh": 20.0, "battery_energy_after_kwh": 90.0
  }],
  "total_grid_kwh": 2915.0,
  "total_cost_bdt": 42885.0,
  "peak_grid_kwh": 180.0,
  "plan_summary": "Avoids charging during the maintenance window, …"
}
```

### Error mapping

FastAPI answers 422 for body-validation errors by default, which is wrong here, so it is overridden explicitly.

| Condition | Status |
|---|---|
| Malformed JSON, missing field, wrong type, bad hour set, 0 or >3 notes | **400** |
| Well-formed but semantically invalid; baseline-infeasible scenario | **422** |
| LLM unusable after budget, solver failure, replay failure | **500** |

A 500 body carries a correlation ID and nothing else — never a stack trace, prompt, provider payload or secret.

---

## How it works

```
HTTP request
  → Pydantic validation + hour canonicalization (sorted by `hour`; array order is never trusted)
  → Baseline feasibility LP, no directives          → infeasible ⇒ controlled 422
  → LLM directive interpreter (ONE structured call for all notes)
  → Deterministic guardrails                        → reject, or one bounded repair
  → Directive compiler (per-hour parameters)
  → LP relaxation of the constrained model          → infeasible ⇒ one focused reinterpretation
  → Final MILP (authoritative)                      → assert LP_cost ≤ MILP_cost + tol
  → Canonicalize → serialize → parse back
  → Independent replay of the exact response values → fail ⇒ controlled 500
  → Response
```

Replay failure is treated as an invariant failure: never retried blindly, never returned as a 200.

### Directive taxonomy (closed set)

| `directive_type` | `structured_adjustment` | Optimizer effect |
|---|---|---|
| `solar_reduction` | `{"hours":[…], "factor": n}` | `effective_solar[h] = solar[h] * factor` |
| `minimum_battery_reserve` | `{"hours":[…], "minimum_energy_kwh": n}` | `E[h] ≥ max(base_min, directive_min)` |
| `no_charge_window` | `{"hours":[…]}` | `c[h] = 0` |
| `no_discharge_window` | `{"hours":[…]}` | `d[h] = 0` |
| `max_grid_window` | `{"hours":[…], "max_grid_kwh": n}` | `g[h] ≤ max_grid_kwh` |
| `no_op` | `null` | none |

An unrecognized type from the model is a guardrail rejection, never a silent coercion.

Two semantic rules cost points when wrong, so they are worth stating plainly:

- **`factor` is the fraction that remains.** "reduced to 20%" and "an 80% reduction" both give `0.2`;
  "reduced by 20%" and "operating at 80%" both give `0.8`.
- **Windows are start-inclusive, end-exclusive.** 1 PM–3 PM → `[13, 14]`; "6 until 9 PM" → `[18, 19, 20]`.

### Energy model

```
g[h] + s[h] + d[h] = demand[h] + c[h]            # balance, every hour
E[0] = initial + c[0] − d[0];  E[h] = E[h−1] + c[h] − d[h]
E[23] = initial_energy_kwh                       # end-of-day neutrality
active_min[h] ≤ E[h] ≤ capacity
0 ≤ s[h] ≤ effective_solar[h]                    # curtailment allowed, no export
0 ≤ c[h] ≤ max_charge · yc[h];  0 ≤ d[h] ≤ max_discharge · yd[h];  yc[h] + yd[h] ≤ 1
minimize  Σ g[h] · tariff[h]
```

168 variables. LP via `scipy.optimize.linprog(method="highs")`, MILP via `scipy.optimize.milp`.
`idle` is derived when both magnitudes are zero. Totals are always recomputed from the returned plan.

---

## Verifying it

Four independent levels of checking, all runnable against a deployed URL.

```bash
# 1. The full test suite (no network, no credentials needed)
pytest

# 2. Correctness: interpretation semantics, validity, and cost vs. the published optimum
python scripts/run_public_cases.py public_cases/sample_cases.json --endpoint http://localhost:8000

# 3. API contract: exactly what the judge sees, as a black box
python scripts/verify_contract.py --base-url http://localhost:8000 --cases 0 --fresh

# 4. Latency
python scripts/benchmark_latency.py
```

All of these also run inside the container:

```bash
docker exec gridwise python scripts/verify_contract.py --base-url http://127.0.0.1:8000 --cases 0 --fresh
docker exec gridwise python scripts/run_public_cases.py public_cases/sample_cases.json --endpoint http://127.0.0.1:8000
docker exec gridwise python scripts/warm_canary.py
```

**`scripts/verify_contract.py` is the submission gate.** It imports nothing from `app`, so a bug shared with the
implementation cannot hide from it. It checks that both endpoints answer on one origin, that `/health` returns
exactly `{"status":"ok"}` fast enough to serve as a readiness probe, that the response carries exactly the
documented fields and **no undocumented extras**, that directive types stay inside the closed taxonomy, that
every number re-derives from the returned plan (hourly balance, battery continuity, end-of-day neutrality,
bounds, rate limits, all three totals), that the 400/422 error mapping holds, and that no error body leaks a
secret or a stack trace. Exit code 0 means conformant.

> A container reporting `healthy` proves very little: the Docker healthcheck only probes `/health`, which by
> design makes no LLM call. A service that fails 100% of real requests still reports healthy. Run the contract
> audit against the deployed URL before judging.

### Other scripts

| Script | Purpose |
|---|---|
| `scripts/warm_canary.py` | Post-deploy warm-up + credential/schema/semantic smoke test; prints the version record |
| `scripts/verify_docker.py` | Builds the image and proves it serves the contract, runs non-root, bakes no secrets |
| `scripts/verify_solver.py` | Checks the LP/MILP stack inside the runtime environment |
| `scripts/semantic_corpus.py` | The paraphrase/adversarial corpus used by the interpreter tests |
| `scripts/paraphrase_eval.py` | Scores interpretation accuracy across paraphrases |
| `scripts/healthcheck.py` | Container `HEALTHCHECK` entry point |

---

## Configuration

Everything is environment-driven. `.env.example` is committed and holds **no values**; the real `.env` is
gitignored *and* excluded from the Docker build context.

Minimum to run:

```bash
LLM_PROVIDER=openai          # openai | openai_compatible | azure_openai | gateway | anthropic
LLM_MODEL=<pinned model id>
LLM_API_KEY=<key>
```

Settings worth knowing about:

| Variable | Default | Why it matters |
|---|---|---|
| `LLM_TEMPERATURE` | *(unset — omitted)* | **Leave blank.** Some models reject an explicit temperature with `400 unsupported_value` instead of ignoring it, which fails *every* request. Omitting the parameter works everywhere. |
| `LLM_ATTEMPT_TIMEOUT_SECONDS` | `12.0` | Must exceed a **cold** call (~8 s), not just a warm one (~2.5 s), or the first request after startup times out and retries. |
| `LLM_MAX_ATTEMPTS` | `2` | Bounded repair budget. |
| `MILP_RELATIVE_GAP` | `0.0` | HiGHS defaults to a 1e-4 MIP gap and returns near-optimal solutions with a success status. Must be 0 to claim proven optimality. |
| `HARD_REQUEST_DEADLINE_SECONDS` | `28.0` | Sits below the organizer's 30 s limit so fallbacks terminate in time. |
| `JUDGE_MODE` | `true` | Keeps the judged surface to exactly the two endpoints. |
| `DEMO_MODE` | `false` | Mounts an optional `/demo` router. Requires `JUDGE_MODE=false`. |
| `METRICS_ENABLED` | `true` | Prometheus-compatible `/metrics`, on its own router, outside the judged surface. |
| `APP_COMMIT_SHA` | *(unset)* | Set it at release; it appears in the version record and in cache keys. |

Cache keys include the prompt version, schema version, pinned model id, optimizer version and battery context —
a parser cache keyed only on note text would be a correctness bug.

The full list is in [.env.example](.env.example).

---

## Repository layout

```
app/
  main.py                    FastAPI app factory, lifespan, middleware order
  config.py                  typed Settings; API keys are SecretStr
  api/                       routes, error taxonomy → HTTP mapping, middleware
  schemas/                   request / directive (discriminated union) / response models
  llm/                       prompts, JSON schema, interpreter, bounded repair
    providers/               OpenAI-compatible and Anthropic adapters
  guardrails/                deterministic validation + normalization of model output
  optimizer/                 directive compiler, shared model, LP, MILP, hybrid solve
  validation/                independent replay, totals, request semantics
  services/                  orchestration, plan summary, per-request deadline
  observability/             structured logging, metrics, context-local tracing
  cache/                     request + parser caches
  policies/                  spec-gap policies, isolated and config-flagged
  demo/                      optional reviewer-facing layer, off by default

tests/                       unit · integration · property · regression · security
scripts/                     verification, benchmarking, operational tooling
public_cases/                the organizer's 10-case pack (byte-identical to docs/)
frontend/                    optional React + Vite demo UI (not part of the judged service)
docs/                        organizer documents — read-only
```

---

## Design decisions worth defending

**The LLM is a translator, not a planner.** It emits typed directives and nothing else. Every kWh is computed by
the optimizer from those directives. This is a hard requirement of the problem, and it is enforced structurally.

**No keyword fallback, ever.** When the model is unusable after the retry budget, the request fails closed with a
controlled 500. A regex matcher standing in for the model would defeat the mandatory-LLM requirement outright, so
that path does not exist.

**MILP is authoritative; LP is a screen.** The LP provides feasibility screening and a lower bound, and
`LP_cost ≤ MILP_cost + tol` is asserted on every solve. The LP plan is never returned.

**The replay validator shares no code with the optimizer.** It was written independently and reconstructs the
schedule from the serialized response alone. An AST-level import test enforces the separation, so a bug in the
optimizer cannot be mirrored by the thing meant to catch it.

**Model output is untrusted data.** Guardrails may only sort by `note_index`, sort an already-unique hour set,
normalize `-0.0` and trim whitespace. They must never deduplicate hours, clip out-of-range numbers or repair
semantics — silently "fixing" a wrong interpretation produces a confidently wrong plan.

**Rounding is not applied field by field.** Only independent decisions are rounded; battery level and grid draw
are derived from them, through a `(6, 9, None)` decimal precision ladder. Rounding every field independently
breaks end-of-day battery neutrality on long-decimal inputs.

**Nothing from the public samples is hard-coded.** No sample wording, IDs, values or schedules appear in the
decision path. Hidden notes paraphrase, and a matcher tuned to the public pack would score zero on them.

---

## Testing

```bash
pytest                                  # everything
pytest tests/unit/test_replay.py        # one file
pytest -k "guardrail"                   # by keyword
ruff check .
```

458 tests across five layers:

- **unit** — schemas, compiler, solvers, guardrails, replay, config, policies
- **integration** — the endpoint end to end with a stubbed provider; error mapping; live-provider tests (opt-in)
- **property / metamorphic** — more available solar cannot raise optimal cost; tightening a feasible reserve or
  grid cap cannot lower it; removing a hard constraint cannot worsen the objective
- **regression** — all 10 public cases, plus every bug ever found, pinned
- **security** — secret-leak checks, prompt-injection notes staying data-only, oversized bodies

Tests never make billable API calls: `tests/conftest.py` clears provider credentials at import unless
`GRIDWISE_TEST_ALLOW_LIVE=1` is set explicitly.

---

## Frontend (optional)

A small React + TypeScript + Vite demo UI lives in `frontend/`. It is **not** part of the judged service and is
not containerized — it exists to exercise the API by hand.

```bash
cd frontend
npm install
npm run dev     # http://localhost:5173
```

It shows only the documented response fields, builds a request from the public samples or by hand, and proxies
`/api/*` to the backend server-side to avoid CORS. The proxy targets `127.0.0.1:8000` deliberately: Node resolves
`localhost` to IPv6 first, and if anything else holds the IPv6 side of port 8000 — a published Docker container
is the usual culprit — requests silently go to that instead. Override with `VITE_BACKEND_URL`.

---

## Provisional policies (spec gaps, not organizer rules)

The Problem Statement does not define these cases. Each is isolated and config-flagged so a clarification is a
one-line change. They are **not** presented as canonical.

| Case | Policy | Flag |
|---|---|---|
| Cross-midnight window (11 PM–2 AM) | modulo-24 expansion → `[0, 1, 23]` | `CROSS_MIDNIGHT_POLICY` |
| "through" wording | end-exclusive | `THROUGH_RANGE_POLICY` |
| Overlapping different solar factors | most restrictive `min(factor)` + internal ambiguity flag | `SOLAR_OVERLAP_POLICY` |
| Single-hour phrasing ("the 4 PM hour") | `[16]` | — |
| Negative tariff | accepted; the request schema never forbids it | — |

---

## Further reading

| Document | Contents |
|---|---|
| [IMPLEMENTATION_TRACKER.md](IMPLEMENTATION_TRACKER.md) | Live status, locked decisions, task board, release gates, session log |
| [DOCKER.md](DOCKER.md) | Image internals, deployment notes |
| [CODE_REVIEW.md](CODE_REVIEW.md) | Review findings and their resolutions |
| [CLAUDE.md](CLAUDE.md) | Working rules for AI-assisted contributions |
| `docs/` | Organizer documents — **read-only**; the Problem Statement wins any disagreement |

## License

MIT — see [LICENSE](LICENSE).
