"""The directive interpreter: one structured-output call for all of a scenario's notes.

This is the only place in the service where a language model influences anything, and its
influence is narrow by construction: it returns typed directives, and every kWh in the response
is computed afterwards by the optimizer from those directives (D-03).

One call handles all 1-3 notes (D-04). Splitting them would triple latency and cost for no
semantic benefit, since the notes describe the same scenario and are interpreted independently
anyway.

What comes back is **untrusted data**. This module parses it and checks nothing semantic; the
deterministic guardrails (P9) decide whether it may become a constraint.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import TypeAdapter, ValidationError

from app.config import Settings, get_settings
from app.llm.base import (
    MalformedModelOutput,
    ProviderNotConfigured,
    StructuredOutputProvider,
)
from app.llm.prompts import build_system_prompt, build_user_payload
from app.llm.schema import build_interpretation_schema
from app.schemas.directive import DirectiveInterpretation
from app.schemas.request import OptimizeRequest

_DIRECTIVE_LIST_ADAPTER: TypeAdapter[list[DirectiveInterpretation]] = TypeAdapter(
    list[DirectiveInterpretation]
)

ENVELOPE_KEY = "directive_interpretation"


@dataclass(frozen=True)
class InterpretationOutcome:
    """Raw model output plus the telemetry the observability and cache layers need."""

    raw_items: list[dict[str, Any]]
    provider: str
    model_version: str
    latency_ms: float
    finish_reason: str = ""
    usage: dict[str, Any] = field(default_factory=dict)


class LlmDirectiveInterpreter:
    """Turns operator notes into raw structured directives using one provider call."""

    def __init__(
        self,
        provider: StructuredOutputProvider,
        settings: Settings | None = None,
    ) -> None:
        self._provider = provider
        self._settings = settings or get_settings()

    @property
    def provider_name(self) -> str:
        return self._provider.name

    async def interpret(
        self,
        request: OptimizeRequest,
        *,
        timeout_s: float | None = None,
    ) -> InterpretationOutcome:
        """Issue one structured-output call and parse the envelope. No semantic checks here."""
        note_count = len(request.operator_notes)
        started = time.perf_counter()

        response = await self._provider.complete(
            system_prompt=build_system_prompt(self._settings),
            user_payload=build_user_payload(request),
            json_schema=build_interpretation_schema(note_count),
            timeout_s=timeout_s if timeout_s is not None else self._settings.llm_attempt_timeout_seconds,
        )
        latency_ms = (time.perf_counter() - started) * 1000.0

        return InterpretationOutcome(
            raw_items=parse_envelope(response.content),
            provider=self._provider.name,
            model_version=response.model_version,
            latency_ms=latency_ms,
            finish_reason=response.finish_reason,
            usage=response.usage,
        )

    async def aclose(self) -> None:
        await self._provider.aclose()


def parse_envelope(content: str) -> list[dict[str, Any]]:
    """Pull the interpretation list out of the model's JSON envelope.

    Only structural unwrapping happens here. Whether an entry is *correct* — the right type, the
    right hours, a reserve within capacity — is deliberately not this function's business.
    """
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise MalformedModelOutput(
            "model output was not valid JSON", problems=[f"json decode error at position {exc.pos}"]
        ) from exc

    if not isinstance(payload, dict):
        raise MalformedModelOutput("model output was not a JSON object")

    items = payload.get(ENVELOPE_KEY)
    if not isinstance(items, list):
        raise MalformedModelOutput(f"model output has no {ENVELOPE_KEY!r} array")
    if not all(isinstance(item, dict) for item in items):
        raise MalformedModelOutput(f"every {ENVELOPE_KEY} entry must be an object")

    return items


def coerce_to_canonical(raw_items: list[dict[str, Any]]) -> list[DirectiveInterpretation]:
    """Strictly validate raw items into canonical directives.

    This is the *shape* gate only: the discriminated union rejects an unknown type, a ``no_op``
    carrying an adjustment, a factor outside [0, 1], or unsorted hours.

    P9 replaces this with the full guardrail module, which additionally classifies each failure
    (so a duplicate hour routes to the bounded repair path rather than a generic rejection) and
    checks scenario-dependent rules such as reserve-vs-capacity. Until then a violation simply
    fails closed.
    """
    try:
        return _DIRECTIVE_LIST_ADAPTER.validate_python(raw_items)
    except ValidationError as exc:
        problems = [
            f"{'.'.join(str(part) for part in error.get('loc', ()))}: {error.get('msg', '')}"
            for error in exc.errors()[:5]
        ]
        raise MalformedModelOutput(
            "model output did not match the directive schema", problems=problems
        ) from exc


def build_interpreter(settings: Settings | None = None) -> LlmDirectiveInterpreter | None:
    """Build the interpreter from configuration, or ``None`` when no provider is configured."""
    from app.llm.providers import build_provider

    settings = settings or get_settings()
    try:
        provider = build_provider(settings)
    except ProviderNotConfigured:
        return None
    if provider is None:
        return None
    return LlmDirectiveInterpreter(provider, settings)


__all__ = [
    "ENVELOPE_KEY",
    "InterpretationOutcome",
    "LlmDirectiveInterpreter",
    "build_interpreter",
    "coerce_to_canonical",
    "parse_envelope",
]
