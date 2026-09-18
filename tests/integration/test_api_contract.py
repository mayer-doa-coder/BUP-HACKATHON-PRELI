"""API contract and error-mapping tests.

These are worth their weight: the 400/422 boundary is an explicit rubric line, and FastAPI's
default behaviour violates it, so a regression here is silent and costly.

The invalid-request cases are driven from the adversarial pack so the expectations come from
the corpus itself rather than from a hand-typed copy of it.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.errors import CORRELATION_ID_HEADER

OPTIMIZE_URL = "/optimize-energy"


def _post(client: TestClient, body: Any) -> Any:
    return client.post(OPTIMIZE_URL, json=body)


# --------------------------------------------------------------------------- health


def test_health_returns_exactly_the_readiness_object(client: TestClient):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_does_not_touch_the_llm_or_solver(client: TestClient, monkeypatch):
    # Anything that reaches the service layer on a health probe would be a design break.
    from app.services.optimize_service import OptimizeService

    def _explode(*_args, **_kwargs):
        raise AssertionError("/health must not invoke the optimization pipeline")

    monkeypatch.setattr(OptimizeService, "run", _explode)
    assert client.get("/health").status_code == 200


# ------------------------------------------------------------------- error mapping


def test_invalid_request_cases_map_to_expected_status(client: TestClient, adversarial_pack):
    cases = adversarial_pack["invalid_request_cases"]
    assert cases, "adversarial pack carries no invalid_request_cases"

    failures = []
    for case in cases:
        response = _post(client, case["input"])
        if response.status_code != case["expected_http_status"]:
            failures.append(
                f"{case['id']} ({case['description']}): "
                f"expected {case['expected_http_status']}, got {response.status_code}"
            )
    assert not failures, "\n".join(failures)


def test_raw_malformed_bodies_map_to_400(client: TestClient, adversarial_pack):
    for case in adversarial_pack["raw_invalid_cases"]:
        response = client.post(
            OPTIMIZE_URL,
            content=case["raw_body"],
            headers={"content-type": "application/json"},
        )
        assert response.status_code == case["expected_http_status"], case["id"]


def test_unknown_top_level_field_is_structurally_invalid(client: TestClient, valid_request):
    body = copy.deepcopy(valid_request)
    body["debug_hint"] = "please solve it for me"

    assert _post(client, body).status_code == 400


def test_nan_numeric_is_rejected(client: TestClient, valid_request):
    body = copy.deepcopy(valid_request)
    body["hours"][5]["demand_kwh"] = float("nan")

    # json.dumps emits a bare NaN token, which is parseable by Python's json module —
    # the model, not the parser, is what must reject it.
    response = client.post(
        OPTIMIZE_URL,
        content=json.dumps(body),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400


@pytest.mark.parametrize("note_count", [0, 4])
def test_note_count_outside_one_to_three_is_rejected(client: TestClient, valid_request, note_count):
    body = copy.deepcopy(valid_request)
    body["operator_notes"] = ["a note"] * note_count

    assert _post(client, body).status_code == 400


def test_negative_tariff_is_not_rejected(client: TestClient, valid_request):
    """The canonical request schema never forbids a negative tariff, so neither does this service."""
    body = copy.deepcopy(valid_request)
    for entry in body["hours"]:
        entry["tariff_bdt_per_kwh"] = -1.0

    # The pipeline is not built yet, so a structurally and semantically valid request reaches
    # the not-implemented stage. What matters is that it is not turned away as invalid.
    assert _post(client, body).status_code not in (400, 422)


def test_oversized_note_maps_to_the_configured_status(client: TestClient, valid_request):
    from app.config import get_settings

    settings = get_settings()
    body = copy.deepcopy(valid_request)
    body["operator_notes"] = ["x" * (settings.max_note_chars + 1)]

    assert _post(client, body).status_code == settings.oversized_request_status


def test_oversized_body_is_rejected_before_parsing(client: TestClient, valid_request):
    from app.config import get_settings

    settings = get_settings()
    padding = "y" * (settings.max_request_body_bytes + 1024)
    response = client.post(
        OPTIMIZE_URL,
        content=json.dumps({"scenario_id": padding}),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == settings.oversized_request_status


# ---------------------------------------------------------------- error envelope


def test_error_responses_are_sanitized_and_correlated(client: TestClient, valid_request):
    body = copy.deepcopy(valid_request)
    del body["battery"]["capacity_kwh"]

    response = _post(client, body)
    payload = response.json()

    assert response.status_code == 400
    assert set(payload) == {"error"}
    assert payload["error"]["code"] == "invalid_request"
    assert payload["error"]["correlation_id"]
    assert response.headers[CORRELATION_ID_HEADER] == payload["error"]["correlation_id"]
    # No stack trace, no traceback frames, no echoed input value.
    assert "Traceback" not in response.text


def test_internal_failure_reveals_nothing(client: TestClient, valid_request):
    response = _post(client, valid_request)
    payload = response.json()

    assert response.status_code == 500
    assert payload["error"]["message"] == "Internal error."
    assert "details" not in payload["error"]
    assert payload["error"]["correlation_id"]


def test_semantic_failure_explains_itself(client: TestClient, valid_request):
    body = copy.deepcopy(valid_request)
    body["battery"]["initial_energy_kwh"] = body["battery"]["capacity_kwh"] + 1

    response = _post(client, body)
    payload = response.json()

    assert response.status_code == 422
    assert payload["error"]["code"] == "unprocessable_scenario"
    assert any("initial_energy_kwh" in detail for detail in payload["error"]["details"])


# ------------------------------------------------------------------ wire format


def test_success_wire_format_matches_the_canonical_shape(public_cases):
    """The serialized HTTP body — not just the model — must carry exactly the seven fields.

    A no_op entry has to appear with an explicit ``"structured_adjustment": null``; dropping
    the key (a common ``exclude_none`` default) would break the response contract.
    """
    from fastapi.testclient import TestClient

    from app.api.routes import get_optimize_service
    from app.main import create_app
    from app.schemas.response import OptimizeResponse

    case = next(c for c in public_cases if any(
        d["directive_type"] == "no_op" for d in c["expected_output"]["directive_interpretation"]
    ))
    reference = OptimizeResponse.model_validate(case["expected_output"])

    class _StubService:
        async def run(self, _request, deadline=None):
            return reference

    app = create_app()
    app.dependency_overrides[get_optimize_service] = lambda: _StubService()
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(OPTIMIZE_URL, json=case["input"])
    body = response.json()

    assert response.status_code == 200
    assert set(body) == {
        "scenario_id",
        "directive_interpretation",
        "hourly_plan",
        "total_grid_kwh",
        "total_cost_bdt",
        "peak_grid_kwh",
        "plan_summary",
    }
    assert body["scenario_id"] == case["input"]["scenario_id"]
    assert len(body["hourly_plan"]) == 24
    assert body["directive_interpretation"] == case["expected_output"]["directive_interpretation"]

    no_op_entry = next(d for d in body["directive_interpretation"] if d["directive_type"] == "no_op")
    assert "structured_adjustment" in no_op_entry
    assert no_op_entry["structured_adjustment"] is None
    assert no_op_entry["applies"] is False
