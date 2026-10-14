"""
main.py
-------
FastAPI application entry point.

Responsibilities:
  - Load trade positions from data/trade_positions.json at startup.
  - Instantiate and hold Negotiator agents for both countries.
  - Expose POST /negotiate to orchestrate multi-round agent dialogue.
  - Persist every completed negotiation to negotiation_log.json.
  - Expose GET /health for container health-checks.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from agents.negotiator import Negotiator
from scoring import calculate_compromise

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration — read exclusively from environment variables (no hardcodes)
# ---------------------------------------------------------------------------
OLLAMA_BASE_URL: str = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434")
OLLAMA_MODEL: str = os.environ.get("OLLAMA_MODEL", "llama3")
LLM_TEMPERATURE: float = float(os.environ.get("LLM_TEMPERATURE", "0.3"))
OLLAMA_TIMEOUT: float = float(os.environ.get("OLLAMA_TIMEOUT", "120"))
AGREEMENT_THRESHOLD: float = float(os.environ.get("AGREEMENT_THRESHOLD", "0.5"))
LOG_FILE_PATH: Path = Path(os.environ.get("LOG_FILE_PATH", "/app/logs/negotiation_log.json"))
TRADE_POSITIONS_PATH: Path = Path(
    os.environ.get("TRADE_POSITIONS_PATH", "data/trade_positions.json")
)

# ---------------------------------------------------------------------------
# Load trade positions — executed once at module import time
# ---------------------------------------------------------------------------

def _load_positions(path: Path) -> Dict[str, Any]:
    """
    Loads and validates the trade positions data file.

    Parameters
    ----------
    path : Path
        Filesystem path to trade_positions.json.

    Returns
    -------
    dict
        The parsed JSON object.

    Raises
    ------
    RuntimeError
        If the file cannot be found or parsed.
    """
    if not path.exists():
        raise RuntimeError(
            f"Trade positions file not found at '{path}'. "
            "Ensure the ./data volume mount is configured correctly."
        )
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Failed to parse trade positions file '{path}': {exc}"
        ) from exc

    for country in ("usa", "china"):
        if country not in data:
            raise RuntimeError(
                f"Trade positions file is missing the '{country}' key."
            )
    return data


positions: Dict[str, Any] = _load_positions(TRADE_POSITIONS_PATH)
logger.info("Trade positions loaded from '%s'.", TRADE_POSITIONS_PATH)

# ---------------------------------------------------------------------------
# Initialise agents
# ---------------------------------------------------------------------------

usa_agent = Negotiator(
    country="usa",
    positions=positions["usa"],
    ollama_url=OLLAMA_BASE_URL,
    model=OLLAMA_MODEL,
    temperature=LLM_TEMPERATURE,
    timeout=OLLAMA_TIMEOUT,
)

china_agent = Negotiator(
    country="china",
    positions=positions["china"],
    ollama_url=OLLAMA_BASE_URL,
    model=OLLAMA_MODEL,
    temperature=LLM_TEMPERATURE,
    timeout=OLLAMA_TIMEOUT,
)

logger.info(
    "Negotiator agents initialised (model=%s, ollama_url=%s).",
    OLLAMA_MODEL,
    OLLAMA_BASE_URL,
)

# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="AI Trade Negotiation API",
    description=(
        "Multi-agent system where USA and China AI agents negotiate a "
        "bilateral trade agreement over configurable rounds."
    ),
    version="1.0.0",
)

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class NegotiateRequest(BaseModel):
    """Request body for POST /negotiate."""

    issue: str = Field(
        ...,
        min_length=3,
        max_length=512,
        description="The trade topic or issue under negotiation.",
        examples=["Technology Tariffs"],
    )
    rounds: int = Field(
        default=3,
        ge=1,
        le=20,
        description="Number of negotiation rounds to simulate.",
    )


class RoundResult(BaseModel):
    """Represents a single round of the negotiation."""

    round: int
    usa_proposal: str
    china_response: str


class OutcomeResult(BaseModel):
    """Summary of the negotiation outcome."""

    agreement_reached: bool
    final_terms: str
    compromise_score: float


class NegotiateResponse(BaseModel):
    """Top-level response for POST /negotiate."""

    rounds: List[RoundResult]
    outcome: OutcomeResult


# ---------------------------------------------------------------------------
# State persistence helpers
# ---------------------------------------------------------------------------


def _append_log_entry(entry: Dict[str, Any]) -> None:
    """
    Appends a single negotiation log entry to LOG_FILE_PATH.

    The file stores a JSON array.  If the file does not exist, it is created.
    Errors are logged but do not propagate — a logging failure must never
    abort the API response.
    """
    try:
        existing: List[Dict[str, Any]] = []
        if LOG_FILE_PATH.exists():
            try:
                with LOG_FILE_PATH.open("r", encoding="utf-8") as fh:
                    content = fh.read().strip()
                    if content:
                        existing = json.loads(content)
                        if not isinstance(existing, list):
                            existing = [existing]
            except (json.JSONDecodeError, ValueError):
                logger.warning(
                    "Existing log file '%s' is malformed; starting fresh.",
                    LOG_FILE_PATH,
                )
                existing = []

        existing.append(entry)

        # Ensure parent directory exists (e.g. /app/logs)
        LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)

        with LOG_FILE_PATH.open("w", encoding="utf-8") as fh:
            json.dump(existing, fh, indent=2, ensure_ascii=False)

        logger.info("Negotiation log updated (%d entries).", len(existing))
    except OSError as exc:
        logger.error("Failed to write negotiation log: %s", exc)


def _derive_final_terms(history: List[Dict[str, Any]], issue: str) -> str:
    """
    Constructs a human-readable summary of the final terms by combining
    the last proposals from both agents.
    """
    if not history:
        return f"No terms reached on: {issue}"

    last = history[-1]
    usa_last = last.get("usa_proposal", "")
    china_last = last.get("china_response", "")

    if usa_last and china_last:
        return (
            f"After {len(history)} round(s) on '{issue}': "
            f"USA final position — {usa_last[:200]}. "
            f"China final position — {china_last[:200]}."
        )
    return f"Negotiation concluded on '{issue}' after {len(history)} round(s)."


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health", tags=["Meta"])
async def health_check() -> Dict[str, str]:
    """Lightweight health-check endpoint for Docker / load-balancer probes."""
    return {"status": "ok", "service": "AI Trade Negotiation API"}


@app.post("/negotiate", response_model=NegotiateResponse, tags=["Negotiation"])
async def negotiate(request: NegotiateRequest) -> NegotiateResponse:
    """
    Orchestrates a multi-round AI negotiation between USA and China agents.

    For each round:
      1. The USA agent generates a proposal based on current history.
      2. The China agent generates a response based on history + USA proposal.
      3. The round result is appended to the history.

    After all rounds the compromise score is calculated, an outcome is
    derived, and the full log entry is persisted to disk.

    Returns the complete rounds array and outcome object.
    """
    logger.info(
        "Negotiation started | issue='%s' | rounds=%d",
        request.issue,
        request.rounds,
    )

    history: List[Dict[str, Any]] = []

    for round_number in range(1, request.rounds + 1):
        logger.info("--- Round %d / %d ---", round_number, request.rounds)

        # USA generates its proposal
        try:
            usa_proposal = await usa_agent.make_proposal(request.issue, history)
        except RuntimeError as exc:
            logger.error("USA agent failed on round %d: %s", round_number, exc)
            raise HTTPException(
                status_code=502,
                detail=(
                    f"USA agent failed to generate a proposal on round {round_number}: "
                    f"{exc}"
                ),
            ) from exc

        # Build a partial history entry so China sees USA's latest move
        partial_entry: Dict[str, Any] = {
            "round": round_number,
            "usa_proposal": usa_proposal,
            "china_response": "",
        }
        history.append(partial_entry)

        # China generates its response
        try:
            china_response = await china_agent.make_proposal(request.issue, history)
        except RuntimeError as exc:
            logger.error("China agent failed on round %d: %s", round_number, exc)
            raise HTTPException(
                status_code=502,
                detail=(
                    f"China agent failed to generate a response on round {round_number}: "
                    f"{exc}"
                ),
            ) from exc

        # Update the history entry with China's response
        partial_entry["china_response"] = china_response

        logger.info("Round %d complete.", round_number)

    # ------------------------------------------------------------------
    # Scoring and outcome determination
    # ------------------------------------------------------------------
    compromise_score: float = calculate_compromise(history, positions)
    agreement_reached: bool = compromise_score >= AGREEMENT_THRESHOLD
    final_terms: str = _derive_final_terms(history, request.issue)

    logger.info(
        "Negotiation complete | score=%.4f | agreement=%s",
        compromise_score,
        agreement_reached,
    )

    # ------------------------------------------------------------------
    # Build structured round results for the response
    # ------------------------------------------------------------------
    round_results: List[RoundResult] = [
        RoundResult(
            round=entry["round"],
            usa_proposal=entry["usa_proposal"],
            china_response=entry["china_response"],
        )
        for entry in history
    ]

    outcome = OutcomeResult(
        agreement_reached=agreement_reached,
        final_terms=final_terms,
        compromise_score=compromise_score,
    )

    # ------------------------------------------------------------------
    # Persist log entry
    # ------------------------------------------------------------------
    log_entry: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "issue": request.issue,
        "requested_rounds": request.rounds,
        "rounds": [r.model_dump() for r in round_results],
        "outcome": outcome.model_dump(),
    }
    _append_log_entry(log_entry)

    return NegotiateResponse(rounds=round_results, outcome=outcome)
