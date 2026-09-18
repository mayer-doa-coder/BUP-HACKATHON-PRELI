"""Shared fixtures.

Test data comes from the JSON packs in ``docs/`` rather than being retyped here, so a
fixture can never drift from the case it claims to represent.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------------------
# Keep the suite hermetic and free.
#
# A developer's local ``.env`` carries real credentials, and without this the default service
# would build a live interpreter: tests would make billable provider calls, and results would
# depend on whose machine they ran on. Cleared here, at import time, before any test module
# imports the app (``app.api.routes`` builds a service at module scope).
#
# The opt-in live checks re-enable it explicitly:
#     GRIDWISE_TEST_ALLOW_LIVE=1 pytest -m live
# ---------------------------------------------------------------------------------------
if os.environ.get("GRIDWISE_TEST_ALLOW_LIVE") != "1":
    os.environ["LLM_MODEL"] = ""
    os.environ["LLM_API_KEY"] = ""
    os.environ["BACKUP_LLM_PROVIDER"] = ""
    os.environ["BACKUP_LLM_MODEL"] = ""
    os.environ["BACKUP_LLM_API_KEY"] = ""

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = REPO_ROOT / "docs"
PUBLIC_CASES = REPO_ROOT / "public_cases" / "sample_cases.json"
ADVERSARIAL_PACK = DOCS_DIR / "GridWise_Adversarial_Edge_Cases.json"
EXTENDED_PACK = DOCS_DIR / "GridWise_Extended_HiddenLike_Cases.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def public_cases() -> list[dict[str, Any]]:
    """The 10 organizer public sample cases."""
    return _load(PUBLIC_CASES)["cases"]


@pytest.fixture(scope="session")
def adversarial_pack() -> dict[str, Any]:
    """Unofficial synthetic robustness corpus (invalid requests, guardrail outputs, ...)."""
    return _load(ADVERSARIAL_PACK)


@pytest.fixture(scope="session")
def extended_cases() -> list[dict[str, Any]]:
    """Unofficial synthetic hidden-like scenarios with expected interpretation output."""
    return _load(EXTENDED_PACK)["cases"]


@pytest.fixture(scope="session")
def valid_request(public_cases: list[dict[str, Any]]) -> dict[str, Any]:
    """A known-good request body, used as the baseline for mutation tests."""
    return public_cases[0]["input"]


@pytest.fixture
def client() -> TestClient:
    from app.main import create_app

    # raise_server_exceptions=False so the registered 500 handler is exercised instead of the
    # exception propagating into the test as a Python error.
    return TestClient(create_app(), raise_server_exceptions=False)
