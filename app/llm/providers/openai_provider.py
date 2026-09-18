"""OpenAI-compatible structured-output adapter.

Targets the Chat Completions shape with ``response_format={"type": "json_schema"}``, which is
also what most OpenAI-compatible gateways implement, so a different base URL is usually the
only change needed to point this at another host.

HTTP status and body are translated into the failure taxonomy from ``app.llm.base`` — the whole
point of this layer is that the interpreter never sees a vendor-shaped error.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.llm.base import (
    MalformedModelOutput,
    ModelRefusal,
    ModelTruncated,
    ProviderRateLimited,
    ProviderResponse,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.llm.schema import SCHEMA_NAME

DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAICompatibleProvider:
    """Structured-output provider speaking the OpenAI Chat Completions dialect."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        max_output_tokens: int = 2048,
        temperature: float | None = 0.0,
        name: str = "openai",
    ) -> None:
        self.name = name
        self.model = model
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature
        self._client: httpx.AsyncClient | None = None

    def _http(self) -> httpx.AsyncClient:
        # One pooled client per provider instance: reconnecting per request would add a TLS
        # handshake to the critical path of every judged call.
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self._base_url)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def complete(
        self,
        *,
        system_prompt: str,
        user_payload: str,
        json_schema: dict[str, Any],
        timeout_s: float,
    ) -> ProviderResponse:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_payload},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": SCHEMA_NAME, "strict": True, "schema": json_schema},
            },
            "max_completion_tokens": self._max_output_tokens,
        }
        if self._temperature is not None:
            body["temperature"] = self._temperature

        try:
            response = await self._http().post(
                "/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=timeout_s,
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(f"{self.name} timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"{self.name} transport error: {type(exc).__name__}") from exc

        _raise_for_status(response, self.name)
        return _parse_body(response, self.name, self.model)


def _raise_for_status(response: httpx.Response, provider: str) -> None:
    if response.status_code == 429:
        retry_after = response.headers.get("retry-after")
        raise ProviderRateLimited(
            f"{provider} rate limited",
            retry_after=float(retry_after) if _is_number(retry_after) else None,
        )
    if response.status_code >= 500:
        raise ProviderUnavailable(f"{provider} returned {response.status_code}")
    if response.status_code >= 400:
        # 400/401/403/404 are configuration faults: retrying the same call cannot fix them, and
        # without a reason they are very hard to diagnose. The provider's error *metadata*
        # (type, code, offending parameter) is safe to surface — it describes the request shape,
        # not its content — so it is attached here. It reaches operators and the canary; API
        # clients still see only a sanitized 500, because 500s never expose details.
        raise ProviderUnavailable(
            f"{provider} rejected the request with {response.status_code}: {_error_hint(response)}"
        )


#: Cap on the provider's own error text, so a verbose body cannot flood a log line.
ERROR_HINT_CHARS = 300


def _error_hint(response: httpx.Response) -> str:
    """Safe, useful summary of a provider error body.

    ``type``, ``code`` and ``param`` describe the *shape* of the request that was rejected —
    an unsupported parameter, an unknown model — and carry no scenario content. The message is
    included, truncated, because it is what actually names the problem.
    """
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError):
        return "unparseable error body"

    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return "no error detail"

    parts = [
        f"{key}={error[key]}"
        for key in ("type", "code", "param")
        if error.get(key)
    ]
    message = str(error.get("message") or "")[:ERROR_HINT_CHARS]
    if message:
        parts.append(f"message={message}")
    return "; ".join(parts) or "no error detail"


def _parse_body(response: httpx.Response, provider: str, model: str) -> ProviderResponse:
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise MalformedModelOutput(f"{provider} returned a non-JSON body") from exc

    choices = payload.get("choices") or []
    if not choices:
        raise MalformedModelOutput(f"{provider} returned no choices")

    choice = choices[0]
    message = choice.get("message") or {}
    finish_reason = str(choice.get("finish_reason") or "")

    if message.get("refusal"):
        raise ModelRefusal(f"{provider} refused the request")
    if finish_reason == "length":
        raise ModelTruncated(f"{provider} hit the output token limit")

    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise MalformedModelOutput(f"{provider} returned empty content")

    return ProviderResponse(
        content=content,
        model_version=str(payload.get("model") or model),
        finish_reason=finish_reason,
        usage=payload.get("usage") or {},
    )


def _is_number(value: str | None) -> bool:
    if value is None:
        return False
    try:
        float(value)
    except ValueError:
        return False
    return True


__all__ = ["DEFAULT_BASE_URL", "OpenAICompatibleProvider"]
