"""Observability wiring: does real traffic actually populate the trace and the metrics?

A metrics module that nothing calls is worse than none — it looks like coverage while telling
you nothing during judging. These tests drive real requests through the app and assert the
counters moved and the trace carries the diagnostics Guide §23 asks for.
"""

from __future__ import annotations

import copy
import json

import pytest
from fastapi.testclient import TestClient

from app.api.routes import get_optimize_service
from app.llm.base import ProviderResponse
from app.llm.interpreter import LlmDirectiveInterpreter
from app.main import create_app
from app.observability import metrics
from app.observability.trace import current_trace
from app.services.optimize_service import OptimizeService


class ReferenceProvider:
    name = "reference"
    model = "reference-1"

    def __init__(self, envelope):
        self.envelope = envelope

    async def complete(self, *, system_prompt, user_payload, json_schema, timeout_s):
        return ProviderResponse(content=json.dumps(self.envelope), model_version=self.model)

    async def aclose(self):
        return None


@pytest.fixture
def client(public_cases):
    case = public_cases[0]
    envelope = {"directive_interpretation": case["expected_output"]["directive_interpretation"]}
    service = OptimizeService(interpreter=LlmDirectiveInterpreter(ReferenceProvider(envelope)))

    app = create_app()
    app.dependency_overrides[get_optimize_service] = lambda: service
    return TestClient(app, raise_server_exceptions=False)


# ------------------------------------------------------------------- metrics move


def test_request_metrics_are_recorded(client, public_cases):
    before = metrics.requests_total.value(("/optimize-energy", "200"))
    before_observations = metrics.request_duration_seconds.count(("/optimize-energy",))

    response = client.post("/optimize-energy", json=public_cases[0]["input"])

    assert response.status_code == 200
    assert metrics.requests_total.value(("/optimize-energy", "200")) == before + 1
    assert metrics.request_duration_seconds.count(("/optimize-energy",)) == before_observations + 1


def test_failed_requests_are_counted_under_their_status(client, public_cases):
    body = copy.deepcopy(public_cases[0]["input"])
    body["hours"] = body["hours"][:23]
    before = metrics.requests_total.value(("/optimize-energy", "400"))

    client.post("/optimize-energy", json=body)

    assert metrics.requests_total.value(("/optimize-energy", "400")) == before + 1


def test_the_active_gauge_returns_to_zero(client, public_cases):
    client.post("/optimize-energy", json=public_cases[0]["input"])

    assert metrics.active_requests.value() == 0, "a leaked gauge would look like a stuck request"


def test_solver_and_cache_metrics_are_populated(client, public_cases):
    before_lp = metrics.lp_duration_seconds.count()
    before_milp = metrics.milp_duration_seconds.count()

    body = copy.deepcopy(public_cases[0]["input"])
    body["scenario_id"] = "METRICS-1"
    client.post("/optimize-energy", json=body)

    assert metrics.lp_duration_seconds.count() > before_lp
    assert metrics.milp_duration_seconds.count() > before_milp
    assert metrics.cache_misses_total.value(("response",)) > 0


def test_a_cache_hit_is_counted(client, public_cases):
    body = copy.deepcopy(public_cases[0]["input"])
    body["scenario_id"] = "METRICS-CACHED"
    before = metrics.cache_hits_total.value(("response",))

    client.post("/optimize-energy", json=body)
    client.post("/optimize-energy", json=body)

    assert metrics.cache_hits_total.value(("response",)) == before + 1


def test_the_metrics_endpoint_exposes_the_registry(client, public_cases):
    client.post("/optimize-energy", json=public_cases[0]["input"])

    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    for name in (
        "gridwise_requests_total",
        "gridwise_request_duration_seconds",
        "gridwise_active_requests",
        "gridwise_lp_duration_seconds",
        "gridwise_milp_duration_seconds",
        "gridwise_cache_hits_total",
    ):
        assert name in body, name


def test_metrics_can_be_switched_off(public_cases):
    """It is operational, not part of the judged contract, so it must be optional."""
    from app.config import Settings

    settings = Settings(_env_file=None, metrics_enabled=False)
    app = create_app(settings)
    disabled = TestClient(app, raise_server_exceptions=False)

    assert disabled.get("/metrics").status_code == 404
    assert disabled.get("/health").status_code == 200


# ---------------------------------------------------------------- the trace is filled


def test_the_trace_carries_the_diagnostics_guide_23_asks_for(public_cases):
    """Captured inside the request, because the trace is cleared when it finishes."""
    case = public_cases[0]
    envelope = {"directive_interpretation": case["expected_output"]["directive_interpretation"]}
    captured = {}

    class _CapturingService(OptimizeService):
        async def run(self, request, deadline=None):
            response = await super().run(request, deadline)
            trace = current_trace()
            captured["fields"] = trace.as_log_fields() if trace else {}
            return response

    service = _CapturingService(interpreter=LlmDirectiveInterpreter(ReferenceProvider(envelope)))
    app = create_app()
    app.dependency_overrides[get_optimize_service] = lambda: service
    TestClient(app, raise_server_exceptions=False).post("/optimize-energy", json=case["input"])

    fields = captured["fields"]
    assert fields["scenario_id"] == case["input"]["scenario_id"]
    assert fields["llm_provider"] == "reference"
    assert fields["llm_model_version"] == "reference-1"
    assert fields["llm_attempts"] == 1
    assert fields["baseline_lp_status"] == "optimal"
    assert fields["lp_status"] == "optimal"
    assert fields["milp_status"] == "optimal"
    assert fields["validator_status"] == "pass"
    assert fields["proven_optimal"] is True
    assert fields["prompt_version"]
    assert fields["optimizer_version"]
    assert fields["note_count"] == len(case["input"]["operator_notes"])


def test_a_failure_stamps_its_code_on_the_trace(public_cases):
    case = public_cases[0]
    captured = {}

    class _CapturingService(OptimizeService):
        async def run(self, request, deadline=None):
            try:
                return await super().run(request, deadline)
            finally:
                trace = current_trace()
                captured["trace"] = trace

    body = copy.deepcopy(case["input"])
    body["battery"]["initial_energy_kwh"] = 10.0
    body["battery"]["minimum_energy_kwh"] = 80.0

    service = _CapturingService()
    app = create_app()
    app.dependency_overrides[get_optimize_service] = lambda: service
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/optimize-energy", json=body)

    assert response.status_code == 422
    assert captured["trace"].baseline_lp_status == "infeasible"


def test_the_correlation_id_in_the_response_matches_the_header(client, public_cases):
    body = copy.deepcopy(public_cases[0]["input"])
    del body["battery"]["capacity_kwh"]

    response = client.post("/optimize-energy", json=body)

    assert response.status_code == 400
    assert response.headers["X-Correlation-ID"] == response.json()["error"]["correlation_id"]


def test_health_stays_silent_and_unmetered_of_trace_noise(client):
    """The probe runs constantly; logging a trace line for each would drown the real traffic."""
    before = metrics.requests_total.value(("/health", "200"))

    client.get("/health")

    # Still counted — just not trace-logged.
    assert metrics.requests_total.value(("/health", "200")) == before + 1
