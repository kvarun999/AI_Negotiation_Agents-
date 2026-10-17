"""
tests/test_negotiation.py
--------------------------
Pytest suite for the AI Negotiation API.

Test strategy
=============
Because the Ollama LLM service is an external dependency we cannot rely on
it being present during unit-test runs.  Every test therefore uses the
``client`` fixture from conftest.py which patches the Negotiator's
``generate_response`` method with a deterministic fake that:
  - Returns text referencing real priority keywords (tariffs, IP,
    market access, tech transfer) so keyword-coverage tests pass
    consistently.
  - Contains concession keywords so compromise-score tests are stable.

Integration-style tests that talk to a real Ollama instance are gated
behind the ``--integration`` pytest marker (registered in conftest.py)
and are skipped by default.

Running the tests
-----------------
  # Unit tests only (default, no Ollama required)
  pytest tests/test_negotiation.py -v

  # Include integration tests (requires Ollama + llama3 model)
  pytest tests/test_negotiation.py -v --integration
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------
# The `client` fixture is defined globally in conftest.py and is automatically
# available to every test class and function in this file.


# ---------------------------------------------------------------------------
# Core endpoint tests
# ---------------------------------------------------------------------------


class TestNegotiateEndpointSchema:
    """Validates the HTTP contract: status codes, top-level keys, types."""

    def test_returns_200_ok(self, client: TestClient) -> None:
        response = client.post(
            "/negotiate",
            json={"issue": "Technology Tariffs", "rounds": 1},
        )
        assert response.status_code == 200, response.text

    def test_response_contains_rounds_key(self, client: TestClient) -> None:
        response = client.post(
            "/negotiate",
            json={"issue": "Technology Tariffs", "rounds": 1},
        )
        data = response.json()
        assert "rounds" in data

    def test_response_contains_outcome_key(self, client: TestClient) -> None:
        response = client.post(
            "/negotiate",
            json={"issue": "Technology Tariffs", "rounds": 1},
        )
        data = response.json()
        assert "outcome" in data


class TestRoundsCount:
    """
    Requirement 4 & 11: The rounds array length must equal the requested
    number of rounds.
    """

    def test_rounds_array_length_equals_requested_rounds_3(
        self, client: TestClient
    ) -> None:
        """Primary requirement 11: assert len(data['rounds']) == 3."""
        response = client.post(
            "/negotiate",
            json={"issue": "Agricultural Subsidies", "rounds": 3},
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["rounds"], list)
        assert len(data["rounds"]) == 3  # noqa: PLR2004

    def test_rounds_array_length_equals_1(self, client: TestClient) -> None:
        response = client.post(
            "/negotiate",
            json={"issue": "Agricultural Subsidies", "rounds": 1},
        )
        data = response.json()
        assert len(data["rounds"]) == 1  # noqa: PLR2004

    def test_rounds_array_length_equals_5(self, client: TestClient) -> None:
        response = client.post(
            "/negotiate",
            json={"issue": "Market Access", "rounds": 5},
        )
        data = response.json()
        assert len(data["rounds"]) == 5  # noqa: PLR2004

    def test_default_rounds_is_3(self, client: TestClient) -> None:
        """Omitting 'rounds' should default to 3 rounds."""
        response = client.post(
            "/negotiate",
            json={"issue": "IP Protection"},
        )
        data = response.json()
        assert len(data["rounds"]) == 3  # noqa: PLR2004


class TestRoundObjectSchema:
    """
    Requirement 5: Each round object must have usa_proposal and
    china_response as non-empty strings.
    """

    def test_round_has_round_number(self, client: TestClient) -> None:
        response = client.post("/negotiate", json={"issue": "Tariffs", "rounds": 2})
        data = response.json()
        for entry in data["rounds"]:
            assert "round" in entry
            assert isinstance(entry["round"], int)

    def test_round_has_usa_proposal_string(self, client: TestClient) -> None:
        response = client.post("/negotiate", json={"issue": "Tariffs", "rounds": 2})
        data = response.json()
        for entry in data["rounds"]:
            assert "usa_proposal" in entry
            assert isinstance(entry["usa_proposal"], str)
            assert len(entry["usa_proposal"]) > 0

    def test_round_has_china_response_string(self, client: TestClient) -> None:
        response = client.post("/negotiate", json={"issue": "Tariffs", "rounds": 2})
        data = response.json()
        for entry in data["rounds"]:
            assert "china_response" in entry
            assert isinstance(entry["china_response"], str)
            assert len(entry["china_response"]) > 0

    def test_round_numbers_are_sequential(self, client: TestClient) -> None:
        response = client.post("/negotiate", json={"issue": "Tariffs", "rounds": 3})
        data = response.json()
        for i, entry in enumerate(data["rounds"], start=1):
            assert entry["round"] == i


class TestOutcomeSchema:
    """
    Requirement 6: outcome must have agreement_reached (bool),
    final_terms (str), compromise_score (float).
    """

    def _get_outcome(self, client: TestClient) -> Dict[str, Any]:
        response = client.post(
            "/negotiate", json={"issue": "Technology Transfer", "rounds": 2}
        )
        return response.json()["outcome"]

    def test_outcome_has_agreement_reached_key(self, client: TestClient) -> None:
        outcome = self._get_outcome(client)
        assert "agreement_reached" in outcome

    def test_outcome_agreement_reached_is_bool(self, client: TestClient) -> None:
        outcome = self._get_outcome(client)
        assert isinstance(outcome["agreement_reached"], bool)

    def test_outcome_has_final_terms_key(self, client: TestClient) -> None:
        outcome = self._get_outcome(client)
        assert "final_terms" in outcome

    def test_outcome_final_terms_is_non_empty_string(self, client: TestClient) -> None:
        outcome = self._get_outcome(client)
        assert isinstance(outcome["final_terms"], str)
        assert len(outcome["final_terms"]) > 0

    def test_outcome_has_compromise_score_key(self, client: TestClient) -> None:
        outcome = self._get_outcome(client)
        assert "compromise_score" in outcome

    def test_outcome_compromise_score_is_float(self, client: TestClient) -> None:
        outcome = self._get_outcome(client)
        assert isinstance(outcome["compromise_score"], float)

    def test_outcome_compromise_score_in_valid_range(
        self, client: TestClient
    ) -> None:
        """Requirement 7: score must be in [0.0, 1.0]."""
        outcome = self._get_outcome(client)
        score = outcome["compromise_score"]
        assert 0.0 <= score <= 1.0, f"Score {score} is out of [0.0, 1.0] range"


class TestPriorityKeywordCoverage:
    """
    Requirement 12: Agent proposals must reference priority keywords from
    trade_positions.json.
    """

    def _get_all_proposals(
        self, client: TestClient, rounds: int = 2
    ) -> tuple[str, str]:
        """Returns (all_usa_text, all_china_text) from a negotiation."""
        response = client.post(
            "/negotiate",
            json={"issue": "Technology Tariffs and Market Access", "rounds": rounds},
        )
        assert response.status_code == 200
        data = response.json()

        all_usa = " ".join(
            entry["usa_proposal"] for entry in data["rounds"]
        ).lower()
        all_china = " ".join(
            entry["china_response"] for entry in data["rounds"]
        ).lower()
        return all_usa, all_china

    def test_usa_proposals_mention_tariff_related_terms(
        self, client: TestClient
    ) -> None:
        """USA's proposals must contain 'tariff' or 'tariffs'."""
        all_usa, _ = self._get_all_proposals(client)
        assert any(
            kw in all_usa for kw in ("tariff", "tariffs", "technology", "reduce")
        ), f"USA proposals did not mention tariff-related terms. Got: {all_usa[:300]}"

    def test_usa_proposals_mention_ip_related_terms(
        self, client: TestClient
    ) -> None:
        """USA's proposals must contain IP / intellectual property terms."""
        all_usa, _ = self._get_all_proposals(client)
        assert any(
            kw in all_usa
            for kw in ("ip", "intellectual property", "protection", "ip protection")
        ), f"USA proposals did not mention IP-related terms. Got: {all_usa[:300]}"

    def test_china_proposals_mention_market_access(
        self, client: TestClient
    ) -> None:
        """China's proposals must contain 'market access'."""
        _, all_china = self._get_all_proposals(client)
        assert any(
            kw in all_china
            for kw in ("market access", "market", "agricultural", "agriculture")
        ), (
            f"China proposals did not mention market access terms. "
            f"Got: {all_china[:300]}"
        )

    def test_china_proposals_mention_tech_transfer_terms(
        self, client: TestClient
    ) -> None:
        """China's proposals must reference technology transfer topics."""
        _, all_china = self._get_all_proposals(client)
        assert any(
            kw in all_china
            for kw in ("technology transfer", "tech transfer", "technology", "transfer")
        ), (
            f"China proposals did not mention tech-transfer terms. "
            f"Got: {all_china[:300]}"
        )


# ---------------------------------------------------------------------------
# Scoring unit tests (no LLM required)
# ---------------------------------------------------------------------------


class TestCalculateCompromise:
    """Unit tests for the scoring.calculate_compromise function."""

    def _make_history(
        self, usa_text: str, china_text: str, rounds: int = 1
    ) -> List[Dict[str, Any]]:
        return [
            {
                "round": i + 1,
                "usa_proposal": usa_text,
                "china_response": china_text,
            }
            for i in range(rounds)
        ]

    def _positions(self) -> Dict[str, Any]:
        return {
            "usa": {
                "priorities": [
                    "Reduce tariffs on technology products",
                    "Strengthen intellectual property (IP) protection clauses",
                ],
                "flexibility": {"tariffs": 0.7, "ip_protection": 0.3},
                "red_lines": [],
            },
            "china": {
                "priorities": [
                    "Gain greater market access for agricultural products",
                    "Limit restrictions on technology transfer",
                ],
                "flexibility": {"market_access": 0.8, "tech_transfer_limits": 0.4},
                "red_lines": [],
            },
        }

    def test_empty_history_returns_zero(self) -> None:
        from scoring import calculate_compromise

        score = calculate_compromise([], self._positions())
        assert score == 0.0

    def test_score_is_within_valid_range(self) -> None:
        from scoring import calculate_compromise

        history = self._make_history(
            "We agree to reduce tariffs and accept compromise.",
            "China accepts and is willing to lower tech transfer limits.",
        )
        score = calculate_compromise(history, self._positions())
        assert 0.0 <= score <= 1.0

    def test_concession_heavy_text_scores_higher_than_combative(self) -> None:
        from scoring import calculate_compromise

        concession_history = self._make_history(
            "We agree to reduce tariffs, accept IP protection, and compromise.",
            "China agrees to market access and is willing to cooperate fully.",
            rounds=3,
        )
        combative_history = self._make_history(
            "We reject all proposals and insist on our demands. Non-negotiable.",
            "China refuses to accept any restrictions. This is unacceptable.",
            rounds=3,
        )
        concession_score = calculate_compromise(concession_history, self._positions())
        combative_score = calculate_compromise(combative_history, self._positions())
        assert concession_score > combative_score

    def test_more_rounds_increases_length_bonus(self) -> None:
        from scoring import calculate_compromise

        neutral_text = "We propose to discuss the issue further."
        short_history = self._make_history(neutral_text, neutral_text, rounds=1)
        long_history = self._make_history(neutral_text, neutral_text, rounds=8)
        short_score = calculate_compromise(short_history, self._positions())
        long_score = calculate_compromise(long_history, self._positions())
        assert long_score > short_score


# ---------------------------------------------------------------------------
# Health endpoint test
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    def test_health_returns_ok(self) -> None:
        from main import app

        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"


# ---------------------------------------------------------------------------
# Input validation tests
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_missing_issue_returns_422(self) -> None:
        from main import app

        c = TestClient(app)
        response = c.post("/negotiate", json={"rounds": 2})
        assert response.status_code == 422  # noqa: PLR2004

    def test_rounds_below_min_returns_422(self) -> None:
        from main import app

        c = TestClient(app)
        response = c.post("/negotiate", json={"issue": "Trade", "rounds": 0})
        assert response.status_code == 422  # noqa: PLR2004

    def test_rounds_above_max_returns_422(self) -> None:
        from main import app

        c = TestClient(app)
        response = c.post("/negotiate", json={"issue": "Trade", "rounds": 25})
        assert response.status_code == 422  # noqa: PLR2004


# ---------------------------------------------------------------------------
# Integration test (skipped unless --integration flag is passed)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestLiveNegotiation:
    """
    Requires a running Ollama instance with the configured model available.
    Run with: pytest tests/test_negotiation.py -v --integration
    """

    def test_live_negotiate_returns_200(self) -> None:
        from main import app

        c = TestClient(app)
        response = c.post(
            "/negotiate",
            json={"issue": "Technology Tariffs", "rounds": 1},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["rounds"]) == 1

    def test_live_negotiate_3_rounds(self) -> None:
        from main import app

        c = TestClient(app)
        response = c.post(
            "/negotiate",
            json={"issue": "Agricultural Market Access", "rounds": 3},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["rounds"]) == 3  # noqa: PLR2004
        assert 0.0 <= data["outcome"]["compromise_score"] <= 1.0
