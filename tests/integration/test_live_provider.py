"""Opt-in live check against the configured provider.

Excluded from the normal suite and from CI: it needs real credentials, costs money, and depends
on a third party being up. Run it deliberately before judging, as the warm canary described in
Guide §7.4 — it is the only test that proves the credentials, quota, and the structured-output
schema all work together against the *exact* production model.

    pytest -m live tests/integration/test_live_provider.py
"""

from __future__ import annotations

import asyncio

import pytest

from app.config import get_settings
from app.llm.interpreter import build_interpreter, coerce_to_canonical
from app.schemas.request import OptimizeRequest

pytestmark = pytest.mark.live


@pytest.fixture
def interpreter():
    built = build_interpreter()
    if built is None:
        pytest.skip("no LLM provider configured (set LLM_PROVIDER, LLM_MODEL, LLM_API_KEY)")
    return built


def test_live_model_interprets_a_public_case(interpreter, public_cases):
    """A real call, parsed and validated exactly as the judge path would."""
    case = public_cases[0]
    request = OptimizeRequest.model_validate(case["input"])

    outcome = asyncio.run(interpreter.interpret(request))
    directives = coerce_to_canonical(outcome.raw_items)

    assert len(directives) == len(request.operator_notes)
    assert [item.note_index for item in directives] == list(range(len(request.operator_notes)))
    print(f"\nmodel={outcome.model_version} latency={outcome.latency_ms:.0f}ms")
    for directive in directives:
        print(f"  note {directive.note_index}: {directive.directive_type} {directive.structured_adjustment}")


def test_live_model_is_within_the_latency_budget(interpreter, public_cases):
    settings = get_settings()
    request = OptimizeRequest.model_validate(public_cases[5]["input"])  # three notes

    outcome = asyncio.run(interpreter.interpret(request))

    budget_ms = settings.soft_response_budget_seconds * 1000
    assert outcome.latency_ms < budget_ms, (
        f"interpretation took {outcome.latency_ms:.0f}ms against a {budget_ms:.0f}ms budget"
    )
