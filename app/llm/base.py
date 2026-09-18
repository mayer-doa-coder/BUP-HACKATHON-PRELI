"""Provider-neutral contract for the directive interpreter.

The failure taxonomy here is not decoration: the retry policy (P10) branches on it. A 429 is
not a refusal, a refusal is not malformed output, and a timeout is not a 5xx — each deserves a
different response, and collapsing them into one exception would force the caller to parse
error strings to decide what to do.

Nothing in this module talks to a network. Provider-specific HTTP lives behind the protocol so
that a second provider can be swapped in without touching the interpreter or the optimizer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class InterpreterError(Exception):
    """Base class for every interpretation failure."""

    #: Whether re-issuing the same request could plausibly succeed.
    retryable: bool = False


class ProviderNotConfigured(InterpreterError):
    """No usable provider/model/credential combination is configured."""


class ProviderTimeout(InterpreterError):
    """The provider did not answer within the attempt budget."""

    retryable = True


class ProviderUnavailable(InterpreterError):
    """Connection failure or a provider-side 5xx."""

    retryable = True


class ProviderRateLimited(InterpreterError):
    """Provider returned 429. ``retry_after`` carries the provider's hint when it gives one."""

    retryable = True

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ModelRefusal(InterpreterError):
    """The model declined to answer. Bounded retry or fallback, never a silent default."""

    retryable = True


class ModelTruncated(InterpreterError):
    """Output stopped at the token limit, so the structure is incomplete."""

    retryable = True


class MalformedModelOutput(InterpreterError):
    """Output was not parseable JSON, or not the shape the schema demanded."""

    retryable = True

    def __init__(self, message: str, *, problems: list[str] | None = None) -> None:
        super().__init__(message)
        self.problems = problems or []


@dataclass(frozen=True)
class ProviderResponse:
    """One provider reply, normalized across vendors."""

    #: The structured payload as a JSON string. Providers that return an object serialize it.
    content: str
    #: Exact model identifier the provider reports having used, for telemetry and cache keys.
    model_version: str
    finish_reason: str = ""
    usage: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class StructuredOutputProvider(Protocol):
    """A model endpoint that can be constrained to a JSON schema."""

    name: str
    model: str

    async def complete(
        self,
        *,
        system_prompt: str,
        user_payload: str,
        json_schema: dict[str, Any],
        timeout_s: float,
    ) -> ProviderResponse: ...

    async def aclose(self) -> None: ...


__all__ = [
    "InterpreterError",
    "MalformedModelOutput",
    "ModelRefusal",
    "ModelTruncated",
    "ProviderNotConfigured",
    "ProviderRateLimited",
    "ProviderResponse",
    "ProviderTimeout",
    "ProviderUnavailable",
    "StructuredOutputProvider",
]
