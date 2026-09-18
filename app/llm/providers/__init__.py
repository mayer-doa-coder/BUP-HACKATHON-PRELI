"""Provider selection.

Which vendor is used is a configuration decision, not a code decision. The factory returns
``None`` rather than raising when nothing is configured, so the service can start, answer
``/health``, and serve the deterministic test paths without credentials — a request that
actually needs interpretation then fails closed with a controlled error.
"""

from __future__ import annotations

from app.config import Settings, get_settings
from app.llm.base import ProviderNotConfigured, StructuredOutputProvider
from app.llm.providers.anthropic_provider import AnthropicProvider
from app.llm.providers.openai_provider import OpenAICompatibleProvider

OPENAI_ALIASES = frozenset({"openai", "openai_compatible", "azure_openai", "gateway"})
ANTHROPIC_ALIASES = frozenset({"anthropic", "claude"})


def build_provider(settings: Settings | None = None) -> StructuredOutputProvider | None:
    """Build the primary provider, or ``None`` when it is not configured."""
    settings = settings or get_settings()
    return _build(
        provider_name=settings.llm_provider,
        model=settings.llm_model,
        api_key=settings.llm_api_key.get_secret_value(),
        base_url=settings.llm_base_url,
        settings=settings,
    )


def build_backup_provider(settings: Settings | None = None) -> StructuredOutputProvider | None:
    """Build the pretested backup provider, or ``None`` when none is configured.

    A backup is only useful once it has passed the same semantic corpus as the primary, so this
    stays unconfigured by default rather than silently routing to an unvalidated model.
    """
    settings = settings or get_settings()
    if not settings.backup_llm_provider:
        return None
    return _build(
        provider_name=settings.backup_llm_provider,
        model=settings.backup_llm_model,
        api_key=settings.backup_llm_api_key.get_secret_value(),
        base_url=settings.backup_llm_base_url,
        settings=settings,
    )


def _build(
    *,
    provider_name: str,
    model: str,
    api_key: str,
    base_url: str,
    settings: Settings,
) -> StructuredOutputProvider | None:
    if not model or not api_key:
        return None

    normalized = provider_name.strip().lower()
    common = {
        "api_key": api_key,
        "model": model,
        "max_output_tokens": settings.llm_max_output_tokens,
        "temperature": settings.llm_temperature,
        "name": normalized,
    }

    if normalized in OPENAI_ALIASES:
        from app.llm.providers.openai_provider import DEFAULT_BASE_URL as openai_default

        return OpenAICompatibleProvider(base_url=base_url or openai_default, **common)
    if normalized in ANTHROPIC_ALIASES:
        from app.llm.providers.anthropic_provider import DEFAULT_BASE_URL as anthropic_default

        return AnthropicProvider(base_url=base_url or anthropic_default, **common)

    raise ProviderNotConfigured(f"unsupported LLM_PROVIDER: {provider_name!r}")


__all__ = [
    "ANTHROPIC_ALIASES",
    "OPENAI_ALIASES",
    "AnthropicProvider",
    "OpenAICompatibleProvider",
    "build_backup_provider",
    "build_provider",
]
