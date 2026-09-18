"""Demo layer tests.

Two obligations, and the first one outranks everything else in this file:

1. **The demo must not touch the judged contract.** Enabled or disabled, ``/optimize-energy``
   returns the same seven fields and ``/health`` behaves identically. A demo that changed the
   judged response would trade a scored category for an unscored one.
2. The demo must show the *real* pipeline, not a re-implementation — so its numbers are checked
   against the canonical response and the independent replay.
"""

from __future__ import annotations

import copy
import json

import pytest
from fastapi.testclient import TestClient

from app.api.routes import get_optimize_service
from app.config import Settings
from app.demo.routes import demo_enabled
from app.llm.base import ProviderResponse
from app.llm.interpreter import LlmDirectiveInterpreter
from app.main import create_app
from app.services.optimize_service import OptimizeService

CANONICAL_FIELDS = {
    "scenario_id",
    "directive_interpretation",
    "hourly_plan",
    "total_grid_kwh",
    "total_cost_bdt",
    "peak_grid_kwh",
    "plan_summary",
}


class ReferenceProvider:
    name = "reference"
    model = "reference-1"

    def __init__(self, by_notes):
        self.by_notes = by_notes
        self.calls = 0

    async def complete(self, *, system_prompt, user_payload, json_schema, timeout_s):
        self.calls += 1
        payload = json.loads(user_payload[user_payload.index("{") : user_payload.rindex("}") + 1])
        notes = tuple(note["text"] for note in payload["operator_notes"])
        entries = self.by_notes.get(notes)
        if entries is None:
            # A paraphrase or single-note lookup: answer with the first directive, reindexed.
            first = next(iter(self.by_notes.values()))
            entries = [dict(first[0], note_index=0)]
        return ProviderResponse(
            content=json.dumps({"directive_interpretation": entries}), model_version=self.model
        )

    async def aclose(self):
        return None


def _demo_settings(**overrides) -> Settings:
    return Settings(_env_file=None, demo_mode=True, judge_mode=False, **overrides)


@pytest.fixture
def demo_client(public_cases):
    by_notes = {
        tuple(case["input"]["operator_notes"]): case["expected_output"]["directive_interpretation"]
        for case in public_cases
    }
    provider = ReferenceProvider(by_notes)
    settings = _demo_settings()
    service = OptimizeService(settings=settings, interpreter=LlmDirectiveInterpreter(provider, settings))

    app = create_app(settings)
    app.dependency_overrides[get_optimize_service] = lambda: service
    client = TestClient(app, raise_server_exceptions=False)
    client.provider = provider  # type: ignore[attr-defined]
    return client


# --------------------------------------------------- the judged contract is untouched


def test_demo_routes_are_absent_by_default(public_cases):
    """Production defaults expose nothing extra."""
    client = TestClient(create_app(Settings(_env_file=None)), raise_server_exceptions=False)

    assert client.get("/demo").status_code == 404
    assert client.post("/demo/analyze", json=public_cases[0]["input"]).status_code == 404
    assert client.get("/health").status_code == 200


def test_demo_mode_alone_is_not_enough(public_cases):
    """A deployment that ships DEMO_MODE=true by accident still exposes nothing."""
    settings = Settings(_env_file=None, demo_mode=True)  # judge_mode defaults to True

    assert demo_enabled(settings) is False
    client = TestClient(create_app(settings), raise_server_exceptions=False)
    assert client.get("/demo").status_code == 404


def test_the_canonical_response_is_identical_with_the_demo_enabled(demo_client, public_cases):
    case = public_cases[0]

    response = demo_client.post("/optimize-energy", json=case["input"])
    body = response.json()

    assert response.status_code == 200
    assert set(body) == CANONICAL_FIELDS, "the demo must not add a field to the judged response"
    assert abs(body["total_cost_bdt"] - case["expected_output"]["total_cost_bdt"]) <= 0.01


def test_demo_routes_stay_out_of_the_public_schema(demo_client):
    """They should not appear in the OpenAPI document a reviewer reads as 'the contract'."""
    paths = demo_client.get("/openapi.json").json()["paths"]

    assert "/optimize-energy" in paths
    assert "/health" in paths
    assert not [path for path in paths if path.startswith("/demo")]


# ------------------------------------------------------------------ the demo shows truth


def test_analyze_returns_the_full_pipeline_trace(demo_client, public_cases):
    case = public_cases[0]

    response = demo_client.post("/demo/analyze", json=case["input"])
    body = response.json()

    assert response.status_code == 200
    assert body["scenario_id"] == case["input"]["scenario_id"]
    assert len(body["interpretation"]) == len(case["input"]["operator_notes"])
    assert len(body["hours"]) == 24
    assert body["validation"]["passed"] is True
    assert body["solver"]["proven_optimal"] is True
    assert body["solver"]["lower_bound_respected"] is True


def test_the_demo_numbers_match_the_canonical_response(demo_client, public_cases):
    """The demo must report the same plan the judge would get, not a second computation."""
    case = public_cases[0]

    canonical = demo_client.post("/optimize-energy", json=case["input"]).json()
    demo = demo_client.post("/demo/analyze", json=case["input"]).json()

    assert demo["totals_cost_bdt"] == pytest.approx(canonical["total_cost_bdt"], abs=0.01)
    assert demo["totals_grid_kwh"] == pytest.approx(canonical["total_grid_kwh"], abs=0.01)
    assert [h["grid_kwh"] for h in demo["plan"]] == [h["grid_kwh"] for h in canonical["hourly_plan"]]


def test_effective_solar_is_shown_next_to_the_original(demo_client, public_cases):
    """The point of the solar row: what the note changed, visibly."""
    case = next(
        c
        for c in public_cases
        if any(d["directive_type"] == "solar_reduction" for d in c["expected_output"]["directive_interpretation"])
    )
    directive = next(
        d for d in case["expected_output"]["directive_interpretation"] if d["directive_type"] == "solar_reduction"
    )
    reduced_hour = directive["structured_adjustment"]["hours"][0]

    body = demo_client.post("/demo/analyze", json=case["input"]).json()
    hour = next(h for h in body["hours"] if h["hour"] == reduced_hour)

    assert hour["effective_solar_kwh"] < hour["original_solar_kwh"]
    assert hour["effective_solar_kwh"] == pytest.approx(
        hour["original_solar_kwh"] * directive["structured_adjustment"]["factor"]
    )


def test_constraint_origins_name_the_note_behind_each_bound(demo_client, public_cases):
    case = next(
        c
        for c in public_cases
        if any(d["directive_type"] == "minimum_battery_reserve" for d in c["expected_output"]["directive_interpretation"])
    )

    body = demo_client.post("/demo/analyze", json=case["input"]).json()
    origins = body["constraint_origins"]

    assert origins, "provenance should be recorded for an applied directive"
    assert all("source_note_index" in item for item in origins)
    assert any(item["field"] == "min_energy" for item in origins)


def test_binding_constraints_are_identified(demo_client, public_cases):
    case = next(
        c
        for c in public_cases
        if any(d["directive_type"] == "max_grid_window" for d in c["expected_output"]["directive_interpretation"])
    )

    body = demo_client.post("/demo/analyze", json=case["input"]).json()

    assert any(hour["binding"] for hour in body["hours"])


def test_an_infeasible_baseline_is_labelled_not_faked(demo_client, public_cases):
    """A saving against a plan nobody could legally run would be a dishonest comparison."""
    case = public_cases[0]
    body = copy.deepcopy(case["input"])
    body["operator_notes"] = [case["input"]["operator_notes"][0]]

    analysis = demo_client.post("/demo/analyze", json=body).json()
    comparison = analysis["cost_comparison"]

    assert "baseline_feasible" in comparison
    if comparison["baseline_feasible"]:
        assert comparison["baseline_cost_bdt"] >= analysis["totals_cost_bdt"] - 0.01
    else:
        assert comparison["baseline_cost_bdt"] is None
        assert comparison["baseline_note"]


# -------------------------------------------------------------------------- the labs


def test_what_if_reruns_and_reports_the_difference(demo_client, public_cases):
    case = public_cases[0]

    response = demo_client.post(
        "/demo/what-if",
        json={"scenario": case["input"], "changes": {"tariff_multiplier": 2.0}},
    )
    body = response.json()

    assert response.status_code == 200
    # Doubling every tariff doubles the cost of the same energy, so cost must rise.
    assert body["modified_cost_bdt"] > body["baseline_cost_bdt"]
    assert body["cost_delta_bdt"] == pytest.approx(
        body["modified_cost_bdt"] - body["baseline_cost_bdt"]
    )
    assert body["modified"]["validation"]["passed"] is True


def test_what_if_rejects_a_body_without_a_scenario(demo_client):
    assert demo_client.post("/demo/what-if", json={"changes": {}}).status_code == 400


def test_paraphrase_lab_compares_variants(demo_client, public_cases):
    case = public_cases[0]

    response = demo_client.post(
        "/demo/paraphrase",
        json={
            "scenario": case["input"],
            "reference": case["input"]["operator_notes"][0],
            "variants": ["A differently worded version of the same instruction."],
        },
    )
    body = response.json()

    assert response.status_code == 200
    assert body["reference"]["directive_type"]
    assert len(body["variants"]) == 1
    assert "matches_reference" in body["variants"][0]


def test_public_case_runner_is_exposed(demo_client):
    body = demo_client.get("/demo/public-cases").json()

    assert body["total"] == 10
    assert body["passed"] == 10
    assert all(case["validity"] == "PASS" for case in body["cases"])


def test_config_view_exposes_versions_but_never_secrets(demo_client):
    body = demo_client.get("/demo/config").json()

    assert body["prompt_version"]
    assert body["optimizer_version"]
    assert set(body["provisional_policies"]) == {
        "cross_midnight",
        "through_range",
        "solar_overlap",
        "single_hour_phrase",
    }
    # Presence only — never the value.
    assert isinstance(body["llm_configured"], bool)
    assert "api_key" not in json.dumps(body).lower()


def test_the_dashboard_page_is_self_contained(demo_client):
    response = demo_client.get("/demo")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    page = response.text
    assert "<svg" in page or "svg" in page
    # No external fetches: a container may have no outbound internet during a demo.
    assert "http://" not in page.replace("http://www.w3.org", "")
    assert "cdn." not in page
    assert "<script src=" not in page


def test_the_demo_reports_a_missing_interpreter_clearly(public_cases):
    """Without a model the demo cannot run, and it should say so rather than 500 silently."""
    settings = _demo_settings()
    app = create_app(settings)
    app.dependency_overrides[get_optimize_service] = lambda: OptimizeService(settings=settings)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/demo/analyze", json=public_cases[0]["input"])

    assert response.status_code == 503
    # The demo shares the service-wide error envelope from P1 rather than FastAPI's raw
    # ``{"detail": ...}``, so every failure on this service looks the same to a reader.
    assert "LLM_MODEL" in response.json()["error"]["message"]
