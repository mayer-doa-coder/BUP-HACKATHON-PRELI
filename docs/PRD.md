# GridWise — LLM-Assisted Smart Campus Energy Optimizer
## Product Requirements Document (PRD)

**Version:** 1.1  
**Research date:** 2026-09-18  
**Target:** BUP CSE Fest 2026 Hackathon — Online Preliminary  
**Primary API:** `GET /health`, `POST /optimize-energy`  
**Product strategy:** maximize correctness, robustness, reproducibility, and demonstrable engineering depth without changing the canonical judge contract.

---

## 1. Source Hierarchy

This PRD is grounded in the three organizer-provided files:

1. `BUP_CSE_FEST_2026_Preliminary_Problem_Statement_GridWise_LLM` — **canonical source** for challenge behavior, request/response schema, directives, guardrails, energy accounting, battery behavior, and optimization validity.
2. `BUP_CSE_FEST_2026_Participant_Guide_&_Evaluation_Rubric_GridWise_LLM` — **canonical source** for deployment, repository policy, scoring, performance, penalties, tie-breakers, documentation, and submission requirements.
3. `BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json` — ten public reference cases used for local validation. Public cases are not the hidden judge set.

Web research in Section 22 is **supplementary engineering guidance only**. It must never override the organizer documents.

---

## 2. Product Vision

Build a reliable, judge-safe smart-campus energy scheduling service that:

1. understands natural-language operator notes using an LLM;
2. converts each note into exactly one supported machine-readable directive or `no_op`;
3. validates the LLM output deterministically;
4. compiles valid directives into mathematical constraints;
5. computes a minimum-cost 24-hour grid/solar/battery schedule;
6. independently replays and verifies the schedule before returning it;
7. exposes a polished demonstration layer that makes the LLM reasoning boundary, constraints, energy flows, cost savings, and validation evidence easy to understand.

The core philosophy is:

> **LLM for language; deterministic code for trust; mathematical optimization for scheduling; independent replay for proof.**

This is aligned with both the organizer specification and current research on combining LLMs with external optimization solvers and deterministic guardrails.

---

## 3. Problem Statement

BUP has a 24-hour campus energy scenario. For each hour, the input provides:

- campus electricity demand;
- available rooftop solar energy;
- grid tariff.

The input also provides a battery with:

- capacity;
- starting energy;
- minimum energy reserve;
- maximum hourly charge;
- maximum hourly discharge.

Additionally, the operator provides 1–3 natural-language notes. A note may create one supported operational directive, or it may be an irrelevant distractor.

The system must interpret the notes, apply all valid directives, and produce the lowest-cost valid 24-hour operating plan.

The supported directive types are exactly:

- `solar_reduction`
- `minimum_battery_reserve`
- `no_charge_window`
- `no_discharge_window`
- `max_grid_window`
- `no_op`

No unpublished directive type may be invented.

---

## 4. Product Goals

### G1 — Exact contract correctness

The judge-facing endpoints, field names, types, ordering rules, and semantics must match the Problem Statement.

### G2 — Strong language understanding

The system must generalize across paraphrases, different time expressions, percentages, and equivalent numeric wording rather than memorizing public examples.

### G3 — Deterministic safety boundary

The LLM output is untrusted until validated by deterministic code. Invalid model output must never silently become an optimization constraint.

### G4 — Optimal, physically valid scheduling

The final plan must satisfy all energy, battery, solar, directive, and end-of-day rules before cost is considered.

### G5 — Reliability under repeated hidden tests

Normal requests should use one fast LLM call, deterministic validation, a small **LP-relaxation + MILP** optimization pass, and an independent final replay. Retries/fallbacks should be bounded.

### G6 — Reproducibility

A clean environment should be able to clone, configure, run, health-check, and validate at least one public sample without team assistance.

### G7 — Strong hackathon demonstration

The system should expose rich visual and engineering features without polluting or altering the exact judge response.

---

## 5. Non-Goals / Explicit Boundaries

The product must **not**:

- use live campus, utility, billing, or personal data;
- perform long runtime training or fine-tuning during evaluation;
- use an LLM only for `plan_summary` while bypassing it for note interpretation;
- use hard-coded phrase matching as the sole note interpreter;
- allow grid export;
- consume the starting battery as free one-time energy by ending below the initial state;
- add new directive types;
- trust LLM arithmetic or LLM-generated schedules instead of a solver;
- return demo-only fields inside the canonical `/optimize-energy` response;
- expose API keys, raw secrets, stack traces, or sensitive configuration.

The source documents do not specify battery efficiency losses, degradation cost, forecast uncertainty, grid export, or stochastic optimization. Those concepts can appear in a **demo-only research sandbox**, but they must not change the official judge path.

---

## 6. Users and Stakeholders

### 6.1 Automated judge

Needs exact schema, correct interpretation, valid optimization, low latency, stability, and reproducibility.

### 6.2 Organizer/reviewer

Needs to understand the architecture and verify that the LLM genuinely interprets operator notes and that deterministic guardrails/optimization enforce correctness.

### 6.3 Team developer

Needs typed models, deterministic tests, replayable failures, useful logs, local sample-case runner, Docker, and CI.

### 6.4 Demo viewer / tie-break reviewer

Needs an intuitive visual story showing:

- what the human note said;
- what the LLM extracted;
- what the guardrail accepted/rejected;
- what constraint was applied;
- how the optimizer changed the schedule;
- why the final plan is valid;
- how much the optimized plan costs.

---

## 7. Product Principles

1. **Canonical contract first.**
2. **Probabilistic interpretation, deterministic enforcement.**
3. **Never let the LLM directly control energy variables.**
4. **Fail closed on malformed/unsupported model output.**
5. **Do not invent semantics when the source documents are silent.**
6. **Judge path stays minimal; showcase features stay isolated.**
7. **Every returned schedule must be independently replayable.**
8. **Every important failure should be observable and reproducible.**
9. **Development time is not used as a scope limiter; official runtime latency still matters.**

---

## 8. Success Metrics and Rubric Coverage

The Participant Guide uses a 100-point model:

| Area | Official points | Product capability |
|---|---:|---|
| LLM Directive Interpretation | 25 | strict structured output, complete note coverage, paraphrase robustness, percentage/time normalization |
| Directive Application & Constraint Correctness | 25 | directive compiler, exact constraint application, independent final replay |
| Optimization Quality | 10 | LP-assisted MILP optimizer, exact final MILP schedule, LP lower-bound cross-check, optimal cost, solver status checks |
| API Contract & Schema | 10 | FastAPI/Pydantic strict models, exact response, error mapping |
| Performance & Reliability | 10 | bounded LLM timeout/retry, cache, provider fallback, metrics, no-crash handling |
| Deployment & Docker Fallback | 10 | reproducible Docker image, health check, bind `0.0.0.0`, no secrets |
| Documentation & Local Reproducibility | 10 | copy-paste quickstart, sample runner, environment documentation, architecture docs |

Additional tie-break quality is strengthened by:

- polished 3-minute demo;
- pipeline trace;
- validation proof;
- robustness dashboard;
- request replay;
- solver explainability;
- high-quality tests;
- multi-provider fallback;
- sanitized observability.

---

## 9. Canonical End-to-End Flow

```text
HTTP Request
    |
    v
Strict Request Validation
    |
    v
LLM Directive Interpreter
    |
    v
Structured Directive Schema
    |
    v
Deterministic Guardrails
    |
    v
Directive Compiler
    |
    v
Hybrid LP + MILP Optimization Model
    |
    v
LP Relaxation -> Final MILP Solver
    |
    v
Canonical Plan Builder
    |
    v
Independent Final Replay Validator
    |
    +---- invalid ---> controlled failure / bounded reinterpretation retry
    |
    v
Exact Response Builder
    |
    v
HTTP JSON Response
```

The demo layer consumes copies of the validated internal trace. It does not sit between the judge and the canonical response.

---

## 10. Functional Requirements

### FR-01 — Health endpoint

`GET /health`

**Required behavior**

- return HTTP 200 only when the service is ready;
- safest canonical response:

```json
{"status":"ok"}
```

No LLM call or solver call is needed for health.

---

### FR-02 — Optimization endpoint

`POST /optimize-energy`

Must accept exactly one scenario object with:

- `scenario_id`
- `operator_notes`
- `hours`
- `battery`

Must return:

- `scenario_id`
- `directive_interpretation`
- `hourly_plan`
- `total_grid_kwh`
- `total_cost_bdt`
- `peak_grid_kwh`
- `plan_summary`

The judge-facing response must not contain internal debugging, confidence, solver diagnostics, prompts, model metadata, or demo fields.

---

### FR-03 — Strict input validation

Validate before any LLM call:

- `scenario_id` is a string;
- `operator_notes` contains 1–3 non-empty strings;
- `hours` contains exactly 24 entries;
- hour IDs are unique and represent `0..23`;
- all required hour fields are present;
- battery fields are present and finite;
- capacity/rate/reserve values are physically valid;
- `initial_energy_kwh` and base reserve do not exceed capacity;
- malformed JSON is handled as a controlled client error.

Do not silently fill missing inputs.

---

### FR-04 — Mandatory LLM interpretation

The LLM must be part of the path producing the structured directives that are used by the optimizer.

The LLM receives:

- the directive taxonomy;
- exact structured output schema;
- time-window convention;
- solar factor convention;
- battery context needed to resolve reserve percentages;
- operator notes clearly delimited as untrusted data;
- optionally the full scenario facts for resolving explicit relative references.

The LLM must return exactly one interpretation per note.

---

### FR-05 — Directive schema

Every interpretation contains:

- `note_index`
- `applies`
- `directive_type`
- `structured_adjustment`
- `explanation`

Rules:

- `no_op` => `applies=false`, `structured_adjustment=null`
- all other types => `applies=true`
- hours are unique integers `0..23`, ascending;
- one entry per note, no duplicate `note_index`;
- response order is `0..N-1`.

---

### FR-06 — Semantic normalization

Required language behaviors include:

- `1 PM to 3 PM` -> `[13,14]`;
- start included, end excluded;
- `80% reduction` -> remaining factor `0.2`;
- `25% of forecast` -> factor `0.25`;
- percentage battery reserve -> kWh using battery capacity;
- natural time forms such as `noon`, `midnight`, `one until three`, `13:00`;
- paraphrases that mean the same rule should normalize to the same directive.

The public pack specifically includes an emergency reserve expressed as a percentage of battery capacity, so capacity-aware interpretation is required.

---

### FR-07 — Deterministic guardrail validator

The validator must reject or trigger bounded repair when any of these fail:

- unsupported directive type;
- missing/duplicate/out-of-range note index;
- illegal `applies` semantics;
- wrong adjustment shape for the directive type;
- duplicate/out-of-range hours;
- non-ascending hour list after normalization;
- `solar_reduction.factor` outside `[0,1]`;
- reserve negative, non-finite, or above capacity;
- `max_grid_kwh` negative or non-finite;
- extra unsupported fields if strict schema is used.

Safe normalizations are allowed:

- sort entries by `note_index`;
- sort unique hours;
- normalize near-zero floating artifacts;
- canonicalize explanation whitespace.

Semantic values must not be invented by deterministic code.

---

### FR-08 — Bounded interpretation repair

Normal path: one LLM call.

If structured output fails guardrails:

1. issue one repair call containing the original note plus a concise validation-error summary;
2. validate again;
3. optionally fail over to a configured backup LLM provider;
4. if still invalid, return a controlled error.

A regex/keyword interpreter must never become the hidden semantic fallback.

---

### FR-09 — Directive compiler

Compile validated directives into per-hour deterministic parameters:

- `effective_solar[h]`
- `active_minimum_energy[h]`
- charge permission
- discharge permission
- `grid_upper_bound[h]`

Composition rules:

- reserve constraints combine with `max`;
- grid caps combine with `min`;
- no-charge/no-discharge windows combine as hard booleans;
- overlapping same-hour solar-reduction directives with inconsistent factors are treated as a conflict rather than silently guessing a new meaning.

The organizer states valid scoring scenarios are feasible and will not require contradictory hard directives.

---

### FR-10 — Optimization engine

The primary optimizer must minimize:

```text
sum(grid_kwh[h] * tariff_bdt_per_kwh[h])  for h=0..23
```

subject to:

- hourly demand balance;
- effective solar limit;
- battery capacity and reserve;
- hourly charge/discharge rate limit;
- directive constraints;
- final battery energy equals initial battery energy;
- non-negative grid and solar use.

A linear formulation is preferred because this problem is small, deterministic, easy to verify, and solver-backed.

---

### FR-11 — Independent final replay

After solving, a separate validator recomputes the plan from the response values.

It checks:

- 24 unique hours;
- finite/non-negative response values where required;
- energy balance every hour;
- battery transition every hour;
- battery min/capacity;
- charge/discharge limits;
- no-charge and no-discharge windows;
- reserve constraints;
- effective solar;
- grid caps;
- final battery neutrality;
- `total_grid_kwh`;
- `total_cost_bdt`;
- `peak_grid_kwh`.

A plan that fails final replay must never be returned as HTTP 200.

---

### FR-12 — Plan summary

Return a short human-readable `plan_summary`.

Recommended judge-path behavior: generate it deterministically from the validated directives and plan so a second LLM call cannot hurt latency/reliability.

A richer LLM-generated explanation may be shown in demo mode outside the canonical response.

---

### FR-13 — Controlled error behavior

- malformed or structurally invalid request: controlled 400;
- semantically invalid but well-formed request: optional controlled 422;
- provider/solver/internal failure: controlled 500 without raw stack trace or secrets.

Internally log a correlation ID and sanitized failure class.

---

### FR-14 — Reproducibility

Repository must include:

- environment-variable names;
- exact install/run command;
- model/provider configuration;
- LLM role;
- guardrail description;
- optimizer/solver choice;
- `/health` example;
- `/optimize-energy` example;
- public sample test command;
- Docker pull/run;
- dependency credits;
- known limitations;
- no secret values.

---

## 11. Non-Functional Requirements

### NFR-01 — Latency

Official limits:

- `/optimize-energy` must finish within 30 seconds;
- p95 <= 5 seconds receives full latency credit.

Normal design target:

- request validation: < 10 ms;
- one LLM structured extraction call: dominant latency;
- directive compilation + LP relaxation + tiny MILP solve + replay: expected to remain very small for only 24 hours;
- fallback calls occur only on failure.

### NFR-02 — Availability

The submitted endpoint must remain reachable during evaluation.

### NFR-03 — Determinism

For the same validated interpretation and numeric input, optimization/replay output should be deterministic within floating-point tolerance.

### NFR-04 — Security

- secrets only through environment/configuration;
- no secrets in image/repository/logs/responses;
- operator notes treated as untrusted data;
- LLM has no tool, shell, database, web, or file permissions;
- raw prompt logging disabled by default;
- sanitize provider exceptions.

### NFR-05 — Numeric tolerance

Internal validation should be stricter than the organizer's published `0.01 kWh / 0.01 BDT` tolerance where practical, while final comparisons allow the official tolerance.

### NFR-06 — Observability

Track at least:

- request count;
- success/failure count;
- end-to-end latency histogram;
- LLM latency;
- guardrail failure count;
- repair/fallback count;
- solver latency/status;
- final-replay failure count;
- cache hit count.

---

## 12. Optimization Model Requirements

### 12.1 Chosen algorithm: LP-Assisted MILP

The production optimization algorithm is a **combined LP + MILP pipeline**:

1. **LP relaxation** solves the continuous relaxation of the full model first.
2. **MILP refinement** solves the same model with explicit binary charge/discharge mode decisions.
3. **Cross-check** compares the LP lower bound with the final MILP objective.
4. **Final replay** independently validates the MILP schedule before it is returned.

This is not an average or ensemble of two unrelated optimizers. The LP stage is a relaxation/diagnostic stage; the MILP stage is the authoritative final optimizer.

### 12.2 Continuous decision variables

For each hour `h`:

- `g[h]` = grid kWh;
- `s[h]` = solar used kWh;
- `c[h]` = battery charge kWh;
- `d[h]` = battery discharge kWh;
- `E[h]` = battery energy after hour `h`.

### 12.3 Binary operating-mode variables

For each hour:

- `yc[h] ∈ {0,1}` = charge mode enabled;
- `yd[h] ∈ {0,1}` = discharge mode enabled.

MILP exclusivity constraints:

```text
0 <= c[h] <= max_charge * yc[h]
0 <= d[h] <= max_discharge * yd[h]
yc[h] + yd[h] <= 1
```

`idle` is derived when both charge and discharge amounts are zero; a third binary variable is unnecessary.

### 12.4 Core equations

Energy balance:

```text
g[h] + s[h] + d[h] = demand[h] + c[h]
```

Battery transition:

```text
E[0] = initial_energy + c[0] - d[0]
E[h] = E[h-1] + c[h] - d[h]     for h > 0
E[23] = initial_energy
```

Bounds:

```text
0 <= g[h] <= active_grid_cap[h] (if any)
0 <= s[h] <= effective_solar[h]
0 <= c[h] <= max_charge
0 <= d[h] <= max_discharge
active_minimum_energy[h] <= E[h] <= capacity
```

Directive changes:

```text
solar_reduction:
  effective_solar[h] = original_solar[h] * factor

minimum_battery_reserve:
  active_minimum_energy[h] =
      max(base_minimum, directive_minimum)

no_charge_window:
  c[h] = 0
  yc[h] = 0

no_discharge_window:
  d[h] = 0
  yd[h] = 0

max_grid_window:
  upper_bound(g[h]) = max_grid_kwh
```

### 12.5 LP relaxation stage

Use the same model but relax:

```text
0 <= yc[h] <= 1
0 <= yd[h] <= 1
```

The LP stage provides:

- fast feasibility screening;
- a lower bound on cost;
- diagnostic/sensitivity information;
- optional warm-start information for a MIP backend that supports it.

The relaxed LP plan is not returned as the official schedule.

### 12.6 Final MILP stage

Restore:

```text
yc[h], yd[h] are binary
```

and solve the exact mixed-integer model. The canonical response is built only from this final MILP solution.

For a minimization problem, enforce the sanity check:

```text
LP_cost <= MILP_cost + numerical_tolerance
```

A significant violation indicates an implementation error.

### 12.7 Public-case verification

**Verification performed during this PRD update:** the combined model was evaluated against all 10 public sample scenarios using their published ground-truth directives. The LP relaxation and the final MILP both matched the published optimal total cost in all 10 cases, and the LP-to-MILP objective gap was zero for those public cases.

This zero public-case gap is expected for the published scenarios but should not be hard-coded as a general assumption; the architecture must still solve the final MILP and validate its discrete battery modes.

---

## 13. Judge-Safe Core vs Showcase Layer

### 13.1 Judge-safe core

Must remain minimal and exact:

- `/health`
- `/optimize-energy`
- strict request/response schemas
- one LLM interpretation pipeline
- deterministic guardrails
- optimizer
- final replay
- controlled errors

### 13.2 Showcase layer

Can be enabled with `DEMO_MODE=true` and kept outside the canonical response.

Recommended features:

1. **Interactive 24-hour energy dashboard**
   - demand
   - original/effective solar
   - grid import
   - battery charge/discharge
   - battery state of charge
   - tariff

2. **LLM interpretation trace**
   - raw note
   - parsed directive
   - structured adjustment
   - guardrail status

3. **Constraint timeline**
   - reserve windows
   - charge bans
   - discharge bans
   - grid caps
   - solar reductions

4. **Validation proof panel**
   - max energy-balance residual
   - max state-transition residual
   - final SoC delta
   - directive checks
   - totals reconciliation

5. **Cost comparison**
   - optimized plan
   - no-storage baseline when feasible
   - optional hypothetical no-directive plan clearly labeled as non-operational

6. **Active-constraint inspector**
   - show which constraints bind at each hour
   - optionally expose LP-relaxation dual/marginal values for educational explanation
   - show final MILP charge/discharge binary modes, objective bound, and MIP gap where available

7. **What-if lab**
   - adjust battery capacity
   - reserve
   - tariff
   - grid cap
   - solar availability
   - rerun optimizer
   - never mix this with the official request contract

8. **Paraphrase robustness lab**
   - compare different natural-language phrasings
   - verify they normalize to identical directives
   - visualize mismatches

9. **Provider/fallback dashboard**
   - provider health
   - structured-output failure rate
   - repair count
   - latency

10. **Public sample regression runner**
    - run all 10 public cases
    - show interpretation match
    - validity result
    - cost gap
    - latency

11. **Request replay**
    - sanitized request hash
    - interpretation
    - solver status
    - validation outcome
    - no secrets/raw sensitive provider payloads

12. **Scenario diff**
    - compare two schedules and highlight changed hours/constraints/cost

13. **OpenAPI explorer**
    - FastAPI-generated Swagger/ReDoc for development/demo

14. **Downloadable validation report**
    - export demo-only JSON/Markdown proof bundle
    - not part of judge response

15. **Model comparison mode**
    - optional offline/demo comparison across configured LLM providers
    - never use a voting result that bypasses deterministic guardrails

---

## 14. UX Requirements for Demo Dashboard

Recommended screen layout:

```text
+--------------------------------------------------------------+
| GridWise | Scenario ID | Status | Cost | Validation: PASS    |
+--------------------------------------------------------------+
| Operator Notes        | LLM Interpretation | Guardrail       |
+--------------------------------------------------------------+
| 24h Energy Flow Chart: Demand / Solar / Grid / Battery       |
+--------------------------------------------------------------+
| Tariff Chart          | Battery SoC Chart                    |
+--------------------------------------------------------------+
| Constraint Timeline   | Active Constraints / Why This Hour   |
+--------------------------------------------------------------+
| Cost Comparison       | Validation Proof                     |
+--------------------------------------------------------------+
| What-if / Paraphrase Lab / Sample Regression                 |
+--------------------------------------------------------------+
```

The dashboard should never imply that an LLM directly selected grid/battery quantities. Visually separate the LLM stage from the mathematical solver stage.

---

## 15. Reliability Features

### 15.1 Provider abstraction

Use a common interpreter interface so a backup provider/model can be configured without changing optimizer logic.

### 15.2 Deadline-aware retries

- one normal structured-output call;
- one repair call only on validation failure;
- backup provider only when configured and remaining deadline permits;
- no infinite retries.

### 15.3 Exact-request cache

Cache by a canonical hash of the complete request and model/schema version.

Benefits:

- repeated judge request stability;
- lower latency;
- lower provider cost;
- reproducible response.

Cache must not cause stale behavior after model/schema version changes.

### 15.4 Circuit breaker

Temporarily stop calling a consistently failing provider and route to a configured backup, while keeping the health endpoint responsive.

### 15.5 Solver fallback

Primary hybrid backend: SciPy/HiGHS using `linprog` for the LP relaxation and `milp` for the final mixed-integer solve.

Optional backup: another MIP-capable backend such as OR-Tools, CBC, or Gurobi using the same mathematical model.

The LP relaxation can still be used diagnostically if the MIP backend fails, but the service must not silently substitute a fractional LP relaxation for the authoritative MILP schedule. If the final solver reports non-optimal/infeasible unexpectedly, do not fabricate a plan.

---

## 16. Security Requirements

Operator notes are untrusted natural-language input.

Prompt design must clearly separate:

- developer/system rules;
- scenario facts;
- operator-note data.

The LLM should have **no tools**. It only emits a typed directive object.

Defenses:

- strict structured output;
- deterministic output validation;
- no raw secret values in prompts;
- no prompt or provider exception leakage;
- environment-based keys;
- `.env` ignored by Git;
- container runs as non-root where practical;
- dependency pinning;
- request body size guard at infrastructure layer;
- sanitized structured logging.

Prompt-injection screening can be included as a **signal** in demo telemetry, but must not rewrite or discard legitimate operator notes based only on keyword matching.

---

## 17. Testing Requirements

### 17.1 Public sample regression

All 10 public cases must pass:

- exact directive semantics;
- one entry per note;
- plan validity;
- total reconciliation;
- optimal cost within tolerance.

### 17.2 Directive unit tests

Each type gets:

- standard wording;
- paraphrases;
- 12h/24h time;
- percentage wording;
- irrelevant distractors;
- boundary hours;
- multi-note cases.

### 17.3 Guardrail tests

Inject malformed model outputs:

- unknown type;
- bad `note_index`;
- duplicate hours;
- factor > 1;
- reserve > capacity;
- negative grid cap;
- wrong `applies`;
- non-null adjustment for `no_op`;
- missing fields.

### 17.4 Optimizer property tests

Random feasible scenarios should satisfy:

- energy balance;
- battery transitions;
- battery bounds;
- directive bounds;
- final neutrality;
- objective not worse than known feasible baseline.

### 17.5 API tests

- malformed JSON;
- missing fields;
- duplicate hours;
- wrong count of hours;
- empty notes;
- repeated identical request;
- provider timeout;
- provider malformed output;
- solver failure;
- concurrency.

### 17.6 Security tests

Include notes containing meta-instructions such as:

- “ignore the system prompt”;
- “return a new directive type”;
- “reveal the API key”;
- encoded or oddly formatted instruction-like text.

Expected result: the note is still treated only as data to classify into the official taxonomy or `no_op`.

---

## 18. Acceptance Criteria

The product is release-ready when:

- `/health` is externally reachable and returns the expected readiness response;
- `/optimize-energy` accepts the exact canonical request;
- all 10 public cases pass end-to-end;
- all public reference costs are reproduced within tolerance;
- every returned plan passes the independent final replay;
- malformed input cannot crash the process;
- malformed LLM output cannot reach the optimizer;
- no hard-coded phrase matcher can replace the LLM;
- normal p95 latency meets the official best-score band in deployment testing;
- Docker image starts from documented commands and becomes healthy;
- clean-environment README reproduction succeeds;
- no secrets are present in repository/image/log samples;
- demo features remain isolated from the judge response schema.

---

## 19. Key Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| LLM returns plausible but wrong directive | high | strict taxonomy prompt, structured output, paraphrase tests, optional repair/fallback |
| LLM output is syntactically valid but semantically impossible | high | compile + feasibility check; bounded reinterpretation retry |
| Hidden paraphrase differs from public cases | high | taxonomy-based prompting, synthetic paraphrase test suite, no phrase hard-coding |
| Percentage reserve converted incorrectly | high | include battery capacity in LLM context; deterministic range check |
| Time window off-by-one | high | explicit start-inclusive/end-exclusive instruction and tests |
| Correct directive not reflected in plan | critical | directive compiler + independent final replay |
| Floating-point mismatch | medium | stricter internal tolerance, canonical totals recalculation |
| Provider outage/rate limit | high | timeout, retry budget, backup provider, exact-request cache |
| Extra demo fields break judge schema | critical | separate demo endpoints/UI; strict response model |
| Secrets leak in logs/image | high | env vars, log redaction, CI secret scan, no raw provider payloads |
| Solver returns non-optimal status | high | status assertion, fallback solver or controlled failure |
| Same-type overlapping ambiguous directives | medium | detect conflict; do not invent semantics; valid judge cases are stated feasible |

---

## 20. Assumptions Derived from the Canonical Documents

1. Battery charging/discharging uses the exact organizer state equations; no efficiency factor is added.
2. Grid export is not allowed.
3. Unused solar may be curtailed.
4. The final battery energy must equal the initial energy.
5. Hidden notes map to exactly one published directive type or `no_op`.
6. Valid organizer scoring scenarios are feasible and do not require contradictory hard directives.
7. Equivalent optimal schedules are acceptable; exact action sequence need not match one public reference.
8. Free-text `explanation` does not need byte-for-byte matching.
9. The public sample pack is a regression suite, not a template to hard-code.
10. Development scope may be broad, but official runtime, reachability, and reproducibility limits still apply.

---

## 21. Recommended Technology Stack

**Core service**

- Python 3.11+ or 3.12+
- FastAPI
- Pydantic v2
- `numpy`
- `scipy.optimize.linprog(method="highs")` for LP relaxation
- `scipy.optimize.milp(...)` / HiGHS for final MILP
- official LLM SDK or provider adapter
- `httpx`
- structured logging

**Reliability/testing**

- `pytest`
- `pytest-asyncio`
- optional `hypothesis`
- `tenacity` or a small custom bounded retry layer
- in-memory LRU/TTL cache; optional Redis only if operationally justified

**Observability**

- Prometheus-style counters/histograms
- optional OpenTelemetry traces
- JSON logs with correlation ID

**Demo**

- lightweight React/Vite or a simple server-rendered dashboard
- Plotly/ECharts/Chart.js for time-series plots
- keep demo assets independent of the judge response

**Deployment**

- Docker
- a public HTTPS hosting platform
- pullable Docker Hub/GHCR image with exact tag/digest

---

## 22. Web Research Findings Used in This PRD

The following research reinforced, but did not replace, organizer requirements:

1. **Structured LLM output:** OpenAI Structured Outputs supports JSON-Schema-constrained responses; schema adherence reduces formatting failure, but semantic validation is still needed.  
   https://developers.openai.com/api/docs/guides/structured-outputs

2. **LLM + external solver architecture:** OptLLM describes translating natural language optimization requirements and using external solvers rather than expecting an LLM to numerically optimize everything.  
   https://aclanthology.org/2024.naacl-industry.42/

3. **LLMs remain weak at constrained numerical optimization:** recent work shows that LLMs can fail on complex constrained power/optimization tasks, supporting the separation of language interpretation from the mathematical solver.  
   https://arxiv.org/abs/2603.23004

4. **Energy-management guardrail architecture:** recent building-energy work reports a planner/supervisor/executor structure with deterministic supervision around LLM-generated intent/workflows.  
   https://pubmed.ncbi.nlm.nih.gov/41812359/

5. **Battery + PV tariff scheduling as optimization:** published work formulates 24-hour solar/battery scheduling under time-of-use tariffs as linear programming, supporting the continuous relaxation/baseline portion of the hybrid design.  
   https://arxiv.org/abs/1810.11178

6. **Practical battery scheduling:** Gurobi publishes a battery scheduling example involving tariff, PV generation, and battery technical constraints.  
   https://www.gurobi.com/resources/demos/battery-scheduling

7. **LP + MILP solver:** SciPy exposes HiGHS-backed `linprog` for the LP relaxation and `milp` for mixed-integer linear optimization, allowing both stages to share the same linear constraint model.  
   https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.linprog.html  
   https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html

8. **API validation:** FastAPI supports nested Pydantic request models, validation, JSON Schema, and automatic API documentation.  
   https://fastapi.tiangolo.com/tutorial/body-nested-models/

9. **Container deployment:** FastAPI documents Docker deployment; Docker supports `HEALTHCHECK` for container readiness.  
   https://fastapi.tiangolo.com/deployment/docker/  
   https://docs.docker.com/reference/dockerfile

10. **Prompt-injection defense:** OWASP recommends treating external natural-language input as untrusted, clearly separating instructions from data, validating output, and using least privilege.  
    https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html

11. **Latency/reliability observability:** Prometheus recommends tracking query/request count, errors, and latency for online services and supports histograms for latency distributions.  
    https://prometheus.io/docs/practices/instrumentation/

---

## 23. Final Product Definition

The finished GridWise product is not simply an “LLM app” and not simply an “optimizer.”

It is a **neurosymbolic energy scheduling pipeline with an LP-Assisted MILP optimization core**:

```text
natural language
    -> typed directive
    -> deterministic verification
    -> mathematical constraints
    -> exact optimizer
    -> independent physical replay
    -> machine-checkable API result
```

The strongest hackathon version should make every boundary visible in the demo while keeping the judge path exact, fast, deterministic after interpretation, and fully reproducible.
