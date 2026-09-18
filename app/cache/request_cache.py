"""Bounded LRU + TTL caches for interpretations and whole responses.

A cache is a latency optimization, never a semantic fallback: nothing here can answer a request
the pipeline could not answer itself, and a provider outage must not be papered over by serving
something stale from a different scenario.

**Key composition is the correctness-critical part.** Guide §21 warns against keying the parser
cache on note text alone, and the reason is concrete: the same sentence means different things
for different batteries — "keep half the battery in reserve" is 100 kWh at one capacity and 250
at another. This module goes further than keying on capacity: it hashes the **exact prompt that
would be sent**, so anything that can change the model's input — any battery field, note text,
note order, or a prompt edit that slipped through without a version bump — necessarily changes
the key. A field can never be forgotten, because the key is derived from the payload itself
rather than from a hand-maintained list.

What may be cached:

* an interpretation, only once the deterministic guardrails have accepted it;
* a full response, only once independent replay has accepted it.

Never cached: refusals, malformed output, guardrail failures, solver failures, replay failures,
or anything from a request that did not complete.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings, get_settings
from app.schemas.request import OptimizeRequest


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    expirations: int = 0
    stores: int = 0

    @property
    def lookups(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        return self.hits / self.lookups if self.lookups else 0.0


@dataclass
class TtlLruCache[ValueT]:
    """A small, bounded, time-limited LRU cache.

    Guarded by a lock: the endpoint is async and single-threaded per worker today, but a cache
    that quietly corrupts under a future threaded execution model is not worth the risk for the
    few microseconds a lock costs.
    """

    max_size: int
    ttl_seconds: float
    _entries: OrderedDict[str, tuple[float, ValueT]] = field(default_factory=OrderedDict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    stats: CacheStats = field(default_factory=CacheStats)

    def get(self, key: str) -> ValueT | None:
        if self.max_size <= 0:
            return None
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self.stats.misses += 1
                return None
            stored_at, value = entry
            if now - stored_at > self.ttl_seconds:
                del self._entries[key]
                self.stats.expirations += 1
                self.stats.misses += 1
                return None
            self._entries.move_to_end(key)
            self.stats.hits += 1
            return value

    def set(self, key: str, value: ValueT) -> None:
        if self.max_size <= 0:
            return
        with self._lock:
            if key in self._entries:
                self._entries.move_to_end(key)
            self._entries[key] = (time.monotonic(), value)
            self.stats.stores += 1
            while len(self._entries) > self.max_size:
                self._entries.popitem(last=False)
                self.stats.evictions += 1

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


# ----------------------------------------------------------------------- key building


def parser_cache_key(
    *,
    system_prompt: str,
    user_payload: str,
    settings: Settings | None = None,
    provider: str,
    model: str,
) -> str:
    """Key for a cached interpretation.

    Derived from the literal prompt text, so every battery field, the note wording, the note
    order, and any prompt change are all covered without enumerating them. Versions are included
    separately so a bumped ``PROMPT_VERSION`` invalidates even if the rendered text is identical.
    """
    settings = settings or get_settings()
    return _digest(
        [
            "parser-v1",
            settings.prompt_version,
            settings.schema_version,
            provider,
            model,
            system_prompt,
            user_payload,
        ]
    )


def response_cache_key(request: OptimizeRequest, settings: Settings | None = None) -> str:
    """Key for a cached full response.

    Covers the entire scenario — including ``scenario_id``, which the response echoes, so two
    otherwise identical scenarios with different ids can never share an entry — plus every
    version that could change the answer: prompt, schema, model, optimizer, and the code itself.
    """
    settings = settings or get_settings()
    return _digest(
        [
            "response-v1",
            settings.prompt_version,
            settings.schema_version,
            settings.llm_provider,
            settings.llm_model,
            settings.optimizer_version,
            settings.app_commit_sha,
            canonical_request_json(request),
        ]
    )


def canonical_request_json(request: OptimizeRequest) -> str:
    """A stable JSON rendering of a request.

    Hours are emitted in canonical order, so the same scenario submitted with its hours shuffled
    hits the same entry — array position is never part of a scenario's identity.
    """
    payload: dict[str, Any] = {
        "scenario_id": request.scenario_id,
        "operator_notes": list(request.operator_notes),
        "hours": [
            {
                "hour": entry.hour,
                "demand_kwh": entry.demand_kwh,
                "solar_kwh": entry.solar_kwh,
                "tariff_bdt_per_kwh": entry.tariff_bdt_per_kwh,
            }
            for entry in request.canonical_hours()
        ],
        "battery": {
            "capacity_kwh": request.battery.capacity_kwh,
            "initial_energy_kwh": request.battery.initial_energy_kwh,
            "minimum_energy_kwh": request.battery.minimum_energy_kwh,
            "max_charge_kwh_per_hour": request.battery.max_charge_kwh_per_hour,
            "max_discharge_kwh_per_hour": request.battery.max_discharge_kwh_per_hour,
        },
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _digest(parts: list[str]) -> str:
    hasher = hashlib.sha256()
    for part in parts:
        # Length-prefixed so that concatenation cannot be ambiguous: ("ab", "c") and ("a", "bc")
        # must not produce the same digest.
        encoded = part.encode("utf-8")
        hasher.update(str(len(encoded)).encode("ascii"))
        hasher.update(b"\x00")
        hasher.update(encoded)
    return hasher.hexdigest()


def build_cache(settings: Settings | None = None) -> TtlLruCache:
    settings = settings or get_settings()
    return TtlLruCache(
        max_size=settings.request_cache_size,
        ttl_seconds=float(settings.request_cache_ttl_seconds),
    )


__all__ = [
    "CacheStats",
    "TtlLruCache",
    "build_cache",
    "canonical_request_json",
    "parser_cache_key",
    "response_cache_key",
]
