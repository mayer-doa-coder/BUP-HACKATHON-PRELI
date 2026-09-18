"""Smoke checks for configuration loading.

Kept deliberately small: it only guards the two things that silently break the whole
service if they regress — env overrides being read at all, and secrets not leaking
through ``repr``/``str``.
"""

from app.config import Settings


def test_env_overrides_are_applied(monkeypatch):
    monkeypatch.setenv("PORT", "9001")
    monkeypatch.setenv("SOLAR_OVERLAP_POLICY", "multiply")
    settings = Settings(_env_file=None)

    assert settings.port == 9001
    assert settings.solar_overlap_policy == "multiply"


def test_api_key_is_not_printable(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "super-secret-value")
    settings = Settings(_env_file=None)

    assert "super-secret-value" not in repr(settings)
    assert "super-secret-value" not in str(settings)
    assert settings.llm_api_key.get_secret_value() == "super-secret-value"
