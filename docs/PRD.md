# GridWise — LLM-Assisted Smart Campus Energy Optimizer
## Product Requirements Document (PRD)

**Version:** 1.2  
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
- trust LLM arithmetic or LLM-generated schedules instead of the LP+MILP optimizer;
- return demo-only fields inside the canonical `/optimize-energy` response;
- expose API keys, raw secrets, stack traces, or sensitive configuration;
- introduce RAG, a vector database, autonomous agents, or tool-using LLM behavior into the judge path when they do not satisfy a canonical requirement;
- silently treat engineering assumptions for unspecified language/composition cases as organizer-defined rules.

The source documents do not specify battery efficiency losses, degradation cost, forecast uncertainty, grid export, or stochastic optimization. Those concepts can appear in a **demo-only research sandbox**, but they must not change the official judge path.

The selected optimization architecture remains **LP-Assisted MILP**. Deep-research recommendations are applied around interpretation, feasibility screening, numerical safety, testing, retries, deployment, and observability without replacing that optimization choice.

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
Strict Request Validation + Canonical Hour Ordering
    |
    v
Baseline Feasibility LP (no operator directives)
    |
    +---- infeasible ---> controlled semantic-invalid request
    |
    v
LLM Directive Interpreter (one structured call for all notes)
    |
    v
Structured Directive Schema
    |
    v
Deterministic Semantic Guardrails
    |
    v
Directive Compiler
    |
    v
LP Relaxation of Directive-Constrained Model
    |
    +---- infeasible ---> one focused semantic reinterpretation
    |
    v
Final MILP Optimization
    |
    v
Numerical Canonicalizer / Exact Response Builder
    |
    v
Independent Replay of Serialized Response Values
    |
    +---- invalid ---> controlled internal failure
    |
    v
HTTP JSON Response
```

The LP+MILP architecture remains unchanged: the LP stage is the relaxation/feasibility/lower-bound stage and the MILP stage is the authoritative final optimizer. The added baseline LP, canonicalization, and serialized-response replay are reliability layers around that design.

The demo layer consumes sanitized copies of the validated internal trace and never sits between the judge and the canonical response.

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

Validate before any paid LLM call.

**Canonical/contract checks**:

- `scenario_id` is a string;
- `operator_notes` contains 1–3 non-empty strings;
- `hours` contains exactly 24 entries;
- hour IDs are unique and represent exactly `0..23`;
- all required hour/battery fields are present with correct JSON types;
- required numeric values are finite;
- malformed JSON / structural schema errors produce a controlled 400.

After validation, internally sort/canonicalize the hourly records by their `hour` field; do not assume array position equals hour number.

**Engineering semantic checks** may reject impossible battery relationships such as initial energy or minimum reserve above capacity, while preserving source ambiguity where the canonical files do not specify a rule. In particular, tariff must be finite, but the product must not invent a non-negative tariff requirement unless organizers clarify it.

Run a baseline feasibility LP relaxation without operator directives before the LLM. A well-formed scenario that is already infeasible under base GridWise constraints should return a controlled semantic error (recommended 422).

Do not silently fill missing inputs.

### FR-04 — Mandatory LLM interpretation

The LLM must be part of the path producing the structured directives that are used by the optimizer.

The normal call receives:

- the fixed directive taxonomy;
- exact structured-output schema;
- canonical time-window convention;
- explicit solar-percentage contrast rules;
- battery context needed for capacity/base-reserve references;
- operator notes clearly delimited as untrusted data.

By default, **do not send the entire 24-hour demand/solar/tariff matrix**. The LLM's task is narrow semantic parsing; extra unrelated numbers increase tokens, latency, and numeric-copying risk. Add other scenario facts only if a note genuinely depends on them and the canonical rules permit that interpretation.

All 1–3 notes should be interpreted in one structured-output call while preserving `note_index` mapping. The LLM must not receive tools or scheduling responsibility.

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

Required and testable language behaviors include:

**Canonical/high-confidence rules**:

- `1 PM to 3 PM` -> `[13,14]`;
- start included, end excluded;
- noon -> hour `12`;
- midnight -> hour `0`;
- 24-hour expressions such as `13:00 to 15:00` -> `[13,14]`;
- `between 2 and 4 PM` -> `[14,15]`;
- `6 until 9 PM` -> `[18,19,20]`;
- a shared suffix such as `one to three PM` applies PM consistently;
- percentage battery reserve -> kWh using battery capacity;
- equivalent paraphrases normalize to the same directive.

**Solar factor contrasts** must be tested explicitly because `factor` means the usable fraction remaining:

- reduced **to** 20% -> `0.20`;
- reduced **by** 20% -> `0.80`;
- 20% reduction -> `0.80`;
- 80% reduction -> `0.20`;
- operating at 80% -> `0.80`;
- one-fifth remains -> `0.20`;
- halved -> `0.50`;
- unavailable -> `0.00`;
- 12.5% remaining -> `0.125`.

**Documented specification gaps / provisional engineering policies**:

- clearly cross-midnight range `11 PM to 2 AM` -> provisional modulo-24 set `{23,0,1}`, serialized `[0,1,23]`;
- `through` wording -> provisional end-exclusive treatment until organizer clarification;
- a single-hour phrase such as `during the 4 PM hour` -> provisional `[16]`.

These provisional behaviors must be isolated/configurable and must be updated if organizers clarify them. They must not be described as canonical organizer rules.

### FR-07 — Deterministic guardrail validator

The validator must reject or trigger bounded repair when any of these fail:

- unsupported directive type;
- missing/duplicate/out-of-range `note_index`;
- illegal `applies` semantics;
- wrong adjustment shape for the directive type;
- duplicate/out-of-range hours;
- hours not ascending after the chosen strictness policy;
- `solar_reduction.factor` outside `[0,1]` or non-finite;
- reserve negative, non-finite, or above battery capacity;
- `max_grid_kwh` negative or non-finite;
- non-null adjustment for `no_op`;
- extra unsupported fields when strict schema is used.

Safe normalization is deliberately limited:

- sort otherwise-valid entries by `note_index` if every mapping is unique;
- optionally sort an otherwise-valid **unique** hour set;
- normalize tiny `-0.0` artifacts;
- trim explanation whitespace.

Do **not** silently deduplicate repeated hours, clip invalid numeric values into range, or convert unknown directive types. `factor=0.0` and `max_grid_kwh=0.0` are valid values and must not be lost to truthiness checks.

Semantic values must not be invented by deterministic code.

### FR-08 — Bounded interpretation repair

Normal path: one LLM call.

Retries are failure-specific and bounded by the remaining request budget:

- provider connection reset/5xx -> at most one short-backoff retry;
- provider 429 -> honor provider hint only if the deadline permits, otherwise tested backup or controlled failure;
- refusal/truncation -> one bounded retry/fallback;
- structured-schema failure -> one repair call with concise structural errors;
- semantic guardrail failure -> one focused semantic retry using the original note;
- directive LP infeasible after a feasible baseline -> one focused semantic reinterpretation;
- MILP solver internal/non-optimal failure -> do not blindly ask the LLM to change semantics;
- final replay failure -> no blind retry; treat as an internal invariant failure.

A regex/keyword interpreter must never become the hidden semantic fallback.

### FR-09 — Directive compiler

Compile validated directives into per-hour deterministic parameters:

- `effective_solar[h]`;
- `active_minimum_energy[h]`;
- charge permission;
- discharge permission;
- `grid_upper_bound[h]`;
- internal provenance/ambiguity flags for debugging only.

Composition rules:

- reserve constraints combine with pointwise `max`;
- grid caps combine with pointwise `min`;
- no-charge/no-discharge windows combine as hard booleans;
- no-charge + no-discharge on the same hour forces battery idle.

**Overlapping solar-reduction factors are a specification gap.** Until organizer clarification, use a documented provisional policy: if two different factors overlap the same hour, use the most restrictive remaining fraction `min(factors)` and record an internal ambiguity flag. This protects validity by never assuming more solar than either directive allows, but it is not an organizer-defined composition rule and must remain isolated/configurable.

The organizer states valid scoring scenarios are feasible and will not require contradictory hard directives.

### FR-10 — Optimization engine

The selected optimizer remains **LP-Assisted MILP**.

The primary objective is:

```text
minimize sum(grid_kwh[h] * tariff_bdt_per_kwh[h]) for h=0..23
```

subject to the canonical energy, solar, battery, directive, and final-neutrality constraints.

Required execution behavior:

1. run a baseline LP relaxation without operator directives to detect an impossible request before the LLM;
2. after directive compilation, solve the directive-constrained LP relaxation for feasibility and a lower bound;
3. if that LP is infeasible despite a feasible baseline, permit one focused semantic reinterpretation;
4. solve the final MILP with binary charge/discharge modes as the authoritative schedule;
5. require `LP_objective <= MILP_objective + tolerance`;
6. require optimal/non-error solver status and finite objective;
7. never return the LP relaxation as the final schedule when the MILP stage is required by this product design.

Do not add battery degradation, efficiency loss, export revenue, stochastic penalties, or other objective terms to the judge path unless organizers define them.

### FR-11 — Independent final replay

After solving, canonicalize the MILP result, serialize it with sufficient precision, parse it back through the exact response model, and replay **those exact response values**.

The replay checks:

- 24 unique hours in canonical `0..23` order;
- finite/non-negative response values where required;
- action/magnitude consistency;
- no simultaneous charge/discharge semantics;
- energy balance every hour;
- battery transition every hour;
- battery minimum/capacity;
- charge/discharge rate limits;
- no-charge/no-discharge windows;
- reserve constraints;
- effective solar;
- grid caps;
- final battery neutrality;
- `total_grid_kwh`;
- `total_cost_bdt`;
- `peak_grid_kwh`.

Do not independently round all energy fields to two decimals. Use high-enough response precision, reconstruct dependent state/balance values consistently, and calculate totals only from the final plan being returned.

A plan that fails replay must never be returned as HTTP 200, and replay failure must not trigger a blind semantic retry.

### FR-12 — Plan summary

Return a short human-readable `plan_summary`.

Recommended judge-path behavior: generate it deterministically from the validated directives and plan so a second LLM call cannot hurt latency/reliability.

A richer LLM-generated explanation may be shown in demo mode outside the canonical response.

---

### FR-13 — Controlled error behavior

- malformed JSON / structurally invalid request: controlled 400;
- semantically invalid but well-formed request: controlled 422 where used;
- baseline-infeasible request: controlled 422;
- oversized request/note: controlled 413 or documented 400 policy;
- provider/solver/internal failure: controlled 500 without raw stack trace, prompts, or secrets;
- final replay invariant failure: controlled 500.

FastAPI's default validation behavior must be overridden where necessary so structural request errors do not accidentally become the wrong status class.

Internally log a correlation ID and sanitized failure class.

### FR-14 — Reproducibility

Repository/deployment documentation must include:

- environment-variable names;
- exact install/run command;
- exact model/provider identifier or snapshot used;
- prompt version and directive-schema version;
- LLM role and minimal-context policy;
- guardrail description;
- LP+MILP optimizer/solver choice and versions;
- `/health` example;
- `/optimize-energy` example;
- public sample test command;
- adversarial semantic test command;
- Docker pull/run with immutable tag or digest;
- dependency credits and pinned/locked versions;
- known specification ambiguities/provisional policies;
- known limitations;
- no secret values.

The release should record the tested application commit SHA and optimizer version.

## 11. Non-Functional Requirements

### NFR-01 — Latency

Official limits:

- `/optimize-energy` must finish within 30 seconds;
- p95 <= 5 seconds receives full latency credit.

Internal targets:

```text
soft end-to-end target: 4.5 s
warning threshold:      p95 > 4.0 s
urgent threshold:       p95 > 4.5 s
internal hard deadline: ~28 s
```

Normal-stage targets:

- request validation + canonicalization: <20 ms;
- baseline feasibility LP: <50–100 ms;
- one LLM structured extraction call: target p95 <=2.5–3.0 s;
- guardrail/compiler: <10 ms;
- LP relaxation + tiny MILP: expected to be much smaller than the LLM call;
- canonicalization/replay: <20 ms;
- fallback attempts occur only when remaining deadline permits.

### NFR-02 — Availability

The submitted endpoint must remain reachable during evaluation. `/health` is local/readiness-only and must not synchronously call the LLM provider.

### NFR-03 — Determinism

For the same validated interpretation and numeric input, optimization/replay output should be deterministic within floating-point tolerance. Exact optimal action sequences may differ when multiple solutions are equivalent.

### NFR-04 — Security and resource protection

- secrets only through environment/configuration/secret manager;
- no secrets in image/repository/logs/responses;
- operator notes treated as untrusted data;
- LLM has no tool, shell, database, web, or file permissions;
- raw prompt/provider payload logging disabled by default;
- sanitize provider exceptions;
- enforce a generous request-body limit and note-length limit;
- enforce request/LLM concurrency caps sized above expected judge traffic;
- monitor provider RPM/quota/spend;
- use sensible rate limits/circuit breaking only after load testing so protection cannot block the judge.

### NFR-05 — Numeric tolerance

Internal validation should be stricter than the organizer's published `0.01 kWh / 0.01 BDT` tolerance where practical. Do not round internal optimization/state values to two decimals. Replay the exact serialized/parsed response before returning it.

### NFR-06 — Observability and version traceability

Track at least:

- request/success/failure counts;
- active-request gauge;
- end-to-end latency histogram;
- LLM latency/provider/exact model version;
- guardrail failure and semantic-retry counts;
- provider 429/5xx/refusal/truncation counts;
- baseline LP status;
- LP relaxation status/objective/latency;
- MILP status/objective/gap/latency;
- LP<=MILP invariant failures;
- final-replay failure count;
- cache-hit count;
- prompt/schema/optimizer versions and application commit SHA in internal traces.

Any final replay failure or unexpected non-optimal solver status on a valid request is an urgent event.

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

### 15.1 Provider abstraction and exact model pinning

Use a common interpreter interface so a pretested backup provider/model can be configured without changing optimizer logic. Pin the exact model/snapshot where supported and record the actual provider-reported model version in telemetry.

### 15.2 Failure-specific deadline-aware retries

Retries are not a generic loop. Apply the FR-08 policy by failure class and only while the remaining request budget permits. Maximum normal interpretation attempts should remain bounded (recommended two total attempts on one path).

### 15.3 Safe parser/full-response caching

Never key parser cache only by note text. Parser cache keys must include:

- ordered operator notes;
- relevant battery context;
- provider;
- exact model version;
- prompt version;
- schema version.

Full-response cache keys additionally include the entire canonical request, optimizer version, and application code version/commit.

Cache only guardrail-valid interpretations and replay-valid full responses. Never cache refusals, malformed output, solver failures, or replay failures.

### 15.4 Circuit breaker / concurrency protection

A circuit breaker may route to a pretested backup when a provider is consistently failing, but must not make `/health` depend on the provider. Protect quota with bounded request and LLM concurrency. Rate limits must include enough burst headroom for judge traffic.

### 15.5 LP/MILP solver failure handling

The LP relaxation and final MILP remain the required optimization stages. If the directive LP is infeasible after a feasible baseline, one semantic reinterpretation is allowed. If the LP is feasible but the final MILP reports an unexpected non-optimal/internal status, do not weaken directives or return the LP as the final schedule; optionally use a pretested MIP backend, otherwise controlled 500.

### 15.6 Structured-output schema warming

Before judging, run a canary against the exact production model, prompt version, and schema version so first-use schema compilation/cold behavior does not hit the first judged request. Confirm quota, credentials, parseability, guardrail validity, and latency. This warm canary is separate from `/health`.

### 15.7 Release/version freeze

Before submission record and freeze:

- model/provider exact ID;
- prompt version;
- schema version;
- optimizer version;
- SciPy/solver versions;
- application commit SHA;
- Docker image digest.

No last-minute model alias, prompt, solver, or dependency switch should bypass the full regression suite.

## 16. Security Requirements

Operator notes are untrusted natural-language input.

Prompt design must clearly separate:

- system/developer rules;
- minimal required scenario context;
- operator-note data.

The LLM should have **no tools**. It only emits a typed directive object.

Defenses:

- strict structured output;
- deterministic output validation;
- prompt-injection and schema-injection fixtures;
- no raw secret values in prompts;
- no prompt/provider exception leakage;
- environment/secret-manager keys;
- `.env` ignored by Git;
- non-root container where practical;
- pinned dependencies / lock file;
- request body + note length limits;
- request/LLM concurrency limits;
- provider quota/spend monitoring;
- sanitized structured logging with no raw adversarial note text at INFO;
- no API keys in Dockerfile, build args, image layers, README, or CI logs.

Prompt-injection screening may be a demo telemetry signal, but must not rewrite or discard legitimate notes based only on keywords.

## 17. Testing Requirements

### 17.1 Public sample regression

All 10 public cases must pass:

- exact directive semantics;
- one entry per note;
- LP relaxation feasible;
- final MILP optimal/successful;
- `LP objective <= MILP objective + tolerance`;
- serialized final plan validity;
- total reconciliation;
- optimal cost within tolerance.

### 17.2 Large semantic/adversarial gold corpus

Build hundreds of immutable fixtures across:

- 12h/24h time;
- noon/midnight/shared AM-PM suffix;
- `until` / `between` / number words;
- Unicode dash and spacing variants;
- fractions and decimal percentages;
- `reduced to` vs `reduced by` vs `% reduction` vs `operates at`;
- exactly-zero solar factor and grid cap;
- capacity-relative reserve;
- irrelevant notes containing time/energy words;
- multi-note reordering;
- prompt injection and schema-looking note text;
- provisional cross-midnight and `through` policies tracked separately.

Generated paraphrases require curated/verified labels; do not trust the generator's own label automatically.

### 17.3 Guardrail tests

Inject malformed or semantically invalid model outputs:

- unknown type;
- missing/duplicate `note_index`;
- duplicate hours;
- unsorted hours;
- factor >1 / negative / NaN / Infinity;
- reserve above capacity;
- negative grid cap;
- wrong `applies`;
- non-null adjustment for `no_op`;
- missing/extra fields;
- provider refusal/truncation.

### 17.4 LP+MILP property and metamorphic tests

Random feasible scenarios must satisfy:

- energy balance;
- battery transitions/bounds/rate limits;
- directive bounds;
- final neutrality;
- no simultaneous charge/discharge in final MILP;
- LP lower bound <= MILP objective;
- serialized response passes replay;
- objective no worse than any tested feasible heuristic baseline.

Metamorphic properties:

- increasing available solar cannot increase optimal cost;
- tightening a feasible reserve cannot decrease optimal cost;
- tightening a feasible grid cap cannot decrease optimal cost;
- removing a hard constraint cannot worsen the optimal objective.

### 17.5 API/reliability tests

- malformed JSON / missing fields / duplicate or missing hour IDs;
- empty and oversized notes;
- repeated identical request;
- cache key separation across battery/model/prompt versions;
- provider timeout / 429 / 5xx / refusal / malformed output;
- baseline infeasibility;
- LP infeasibility after directives;
- MILP failure/non-optimal status;
- replay failure injection;
- concurrent requests and LLM semaphore behavior;
- 400 vs 422 mapping;
- external p50/p95/p99 benchmark.

### 17.6 Container/deployment/security tests

- clean Docker build;
- solver LP+MILP capability inside final image;
- `/health` does not call provider;
- full `/optimize-energy` request in container;
- secret/image-layer scan;
- external endpoint smoke test;
- warm-schema/model canary;
- immutable image/version metadata present.

## 18. Acceptance Criteria

The product is release-ready when:

- `/health` is externally reachable and returns the expected readiness response without an LLM call;
- `/optimize-energy` accepts the exact canonical request and returns only the canonical response;
- structural 400 vs semantic 422 behavior is intentionally tested;
- all 10 public cases pass interpretation, LP relaxation, final MILP, and serialized replay;
- all public reference costs are reproduced within tolerance;
- the LP lower bound never exceeds the final MILP objective beyond tolerance;
- every returned plan passes independent replay after serialization;
- the percentage/time/adversarial semantic corpus passes the chosen release threshold;
- malformed/provider/model failures cannot reach the optimizer unchecked or crash the process;
- no hard-coded phrase matcher can replace the LLM;
- p95 is comfortably inside the <=5 s full-score band, with internal target <=4.5 s;
- body/concurrency/rate protections have been load-tested not to block judge-shaped traffic;
- production model/schema is prewarmed;
- cache keys include relevant context and exact versions;
- Docker image starts from documented commands and exposes working LP+MILP solver support;
- clean-environment README reproduction succeeds;
- no secrets are present in repository/image/log samples;
- exact model/prompt/schema/optimizer/commit/image versions are recorded and frozen;
- specification-gap policies are documented as provisional rather than canonical;
- demo features remain isolated from the judge response schema.

## 19. Key Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Wrong directive type / relevant note marked `no_op` | critical | strict taxonomy, tagged schema, adversarial relevance corpus, focused semantic retry |
| Wrong hours / off-by-one | critical | explicit start-inclusive/end-exclusive examples, noon/midnight/shared-suffix fixtures |
| `reduced by` vs `reduced to` semantic error | critical | contrastive prompt examples and exact gold tests |
| Capacity-relative reserve wrong | high | supply battery context, range check, gold fixtures |
| Prompt/schema injection | critical | note-is-data prompt, no tools, strict schema, adversarial fixtures |
| Schema-valid but semantically wrong output | critical | deterministic semantic guardrails + gold tests + feasibility signal |
| Cross-midnight / `through` mismatch | high | documented provisional policy, isolated tests, replace immediately if organizer clarifies |
| Differing overlapping solar factors | high | explicit overlap detector, provisional min-factor policy + ambiguity flag |
| Baseline scenario impossible | high | pre-LLM baseline LP -> controlled 422 |
| Directive LP infeasible due wrong semantics | critical | one focused semantic reinterpretation; never weaken constraints |
| LP/MILP invariant violation | critical | assert LP <= MILP + tolerance, solver status checks, property tests |
| Rounding breaks balance/state | critical | canonicalize, reconstruct dependent values, 6–8 digit serialization, replay parsed response |
| Provider timeout/429/5xx/refusal | high | deadline-aware failure-specific retry, tested backup, quota monitoring |
| Model alias drift | high | pin exact model/snapshot where possible; versioned cache and semantic CI |
| Structured-schema cold compile | medium | warm exact production schema/model before judging |
| Cache returns context-wrong directive | critical | include battery context and prompt/schema/model versions in parser key |
| Cache poisoning/staleness | high | cache only guardrail/replay-valid data, invalidate by versions |
| Public endpoint denial-of-wallet | high | body/note limits, concurrency caps, generous rate limits, spend/RPM alerts |
| Protection blocks judge | critical | load test generous burst limits; avoid over-tight configuration |
| Solver non-optimal/internal status | high | assert status, optional pretested MIP backend, controlled failure |
| Final replay fails | critical | no blind retry; never return 200 |
| FastAPI 422/400 mismatch | high | custom exception mapping + contract tests |
| Cold start / inaccessible endpoint | critical | warm instance where useful, external probes, deployment smoke tests |
| Secret leak | critical | env/secret manager, redaction, secret/image scans |
| Last-minute untested model/prompt/solver change | critical | immutable release/version freeze and rollback path |
| Hidden-test overfitting to public phrases | critical | large metamorphic/adversarial corpus; no phrase hard-coding |

## 20. Assumptions, Canonical Facts, and Specification Gaps

### 20.1 Canonical facts used by the product

1. Battery charging/discharging uses the exact organizer state equations; no efficiency factor is added.
2. Grid export is not allowed.
3. Unused solar may be curtailed.
4. The final battery energy must equal the initial energy.
5. Hidden notes map to exactly one published directive type or `no_op`.
6. Valid organizer scoring scenarios are feasible and do not require contradictory hard directives.
7. Equivalent optimal schedules are acceptable; exact action sequence need not match one public reference.
8. Free-text `explanation` does not need byte-for-byte matching.
9. The public sample pack is a regression seed, not a template to hard-code.
10. Official runtime, reachability, Docker, and reproducibility limits still apply regardless of development scope.

### 20.2 Explicit engineering assumptions / unresolved specification gaps

These are **not** claimed as organizer-defined rules:

- cross-midnight windows: provisional modulo-24 expansion, then ascending hour serialization;
- `through` wording: provisional end-exclusive treatment;
- single-hour phrase such as `during the 4 PM hour`: provisional one-hour interval mapping;
- overlapping differing solar-reduction factors: provisional most-restrictive `min(factor)` composition plus an internal ambiguity flag;
- request body/note/concurrency limits: engineering protections chosen generously and load-tested;
- negative-tariff rejection is **not** assumed because the canonical request schema does not explicitly require non-negative tariff.

All gap-handling policies must be isolated so organizer clarification can replace them without touching the rest of the pipeline.

## 21. Recommended Technology Stack

**Core service**

- Python 3.11+ or 3.12+
- FastAPI
- Pydantic v2
- `numpy`
- `scipy.optimize.linprog(method="highs")` for baseline/directive LP relaxation
- `scipy.optimize.milp(...)` / HiGHS for final MILP
- official LLM SDK or provider adapter
- `httpx`
- structured logging

The project intentionally retains SciPy/HiGHS because one stack supports both selected stages. Deep research favoring a pure-LP solver does not override the chosen LP+MILP architecture.

**Reliability/testing**

- `pytest`
- `pytest-asyncio`
- `hypothesis` where useful for property/metamorphic testing
- `tenacity` or a small custom failure-specific retry layer
- bounded in-memory LRU/TTL cache; Redis only if operationally justified
- secret scanner and dependency lock/pins

**Observability**

- Prometheus-style counters/histograms
- optional OpenTelemetry traces
- JSON logs with correlation ID and version metadata

**Demo**

- lightweight React/Vite or server-rendered dashboard
- Plotly/ECharts/Chart.js
- keep demo assets independent of the judge response

**Deployment**

- Docker with immutable commit-based image tag/digest
- public HTTPS hosting platform
- secret-manager/runtime environment configuration
- pre-judging schema/model warm canary
- external endpoint smoke tests and p95 benchmark

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
