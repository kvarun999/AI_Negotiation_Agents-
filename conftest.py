"""
conftest.py
-----------
Root-level pytest configuration.

Responsibilities
----------------
1. Register the --integration CLI option so it is available to all tests
   (pytest hooks in test files are not reliably honoured across all
   collection scenarios).
2. Set the TRADE_POSITIONS_PATH environment variable before any test module
   is imported, ensuring main.py can locate data/trade_positions.json
   regardless of where pytest is invoked from.
3. Provide the `client` fixture using TestClient backed by the FastAPI app
   with the LLM patched out, so it is available project-wide.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Generator, List
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Ensure data/trade_positions.json is resolvable before main.py loads
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).parent
os.environ.setdefault(
    "TRADE_POSITIONS_PATH",
    str(_PROJECT_ROOT / "data" / "trade_positions.json"),
)
# Point the log file to a temp-friendly location during tests
os.environ.setdefault(
    "LOG_FILE_PATH",
    str(_PROJECT_ROOT / "negotiation_log_test.json"),
)
# Use a dummy Ollama URL — real calls are patched in unit tests
os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")


# ---------------------------------------------------------------------------
# Pytest option & marker registration
# ---------------------------------------------------------------------------


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="Run integration tests that require a live Ollama service.",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: marks tests as integration tests (skipped by default).",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: List[pytest.Item]
) -> None:
    if not config.getoption("--integration"):
        skip_integration = pytest.mark.skip(
            reason="Pass --integration to run integration tests."
        )
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip_integration)


# ---------------------------------------------------------------------------
# Shared deterministic fake proposals
# ---------------------------------------------------------------------------

USA_FAKE_PROPOSAL = (
    "The United States proposes a mutual agreement to reduce tariffs on "
    "technology products by 15%, contingent on strengthened IP protection "
    "clauses that enforce intellectual property rights across all sectors. "
    "We are willing to accept reciprocal flexibility and consider compromise "
    "on anti-dumping measures to reach a balanced fair trade outcome."
)

CHINA_FAKE_PROPOSAL = (
    "China accepts the proposal framework and seeks expanded market access "
    "for agricultural products while agreeing to limit excessive restrictions "
    "on technology transfer in a manner that preserves sovereignty. "
    "We are open to cooperation and willing to reduce manufactured tariffs "
    "as a concession toward a mutually beneficial partnership."
)


async def _patched_generate(self: Any, prompt: str) -> str:  # noqa: ARG001
    """Deterministic LLM stub — routes by country to preserve keyword coverage."""
    proposal = (
        USA_FAKE_PROPOSAL if self.country == "usa" else CHINA_FAKE_PROPOSAL
    )
    return f"REASONING: Strategic consideration.\nPROPOSAL: {proposal}"


# ---------------------------------------------------------------------------
# Project-wide `client` fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    """
    FastAPI TestClient with Ollama LLM calls mocked out.
    Available to every test file in the project.
    """
    from agents.negotiator import Negotiator
    from main import app

    with patch.object(Negotiator, "generate_response", new=_patched_generate):
        yield TestClient(app)
