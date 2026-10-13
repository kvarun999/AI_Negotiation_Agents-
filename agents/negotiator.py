"""
agents/negotiator.py
--------------------
Core Negotiator agent class.

Each instance represents one country in the negotiation.  The agent:
  1. Holds its persona, priorities, and red-lines.
  2. Constructs a rich, Chain-of-Thought prompt for the LLM.
  3. Calls the Ollama HTTP API asynchronously via httpx.AsyncClient.
  4. Implements retry logic with exponential back-off for resilience.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, List

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_MAX_RETRIES: int = 3
_BACKOFF_BASE: float = 1.5  # seconds — each retry waits base^attempt seconds


class Negotiator:
    """
    Represents a single country-level AI negotiation agent.

    Attributes
    ----------
    country : str
        Short identifier for the country (e.g. 'usa' or 'china').
    positions : dict
        The priorities, flexibility scores, and red-lines loaded from
        data/trade_positions.json for this specific country.
    ollama_url : str
        Base URL of the Ollama service (e.g. 'http://ollama:11434').
    model : str
        Name of the Ollama model to use (e.g. 'llama3').
    temperature : float
        LLM sampling temperature (0.0–1.0).
    timeout : float
        Per-request HTTP timeout in seconds.
    """

    def __init__(
        self,
        country: str,
        positions: dict,
        ollama_url: str,
        model: str = "llama3",
        temperature: float = 0.3,
        timeout: float = 120.0,
    ) -> None:
        self.country = country
        self.positions = positions
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        """
        Returns the static system prompt that establishes the agent's
        persona, priorities, and strict output formatting rules.
        """
        country_display = self.country.upper()
        priorities_text = "\n".join(
            f"  - {p}" for p in self.positions.get("priorities", [])
        )
        red_lines_text = "\n".join(
            f"  - {r}" for r in self.positions.get("red_lines", [])
        )
        flexibility_text = "\n".join(
            f"  - {k}: {v:.0%} willingness to move"
            for k, v in self.positions.get("flexibility", {}).items()
        )

        return (
            f"You are the chief trade negotiator for {country_display}. "
            f"Your task is to negotiate a bilateral trade agreement on behalf of your country.\n\n"
            f"YOUR PRIORITIES (most important to least important):\n{priorities_text}\n\n"
            f"YOUR RED LINES (you must NEVER compromise on these):\n{red_lines_text}\n\n"
            f"YOUR FLEXIBILITY PROFILE:\n{flexibility_text}\n\n"
            "NEGOTIATION STRATEGY:\n"
            "  - Begin each turn by privately reasoning (Chain of Thought) about the opponent's "
            "last position and deciding your next move.\n"
            "  - Identify areas of overlap and potential compromise.\n"
            "  - Make concessions only where your flexibility score is high.\n"
            "  - Never abandon a red-line item.\n"
            "  - Aim to reach a mutually beneficial agreement.\n\n"
            "OUTPUT FORMAT — CRITICAL:\n"
            "  - First, output a brief internal reasoning section labeled REASONING: "
            "(2–3 sentences max).\n"
            "  - Then output your actual proposal labeled PROPOSAL: "
            "(1–2 sentences max, formal diplomatic language).\n"
            "  - Do NOT output anything else. No greetings, no disclaimers, no markdown.\n"
        )

    def _build_user_prompt(self, issue: str, history: List[Dict]) -> str:
        """
        Builds the dynamic, turn-specific user prompt by injecting the
        current issue and the negotiation history.
        """
        lines: List[str] = [
            f"CURRENT NEGOTIATION ISSUE: {issue}\n",
        ]

        if not history:
            lines.append(
                "This is the OPENING ROUND. There is no prior history. "
                "Present your initial negotiating position clearly and confidently."
            )
        else:
            lines.append("NEGOTIATION HISTORY SO FAR:")
            for entry in history:
                round_num = entry.get("round", "?")
                usa_proposal = entry.get("usa_proposal", "")
                china_response = entry.get("china_response", "")
                lines.append(f"\n  Round {round_num}:")
                if usa_proposal:
                    lines.append(f"    USA proposal  : {usa_proposal}")
                if china_response:
                    lines.append(f"    China response : {china_response}")

        lines.append(
            "\nNow respond according to the OUTPUT FORMAT specified in your system prompt."
        )
        return "\n".join(lines)

    @staticmethod
    def _extract_proposal(raw_text: str) -> str:
        """
        Parses the LLM's raw output and extracts only the PROPOSAL section.
        Falls back to the full (stripped) text if the marker is absent.
        """
        text = raw_text.strip()

        # Try to find the PROPOSAL: marker (case-insensitive)
        lower = text.lower()
        marker = "proposal:"
        idx = lower.rfind(marker)  # rfind to handle duplicates gracefully
        if idx != -1:
            proposal = text[idx + len(marker) :].strip()
            # Strip any trailing REASONING section that may have leaked
            reasoning_idx = proposal.lower().find("reasoning:")
            if reasoning_idx != -1:
                proposal = proposal[:reasoning_idx].strip()
            return proposal

        # Fallback: strip markdown fencing / common preamble
        for prefix in ("here is my proposal:", "my proposal:", "proposal -"):
            if lower.startswith(prefix):
                return text[len(prefix) :].strip()

        return text

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate_response(self, prompt: str) -> str:
        """
        Asynchronously sends a prompt to the Ollama /api/generate endpoint
        and returns the model's response text.

        Implements retry logic with exponential back-off to handle transient
        failures (timeouts, connection resets, 5xx responses).

        Parameters
        ----------
        prompt : str
            The fully constructed prompt string.

        Returns
        -------
        str
            The text response from the LLM.

        Raises
        ------
        RuntimeError
            If all retry attempts fail.
        """
        url = f"{self.ollama_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": 256,  # cap output length for conciseness
            },
        }

        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(self.timeout, connect=10.0)
                ) as client:
                    response = await client.post(url, json=payload)
                    response.raise_for_status()
                    data = response.json()
                    return data.get("response", "").strip()

            except httpx.TimeoutException as exc:
                last_error = exc
                wait = _BACKOFF_BASE**attempt
                logger.warning(
                    "[%s] Ollama request timed out (attempt %d/%d). "
                    "Retrying in %.1fs…",
                    self.country.upper(),
                    attempt + 1,
                    _MAX_RETRIES,
                    wait,
                )
                await asyncio.sleep(wait)

            except httpx.HTTPStatusError as exc:
                last_error = exc
                logger.error(
                    "[%s] Ollama returned HTTP %s: %s",
                    self.country.upper(),
                    exc.response.status_code,
                    exc.response.text,
                )
                # 4xx errors are non-retriable
                if exc.response.status_code < 500:
                    break
                await asyncio.sleep(_BACKOFF_BASE**attempt)

            except httpx.RequestError as exc:
                last_error = exc
                wait = _BACKOFF_BASE**attempt
                logger.warning(
                    "[%s] Request error (attempt %d/%d): %s. Retrying in %.1fs…",
                    self.country.upper(),
                    attempt + 1,
                    _MAX_RETRIES,
                    str(exc),
                    wait,
                )
                await asyncio.sleep(wait)

        raise RuntimeError(
            f"Ollama request failed after {_MAX_RETRIES} attempts "
            f"for country '{self.country}': {last_error}"
        ) from last_error

    async def make_proposal(self, issue: str, history: List[Dict]) -> str:
        """
        Generates a negotiation proposal for the given issue, given the
        current negotiation history.

        Parameters
        ----------
        issue : str
            The topic under negotiation (e.g. 'Technology Tariffs').
        history : List[Dict]
            List of prior round objects (may be empty for the opening round).

        Returns
        -------
        str
            A clean, single-proposal string extracted from the LLM output.
        """
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(issue, history)

        # Ollama's /api/generate endpoint accepts a single `prompt` field.
        # We prefix the system instructions so the model honours the persona.
        full_prompt = f"{system_prompt}\n\n{user_prompt}"

        logger.info(
            "[%s] Generating proposal for issue='%s', history_len=%d",
            self.country.upper(),
            issue,
            len(history),
        )

        raw = await self.generate_response(full_prompt)

        proposal = self._extract_proposal(raw)
        logger.info("[%s] Proposal extracted: %s", self.country.upper(), proposal[:120])
        return proposal
