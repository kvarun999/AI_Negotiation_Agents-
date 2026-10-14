"""
main.py  — FastAPI application entry point.

Loads trade positions and agent config from environment variables at
startup.  The /negotiate endpoint will be implemented in the next commit.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI

from agents.negotiator import Negotiator
from scoring import calculate_compromise  # noqa: F401  imported for later use

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config — all sourced from environment variables
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


def _load_positions(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise RuntimeError(f"Trade positions file not found at '{path}'.")
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    for country in ("usa", "china"):
        if country not in data:
            raise RuntimeError(f"Trade positions file missing '{country}' key.")
    return data


positions: Dict[str, Any] = _load_positions(TRADE_POSITIONS_PATH)
logger.info("Trade positions loaded from '%s'.", TRADE_POSITIONS_PATH)

usa_agent = Negotiator(
    country="usa", positions=positions["usa"],
    ollama_url=OLLAMA_BASE_URL, model=OLLAMA_MODEL,
    temperature=LLM_TEMPERATURE, timeout=OLLAMA_TIMEOUT,
)
china_agent = Negotiator(
    country="china", positions=positions["china"],
    ollama_url=OLLAMA_BASE_URL, model=OLLAMA_MODEL,
    temperature=LLM_TEMPERATURE, timeout=OLLAMA_TIMEOUT,
)
logger.info("Negotiator agents initialised (model=%s).", OLLAMA_MODEL)

app = FastAPI(
    title="AI Trade Negotiation API",
    description="Multi-agent trade negotiation powered by local LLMs via Ollama.",
    version="0.1.0",
)


@app.get("/health", tags=["Meta"])
async def health_check() -> Dict[str, str]:
    """Liveness probe for Docker and load balancers."""
    return {"status": "ok", "service": "AI Trade Negotiation API"}
