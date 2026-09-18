"""Anthropic structured-output adapter.

Constrains output by declaring a single tool whose ``input_schema`` is the directive schema and
forcing that tool, so the model answers with a validated object rather than prose that has to be
scraped. The tool is never executed — it exists purely as a typed output channel, which keeps
the model's least-privilege position intact (no tools, no browsing, no file access).

Errors are translated into the same taxonomy the OpenAI adapter uses, so the interpreter and
the retry policy stay provider-neutral.
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

DEFAULT_BASE_URL = "https://api.anthropic.com"
API_VERSION = "2023-06-01"
TOOL_NAME = "emit_directive_interpretation"


class AnthropicProvider:
    """Structured-output provider speaking the Anthropic Messages dialect."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        max_output_tokens: int = 2048,
        temperature: float | None = 0.0,
        name: str = "anthropic",
    ) -> None:
        self.name = name
        self.model = model
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature
        self._client: httpx.AsyncClient | None = None

    def _http(self) -> httpx.AsyncClient:
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
            "max_tokens": self._max_output_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_payload}],
            "tools": [
                {
                    "name": TOOL_NAME,
                    "description": "Return one directive interpretation per operator note.",
                    "input_schema": json_schema,
                }
            ],
            "tool_choice": {"type": "tool", "name": TOOL_NAME},
        }
        if self._temperature is not None:
            body["temperature"] = self._temperature

        try:
            response = await self._http().post(
                "/v1/messages",
                json=body,
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": API_VERSION,
                    "content-type": "application/json",
                },
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
        raise ProviderUnavailable(f"{provider} rejected the request with {response.status_code}")


def _parse_body(response: httpx.Response, provider: str, model: str) -> ProviderResponse:
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise MalformedModelOutput(f"{provider} returned a non-JSON body") from exc

    stop_reason = str(payload.get("stop_reason") or "")
    if stop_reason == "max_tokens":
        raise ModelTruncated(f"{provider} hit the output token limit")

    for block in payload.get("content") or []:
        if block.get("type") == "tool_use" and block.get("name") == TOOL_NAME:
            tool_input = block.get("input")
            if not isinstance(tool_input, dict):
                raise MalformedModelOutput(f"{provider} tool input was not an object")
            return ProviderResponse(
                content=json.dumps(tool_input),
                model_version=str(payload.get("model") or model),
                finish_reason=stop_reason,
                usage=payload.get("usage") or {},
            )

    # The model answered in prose instead of using the forced tool, which in practice means it
    # declined. Treated as a refusal so the retry policy can respond, not as malformed output.
    raise ModelRefusal(f"{provider} did not produce the structured tool call")


def _is_number(value: str | None) -> bool:
    if value is None:
        return False
    try:
        float(value)
    except ValueError:
        return False
    return True


__all__ = ["API_VERSION", "DEFAULT_BASE_URL", "TOOL_NAME", "AnthropicProvider"]
