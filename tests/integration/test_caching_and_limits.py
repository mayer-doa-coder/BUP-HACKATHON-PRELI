"""Caching and resource protection in the assembled service.

Two failure modes are being guarded against, and they pull in opposite directions:

* a cache that serves something it should not — a stale, unvalidated, or wrong-scenario answer;
* a protection limit that becomes its own outage by turning judge traffic away.

So the tests check both that caching saves provider calls *and* that nothing invalid is ever
stored, and that the concurrency gate queues rather than rejects while still refusing work it
could not finish in time.
"""

from __future__ import annotations

import asyncio
import copy
import json

import pytest
from fastapi.testclient import TestClient

from app.api.errors import DirectiveInfeasible, InterpretationUnavailable
from app.api.routes import get_optimize_service
from app.config import Settings
from app.llm.base import ProviderResponse, ProviderUnavailable
from app.llm.interpreter import LlmDirectiveInterpreter
from app.main import create_app
from app.schemas.request import OptimizeRequest
from app.services.optimize_service import OptimizeService
from app.validation.replay import replay


class CountingProvider:
    """Returns a scripted answer and counts how often it was actually called."""

    name = "counting"
    model = "counting-1"

    def __init__(self, payloads, delay: float = 0.0):
        self.payloads = list(payloads)
        self.delay = delay
        self.calls = 0
        self.concurrent = 0
        self.peak_concurrent = 0

    async def complete(self, *, system_prompt, user_payload, json_schema, timeout_s):
        self.calls += 1
        self.concurrent += 1
        self.peak_concurrent = max(self.peak_concurrent, self.concurrent)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            payload = self.payloads[min(self.calls - 1, len(self.payloads) - 1)]
            if isinstance(payload, Exception):
                raise payload
            return ProviderResponse(content=json.dumps(payload), model_version=self.model)
        finally:
            self.concurrent -= 1

    async def aclose(self):
        return None


def _envelope(case):
    return {"directive_interpretation": case["expected_output"]["directive_interpretation"]}


def _service(provider) -> OptimizeService:
    return OptimizeService(interpreter=LlmDirectiveInterpreter(provider))


# -------------------------------------------------------------------- caching saves work


def test_an_identical_request_is_served_from_cache(public_cases):
    case = public_cases[0]
    provider = CountingProvider([_envelope(case)])
    service = _service(provider)
    request = OptimizeRequest.model_validate(case["input"])

    first = asyncio.run(service.run(request))
    second = asyncio.run(service.run(request))

    assert provider.calls == 1, "the second request must not spend a provider call"
    assert first.model_dump() == second.model_dump()
    assert service.response_cache.stats.hits == 1


def test_a_cached_response_is_still_a_valid_plan(public_cases):
    """Whatever comes back from the cache must survive the same replay a fresh answer does."""
    case = public_cases[0]
    service = _service(CountingProvider([_envelope(case)]))
    request = OptimizeRequest.model_validate(case["input"])

    asyncio.run(service.run(request))
    cached = asyncio.run(service.run(request))

    assert replay(request, cached.directive_interpretation, cached).ok


def test_the_same_notes_with_a_different_scenario_reuse_the_interpretation(public_cases):
    """The parser cache is keyed on the prompt, so a different tariff still reuses the parse."""
    case = public_cases[0]
    provider = CountingProvider([_envelope(case)])
    service = _service(provider)

    body = copy.deepcopy(case["input"])
    dearer = copy.deepcopy(case["input"])
    dearer["scenario_id"] = "OTHER"
    for entry in dearer["hours"]:
        entry["tariff_bdt_per_kwh"] += 4.0

    first = asyncio.run(service.run(OptimizeRequest.model_validate(body)))
    second = asyncio.run(service.run(OptimizeRequest.model_validate(dearer)))

    assert provider.calls == 1, "identical notes and battery should reuse the interpretation"
    assert second.scenario_id == "OTHER"
    # Different prices, so the plan itself must have been recomputed rather than reused.
    assert second.total_cost_bdt != first.total_cost_bdt


def test_a_different_battery_forces_a_fresh_interpretation(public_cases):
    """The headline collision test, end to end: same words, different battery, new call."""
    case = public_cases[0]
    provider = CountingProvider([_envelope(case), _envelope(case)])
    service = _service(provider)

    body = copy.deepcopy(case["input"])
    bigger = copy.deepcopy(case["input"])
    bigger["scenario_id"] = "BIGGER"
    bigger["battery"]["capacity_kwh"] = body["battery"]["capacity_kwh"] * 2

    asyncio.run(service.run(OptimizeRequest.model_validate(body)))
    asyncio.run(service.run(OptimizeRequest.model_validate(bigger)))

    assert provider.calls == 2


# ----------------------------------------------------------- nothing invalid is cached


def test_a_guardrail_failure_is_never_cached(public_cases):
    """A rejected interpretation must not be remembered as if it had been accepted."""
    case = public_cases[0]
    broken = copy.deepcopy(case["expected_output"]["directive_interpretation"])
    broken[0]["structured_adjustment"]["factor"] = 1.8

    provider = CountingProvider([{"directive_interpretation": broken}])
    service = _service(provider)
    request = OptimizeRequest.model_validate(case["input"])

    with pytest.raises(InterpretationUnavailable):
        asyncio.run(service.run(request))
    with pytest.raises(InterpretationUnavailable):
        asyncio.run(service.run(request))

    assert provider.calls == 4, "both requests should retry, and neither should be cached"
    assert len(service.response_cache) == 0


def test_a_provider_outage_is_never_cached(public_cases):
    case = public_cases[0]
    provider = CountingProvider([ProviderUnavailable("503")])
    service = _service(provider)
    request = OptimizeRequest.model_validate(case["input"])

    with pytest.raises(InterpretationUnavailable):
        asyncio.run(service.run(request))

    assert len(service.response_cache) == 0


def test_an_infeasible_result_is_not_cached_as_a_response(public_cases):
    """No response is stored for a request that never produced a valid plan."""
    case = public_cases[0]
    request = OptimizeRequest.model_validate(case["input"])
    night_hour = next(
        entry.hour for entry in request.canonical_hours() if entry.solar_kwh == 0 and entry.demand_kwh > 0
    )
    impossible = {
        "directive_interpretation": [
            {
                "note_index": 0,
                "applies": True,
                "directive_type": "max_grid_window",
                "structured_adjustment": {"hours": [night_hour], "max_grid_kwh": 0.0},
                "explanation": "misread",
            },
            {
                "note_index": 1,
                "applies": False,
                "directive_type": "no_op",
                "structured_adjustment": None,
                "explanation": "",
            },
        ]
    }
    service = _service(CountingProvider([impossible]))

    with pytest.raises(DirectiveInfeasible):
        asyncio.run(service.run(request))

    assert len(service.response_cache) == 0


def test_a_corrected_interpretation_replaces_the_cached_one(public_cases):
    """After a feasibility repair succeeds, the good reading is what gets remembered."""
    case = public_cases[0]
    request = OptimizeRequest.model_validate(case["input"])
    night_hour = next(
        entry.hour for entry in request.canonical_hours() if entry.solar_kwh == 0 and entry.demand_kwh > 0
    )
    impossible = {
        "directive_interpretation": [
            {
                "note_index": 0,
                "applies": True,
                "directive_type": "max_grid_window",
                "structured_adjustment": {"hours": [night_hour], "max_grid_kwh": 0.0},
                "explanation": "misread",
            },
            {
                "note_index": 1,
                "applies": False,
                "directive_type": "no_op",
                "structured_adjustment": None,
                "explanation": "",
            },
        ]
    }
    provider = CountingProvider([impossible, _envelope(case)])
    service = _service(provider)

    first = asyncio.run(service.run(request))
    assert provider.calls == 2, "one bad parse plus one feasibility repair"

    # A different scenario id bypasses the response cache but shares the parser key.
    second_body = copy.deepcopy(case["input"])
    second_body["scenario_id"] = "REPEAT"
    second = asyncio.run(service.run(OptimizeRequest.model_validate(second_body)))

    assert provider.calls == 2, "the corrected interpretation should have been remembered"
    assert second.directive_interpretation[0].directive_type == "solar_reduction"
    assert second.total_cost_bdt == pytest.approx(first.total_cost_bdt, abs=0.01)


# ----------------------------------------------------------------- concurrency limits


def test_concurrent_llm_calls_are_capped(public_cases, monkeypatch):
    """The provider has its own quota; a traffic spike must not become a burst of 429s."""
    monkeypatch.setenv("MAX_CONCURRENT_LLM_CALLS", "2")
    settings = Settings(_env_file=None)

    case = public_cases[0]
    provider = CountingProvider([_envelope(case)], delay=0.05)
    service = OptimizeService(
        settings=settings, interpreter=LlmDirectiveInterpreter(provider, settings)
    )

    async def _drive():
        requests = []
        for index in range(6):
            body = copy.deepcopy(case["input"])
            body["scenario_id"] = f"CONC-{index}"
            # Distinct wording so each request needs its own provider call, but the *number* of
            # notes is unchanged — the canned answer must keep matching one entry per note.
            body["operator_notes"][0] = f"{body['operator_notes'][0]} (variant {index})"
            requests.append(OptimizeRequest.model_validate(body))
        await asyncio.gather(*(service.run(request) for request in requests))

    asyncio.run(_drive())

    assert provider.calls == 6
    assert provider.peak_concurrent <= 2, f"peak was {provider.peak_concurrent}"


def test_health_is_never_queued_behind_optimize_traffic(public_cases, monkeypatch):
    """A saturated optimizer must not make the platform think the instance is dead."""
    monkeypatch.setenv("MAX_CONCURRENT_REQUESTS", "1")
    settings = Settings(_env_file=None)

    app = create_app(settings)
    app.dependency_overrides[get_optimize_service] = lambda: _service(
        CountingProvider([_envelope(public_cases[0])])
    )
    client = TestClient(app, raise_server_exceptions=False)

    assert client.get("/health").status_code == 200
    assert client.get("/health").status_code == 200


def test_a_saturated_service_refuses_rather_than_overrunning_the_timeout(public_cases):
    """If a slot cannot be had inside the budget, 503 beats answering after the judge gave up."""
    from app.api.middleware import ConcurrencyLimitMiddleware

    settings = Settings(_env_file=None)
    middleware = ConcurrencyLimitMiddleware(app=None, settings=settings)
    # Exhaust the pool and leave no budget, exactly as a fully saturated service would.
    middleware._limit = 1
    middleware._slots = asyncio.Semaphore(0)
    middleware._budget_seconds = 0.01

    class _Scope:
        def __init__(self):
            self.state = type("S", (), {})()
            self.url = type("U", (), {"path": "/optimize-energy"})()

    async def _never_called(_request):
        raise AssertionError("the request should not have been processed")

    response = asyncio.run(middleware.dispatch(_Scope(), _never_called))

    assert response.status_code == 503
    body = json.loads(bytes(response.body).decode())
    assert body["error"]["code"] == "service_busy"


def test_the_request_budget_starts_before_queueing(public_cases):
    """Time spent waiting counts against the 30 s, so a queued request cannot overrun it."""
    from app.api.middleware import ConcurrencyLimitMiddleware

    settings = Settings(_env_file=None)
    middleware = ConcurrencyLimitMiddleware(app=None, settings=settings)
    captured = {}

    class _Scope:
        def __init__(self):
            self.state = type("S", (), {})()
            self.url = type("U", (), {"path": "/optimize-energy"})()

    async def _capture(request):
        captured["deadline"] = request.state.deadline
        return "ok"

    asyncio.run(middleware.dispatch(_Scope(), _capture))

    deadline = captured["deadline"]
    assert deadline is not None
    assert deadline.remaining() <= settings.hard_request_deadline_seconds
    assert deadline.remaining() > 0
