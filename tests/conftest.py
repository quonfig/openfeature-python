"""Shared pytest fixtures for the QuonfigProvider test suite."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from quonfig_openfeature import QuonfigProvider

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def fixtures_dir() -> str:
    return str(FIXTURES_DIR)


@pytest.fixture
def provider(fixtures_dir: str) -> QuonfigProvider:
    """A real QuonfigProvider backed by the test datadir, no network."""
    p = QuonfigProvider(
        sdk_key="test-sdk-key",
        datadir=fixtures_dir,
        environment="Production",
        # The Python SDK only stands up a transport when there's no datadir AND
        # an sdk_key is present, so just having a datadir already keeps it
        # local. Disabling telemetry keeps the tests offline.
        collect_evaluation_summaries=False,
        context_upload_mode="none",
    )
    p.initialize(None)  # type: ignore[arg-type]
    yield p
    p.shutdown()


@pytest.fixture(autouse=True)
def _clear_quonfig_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make sure stray QUONFIG_* env vars don't reach into tests."""
    for var in ("QUONFIG_SDK_KEY", "QUONFIG_DIR", "QUONFIG_ENVIRONMENT", "QUONFIG_API_URLS"):
        if var in os.environ:
            monkeypatch.delenv(var, raising=False)
