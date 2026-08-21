"""Shared fixtures.

No test in this suite calls OpenAI. Real-model behaviour is exercised separately
by ``scripts/demo_run.py`` so the suite stays fast, free and deterministic.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.domain.supplier import Supplier
from app.main import create_app

BACKEND_ROOT = Path(__file__).resolve().parent.parent

# Fixed "today" so deadline scoring is reproducible regardless of when tests run.
TODAY = date(2026, 8, 21)
DEMO_DEADLINE = date(2026, 9, 15)


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


@pytest.fixture(scope="session")
def suppliers() -> tuple[Supplier, ...]:
    """The real dataset, validated. Matching tests run against production data."""
    raw = json.loads((BACKEND_ROOT / "data" / "suppliers.json").read_text(encoding="utf-8"))
    return tuple(Supplier.model_validate(item) for item in raw["suppliers"])


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client
