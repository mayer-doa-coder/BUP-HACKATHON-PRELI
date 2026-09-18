"""End-to-end public regression through the real HTTP endpoint.

P7 proved the deterministic half by feeding ground-truth directives straight to the optimizer.
This runs every public case through the **whole service over HTTP** — routing, request schema,
interpreter seam, guardrails, compiler, solvers, canonicalizer, replay and serialization — and
grades each case the way the judge does: interpretation semantics, plan validity, recalculated
cost, and latency.

The model is a deterministic stub, because the point here is the *pipeline*, and a live model
would make the suite non-deterministic, slow and billable. Semantic accuracy of the real model
is P12's job, behind the ``live`` marker. The stub is deliberately strict: it asserts the prompt
it receives is the production one, so this cannot pass with the interpreter bypassed.
"""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from app.api.routes import get_optimize_service
from app.llm.base import ProviderResponse
from app.llm.interpreter import LlmDirectiveInterpreter
from app.main import create_app
from app.schemas.request import OptimizeRequest
from app.schemas.response import OptimizeResponse
from app.services.optimize_service import OptimizeService
from app.validation.interpretation_match import compare_interpretations
from app.validation.replay import replay

JUDGE_TOLERANCE = 0.01
CANONICAL_RESPONSE_FIELDS = {
    "scenario_id",
    "directive_interpretation",
    "hourly_plan",
    "total_grid_kwh",
    "total_cost_bdt",
    "peak_grid_kwh",
    "plan_summary",
}


class ReferenceProvider:
    """Answers with the case's reference interpretation, after checking the prompt is real."""

    name = "reference-stub"
    model = "reference-stub-1"

    def __init__(self, interpretation_by_scenario: dict[str, list]):
        self.by_scenario = interpretation_by_scenario
        self.calls = 0

    async def complete(self, *, system_prompt, user_payload, json_schema, timeout_s):
        self.calls += 1
        # If the service ever stopped using the production prompt or schema, these would fail
        # and this suite would stop being an end-to-end test without anyone noticing.
        assert "UNTRUSTED DATA" in system_prompt
        assert "reduced BY 20%       -> 0.80" in system_prompt
        assert "battery_context" in user_payload
        assert "tariff" not in user_payload
        assert json_schema["properties"]["directive_interpretation"]["items"]["anyOf"]

        payload = json.loads(user_payload[user_payload.index("{") : user_payload.rindex("}") + 1])
        scenario_notes = tuple(note["text"] for note in payload["operator_notes"])
        return ProviderResponse(
            content=json.dumps({"directive_interpretation": self.by_scenario[scenario_notes]}),
            model_version=self.model,
        )

    async def aclose(self):
        return None


@pytest.fixture
def endpoint(public_cases, extended_cases):
    """A TestClient wired to the real app with a reference-answering model."""
    by_notes = {
        tuple(case["input"]["operator_notes"]): case["expected_output"]["directive_interpretation"]
        for case in [*public_cases, *extended_cases]
    }
    provider = ReferenceProvider(by_notes)
    service = OptimizeService(interpreter=LlmDirectiveInterpreter(provider))

    app = create_app()
    app.dependency_overrides[get_optimize_service] = lambda: service
    client = TestClient(app, raise_server_exceptions=False)
    client.provider = provider  # type: ignore[attr-defined]
    return client


# ---------------------------------------------------------------- the full grading run


def test_every_public_case_passes_end_to_end(endpoint, public_cases):
    """Interpretation, validity, and cost — the three things the judge scores per case."""
    failures: list[str] = []
    latencies: list[float] = []

    for case in public_cases:
        started = time.perf_counter()
        response = endpoint.post("/optimize-energy", json=case["input"])
        latencies.append((time.perf_counter() - started) * 1000.0)

        if response.status_code != 200:
            failures.append(f"{case['id']}: HTTP {response.status_code} {response.text[:200]}")
            continue

        body = response.json()
        request = OptimizeRequest.model_validate(case["input"])
        parsed = OptimizeResponse.model_validate(body)

        comparison = compare_interpretations(
            parsed.directive_interpretation, case["expected_output"]["directive_interpretation"]
        )
        if not comparison.matches:
            failures.append(f"{case['id']}: interpretation {comparison.problems}")

        report = replay(request, parsed.directive_interpretation, parsed)
        if not report.ok:
            failures.append(f"{case['id']}: replay {report.messages}")

        reference_cost = case["expected_output"]["total_cost_bdt"]
        if abs(parsed.total_cost_bdt - reference_cost) > JUDGE_TOLERANCE:
            failures.append(f"{case['id']}: cost {parsed.total_cost_bdt} vs {reference_cost}")

    assert not failures, "\n".join(failures)
    assert len(latencies) == 10
    # The deterministic pipeline must leave the whole latency budget to the model.
    assert max(latencies) < 1000.0, f"pipeline latency {max(latencies):.0f}ms excluding the model"


def test_every_extended_case_passes_end_to_end(endpoint, extended_cases):
    failures: list[str] = []
    for case in extended_cases:
        response = endpoint.post("/optimize-energy", json=case["input"])
        if response.status_code != 200:
            failures.append(f"{case['id']}: HTTP {response.status_code} {response.text[:200]}")
            continue

        parsed = OptimizeResponse.model_validate(response.json())
        request = OptimizeRequest.model_validate(case["input"])

        comparison = compare_interpretations(
            parsed.directive_interpretation, case["expected_output"]["directive_interpretation"]
        )
        report = replay(request, parsed.directive_interpretation, parsed)
        reference_cost = case["expected_output"]["total_cost_bdt"]

        if not comparison.matches:
            failures.append(f"{case['id']}: interpretation {comparison.problems}")
        if not report.ok:
            failures.append(f"{case['id']}: replay {report.messages}")
        if abs(parsed.total_cost_bdt - reference_cost) > JUDGE_TOLERANCE:
            failures.append(f"{case['id']}: cost {parsed.total_cost_bdt} vs {reference_cost}")

    assert not failures, "\n".join(failures)


def test_optimization_quality_is_full_marks_on_every_known_case(endpoint, public_cases, extended_cases):
    """Rubric: ``min(1, organizer_optimal / team_cost)``, averaged, times 10 points."""
    ratios = []
    for case in [*public_cases, *extended_cases]:
        response = endpoint.post("/optimize-energy", json=case["input"])
        assert response.status_code == 200, case["id"]

        team_cost = response.json()["total_cost_bdt"]
        optimal = case["expected_output"]["total_cost_bdt"]
        ratios.append(1.0 if abs(team_cost) < 1e-9 else min(1.0, optimal / team_cost))

    assert min(ratios) == pytest.approx(1.0, abs=1e-6)
    assert sum(ratios) / len(ratios) == pytest.approx(1.0, abs=1e-6)


# ------------------------------------------------------------------- contract details


def test_responses_carry_exactly_the_canonical_fields(endpoint, public_cases):
    for case in public_cases:
        body = endpoint.post("/optimize-energy", json=case["input"]).json()

        assert set(body) == CANONICAL_RESPONSE_FIELDS, case["id"]
        assert body["scenario_id"] == case["input"]["scenario_id"]
        assert len(body["hourly_plan"]) == 24
        assert [entry["hour"] for entry in body["hourly_plan"]] == list(range(24))
        assert len(body["directive_interpretation"]) == len(case["input"]["operator_notes"])
        assert [item["note_index"] for item in body["directive_interpretation"]] == list(
            range(len(case["input"]["operator_notes"]))
        )


def test_no_op_entries_keep_their_explicit_null(endpoint, public_cases):
    case = next(
        c
        for c in public_cases
        if any(d["directive_type"] == "no_op" for d in c["expected_output"]["directive_interpretation"])
    )
    body = endpoint.post("/optimize-energy", json=case["input"]).json()

    no_op = next(item for item in body["directive_interpretation"] if item["directive_type"] == "no_op")
    assert "structured_adjustment" in no_op
    assert no_op["structured_adjustment"] is None
    assert no_op["applies"] is False


def test_the_interpreter_is_actually_on_the_path(endpoint, public_cases):
    """Guards the mandatory-LLM requirement: no model call means no answer."""
    before = endpoint.provider.calls
    endpoint.post("/optimize-energy", json=public_cases[0]["input"])

    assert endpoint.provider.calls == before + 1


def test_repeated_identical_requests_are_stable(endpoint, public_cases):
    case = public_cases[0]

    first = endpoint.post("/optimize-energy", json=case["input"]).json()
    second = endpoint.post("/optimize-energy", json=case["input"]).json()

    assert first == second


def test_health_stays_available_alongside_optimize_traffic(endpoint, public_cases):
    endpoint.post("/optimize-energy", json=public_cases[0]["input"])
    health = endpoint.get("/health")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}


def test_invalid_requests_still_map_correctly_with_the_pipeline_live(endpoint, adversarial_pack):
    """The 400/422 boundary must survive having a working interpreter behind it."""
    failures = []
    for case in adversarial_pack["invalid_request_cases"]:
        response = endpoint.post("/optimize-energy", json=case["input"])
        if response.status_code != case["expected_http_status"]:
            failures.append(f"{case['id']}: expected {case['expected_http_status']}, got {response.status_code}")

    assert not failures, "\n".join(failures)


def test_a_structurally_invalid_request_never_reaches_the_model(endpoint, public_cases):
    """No paid call for a request that was never going to be answerable."""
    import copy

    body = copy.deepcopy(public_cases[0]["input"])
    body["hours"] = body["hours"][:23]

    before = endpoint.provider.calls
    response = endpoint.post("/optimize-energy", json=body)

    assert response.status_code == 400
    assert endpoint.provider.calls == before


def test_an_infeasible_scenario_never_reaches_the_model(endpoint, public_cases):
    """The baseline screen runs before interpretation precisely to avoid this spend."""
    import copy

    body = copy.deepcopy(public_cases[0]["input"])
    body["battery"]["initial_energy_kwh"] = 10.0
    body["battery"]["minimum_energy_kwh"] = 80.0

    before = endpoint.provider.calls
    response = endpoint.post("/optimize-energy", json=body)

    assert response.status_code == 422
    assert endpoint.provider.calls == before
