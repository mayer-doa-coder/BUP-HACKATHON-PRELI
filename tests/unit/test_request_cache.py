"""Cache behaviour and — more importantly — cache *key* correctness.

A cache bug does not look like a crash. It looks like a correct-seeming answer computed for a
different scenario, which is the worst possible failure on a judged endpoint. So most of this
file is about collisions that must not happen: the same sentence with a different battery, the
same scenario under a different id, the same everything after a prompt or model change.

The eviction and expiry tests are ordinary; the key tests are the ones that matter.
"""

from __future__ import annotations

import copy
import time

import pytest

from app.cache.request_cache import (
    TtlLruCache,
    canonical_request_json,
    parser_cache_key,
    response_cache_key,
)
from app.config import Settings
from app.llm.prompts import build_system_prompt, build_user_payload
from app.schemas.request import OptimizeRequest


def _request(case, **overrides) -> OptimizeRequest:
    body = copy.deepcopy(case["input"])
    for key, value in overrides.items():
        if key == "battery":
            body["battery"].update(value)
        else:
            body[key] = value
    return OptimizeRequest.model_validate(body)


def _parser_key(request: OptimizeRequest, settings: Settings | None = None) -> str:
    settings = settings or Settings(_env_file=None)
    return parser_cache_key(
        system_prompt=build_system_prompt(settings),
        user_payload=build_user_payload(request),
        settings=settings,
        provider=settings.llm_provider,
        model=settings.llm_model,
    )


# ------------------------------------------------------------------ container behaviour


def test_stores_and_returns_a_value():
    cache: TtlLruCache[str] = TtlLruCache(max_size=4, ttl_seconds=60)
    cache.set("k", "v")

    assert cache.get("k") == "v"
    assert cache.stats.hits == 1
    assert cache.stats.misses == 0


def test_missing_key_is_a_miss():
    cache: TtlLruCache[str] = TtlLruCache(max_size=4, ttl_seconds=60)

    assert cache.get("absent") is None
    assert cache.stats.misses == 1


def test_evicts_least_recently_used_first():
    cache: TtlLruCache[str] = TtlLruCache(max_size=2, ttl_seconds=60)
    cache.set("a", "1")
    cache.set("b", "2")
    cache.get("a")  # 'a' is now the most recently used
    cache.set("c", "3")

    assert cache.get("a") == "1"
    assert cache.get("b") is None, "the least recently used entry should have gone"
    assert cache.get("c") == "3"
    assert cache.stats.evictions == 1


def test_entries_expire():
    cache: TtlLruCache[str] = TtlLruCache(max_size=4, ttl_seconds=0.05)
    cache.set("k", "v")
    time.sleep(0.08)

    assert cache.get("k") is None
    assert cache.stats.expirations == 1


def test_a_zero_sized_cache_is_simply_disabled():
    """Setting the size to zero must turn caching off, not raise or evict in a loop."""
    cache: TtlLruCache[str] = TtlLruCache(max_size=0, ttl_seconds=60)
    cache.set("k", "v")

    assert cache.get("k") is None
    assert len(cache) == 0


def test_overwriting_a_key_does_not_grow_the_cache():
    cache: TtlLruCache[str] = TtlLruCache(max_size=2, ttl_seconds=60)
    cache.set("k", "1")
    cache.set("k", "2")

    assert cache.get("k") == "2"
    assert len(cache) == 1


# ------------------------------------------------------- parser key: no false sharing


def test_the_same_note_with_a_different_battery_capacity_cannot_collide(public_cases):
    """The canonical example: "half the battery" is a different kWh figure per capacity."""
    base = _request(public_cases[0])
    bigger = _request(public_cases[0], battery={"capacity_kwh": base.battery.capacity_kwh * 2})

    assert _parser_key(base) != _parser_key(bigger)


@pytest.mark.parametrize(
    "field_name",
    [
        "capacity_kwh",
        "initial_energy_kwh",
        "minimum_energy_kwh",
        "max_charge_kwh_per_hour",
        "max_discharge_kwh_per_hour",
    ],
)
def test_every_battery_field_in_the_prompt_changes_the_key(public_cases, field_name):
    """All five reach the model, so all five must reach the key — not just capacity."""
    base = _request(public_cases[0])
    current = getattr(base.battery, field_name)
    changed = _request(public_cases[0], battery={field_name: current + 1.0})

    assert _parser_key(base) != _parser_key(changed), f"{field_name} is missing from the key"


def test_different_note_text_changes_the_key(public_cases):
    base = _request(public_cases[0])
    reworded = _request(public_cases[0], operator_notes=["Something else entirely."])

    assert _parser_key(base) != _parser_key(reworded)


def test_note_order_changes_the_key(public_cases):
    """note_index maps answers to notes, so a reordering is a different question."""
    case = next(c for c in public_cases if len(c["input"]["operator_notes"]) > 1)
    base = _request(case)
    swapped = _request(case, operator_notes=list(reversed(case["input"]["operator_notes"])))

    assert _parser_key(base) != _parser_key(swapped)


def test_identical_requests_share_a_key(public_cases):
    assert _parser_key(_request(public_cases[0])) == _parser_key(_request(public_cases[0]))


def test_the_24_hour_matrix_does_not_affect_the_parser_key(public_cases):
    """It never reaches the model, so two scenarios differing only there share an interpretation."""
    base = _request(public_cases[0])
    different_energy = copy.deepcopy(public_cases[0]["input"])
    for entry in different_energy["hours"]:
        entry["demand_kwh"] += 25.0
        entry["tariff_bdt_per_kwh"] += 3.0

    assert _parser_key(base) == _parser_key(OptimizeRequest.model_validate(different_energy))


@pytest.mark.parametrize(
    ("env_name", "value"),
    [
        ("PROMPT_VERSION", "gridwise-parser-v2"),
        ("SCHEMA_VERSION", "gridwise-directives-v2"),
        ("LLM_MODEL", "a-different-model"),
        ("LLM_PROVIDER", "anthropic"),
    ],
)
def test_version_changes_invalidate_the_parser_cache(public_cases, monkeypatch, env_name, value):
    request = _request(public_cases[0])
    before = _parser_key(request, Settings(_env_file=None))

    monkeypatch.setenv(env_name, value)
    after = _parser_key(request, Settings(_env_file=None))

    assert before != after, f"{env_name} must take part in the key"


def test_a_prompt_edit_invalidates_the_key_even_without_a_version_bump(public_cases, monkeypatch):
    """The key hashes the prompt text, so forgetting to bump PROMPT_VERSION is survivable."""
    settings = Settings(_env_file=None)
    request = _request(public_cases[0])
    before = _parser_key(request, settings)

    monkeypatch.setattr("app.llm.prompts._FACTOR_BLOCK", "COMPLETELY DIFFERENT RULES")
    after = parser_cache_key(
        system_prompt=build_system_prompt(settings),
        user_payload=build_user_payload(request),
        settings=settings,
        provider=settings.llm_provider,
        model=settings.llm_model,
    )

    assert before != after


# --------------------------------------------------- response key: whole-scenario identity


def test_a_different_scenario_id_cannot_share_a_response(public_cases):
    """The response echoes scenario_id, so sharing an entry would return the wrong id."""
    settings = Settings(_env_file=None)
    base = _request(public_cases[0])
    renamed = _request(public_cases[0], scenario_id="SOMETHING-ELSE")

    assert response_cache_key(base, settings) != response_cache_key(renamed, settings)


def test_a_different_tariff_cannot_share_a_response(public_cases):
    """Same notes, different prices: the interpretation matches but the plan must not."""
    settings = Settings(_env_file=None)
    base = _request(public_cases[0])
    dearer = copy.deepcopy(public_cases[0]["input"])
    for entry in dearer["hours"]:
        entry["tariff_bdt_per_kwh"] += 5.0

    assert response_cache_key(base, settings) != response_cache_key(
        OptimizeRequest.model_validate(dearer), settings
    )


def test_shuffled_hours_describe_the_same_scenario(public_cases):
    """Array position is not part of a scenario's identity, so the key must not depend on it."""
    settings = Settings(_env_file=None)
    base = _request(public_cases[0])
    shuffled = copy.deepcopy(public_cases[0]["input"])
    shuffled["hours"] = list(reversed(shuffled["hours"]))

    assert response_cache_key(base, settings) == response_cache_key(
        OptimizeRequest.model_validate(shuffled), settings
    )


@pytest.mark.parametrize(
    ("env_name", "value"),
    [
        ("OPTIMIZER_VERSION", "lp-milp-v2"),
        ("APP_COMMIT_SHA", "deadbeef"),
        ("PROMPT_VERSION", "gridwise-parser-v2"),
        ("LLM_MODEL", "another-model"),
    ],
)
def test_version_changes_invalidate_the_response_cache(public_cases, monkeypatch, env_name, value):
    request = _request(public_cases[0])
    before = response_cache_key(request, Settings(_env_file=None))

    monkeypatch.setenv(env_name, value)
    after = response_cache_key(request, Settings(_env_file=None))

    assert before != after, f"{env_name} must take part in the key"


def test_canonical_json_is_stable_and_ordered(public_cases):
    request = _request(public_cases[0])
    rendered = canonical_request_json(request)

    assert rendered == canonical_request_json(request)
    hours = [entry.hour for entry in request.canonical_hours()]
    assert hours == list(range(24))
    assert '"hour":0' in rendered


def test_key_segments_cannot_be_confused_by_concatenation():
    """Length-prefixed hashing: ("ab","c") and ("a","bc") must not collide."""
    settings = Settings(_env_file=None)
    first = parser_cache_key(
        system_prompt="ab", user_payload="c", settings=settings, provider="p", model="m"
    )
    second = parser_cache_key(
        system_prompt="a", user_payload="bc", settings=settings, provider="p", model="m"
    )

    assert first != second
