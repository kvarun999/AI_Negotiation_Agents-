"""
scoring.py
----------
Heuristic compromise scoring for negotiation outcomes.

The scorer analyses the full round history using:
  1. Concession keyword frequency — words indicating willingness to agree.
  2. Combative keyword frequency — words indicating resistance or hard lines.
  3. Explicit priority keyword coverage — how many of each country's core
     priorities appear across their proposals (topic relevance).
  4. History length bonus — longer negotiations tend toward more compromise.

The resulting float is normalised to [0.0, 1.0].
"""

from __future__ import annotations

import math
from typing import Dict, List

# ---------------------------------------------------------------------------
# Keyword lexicons (all lower-case for case-insensitive matching)
# ---------------------------------------------------------------------------

_CONCESSION_KEYWORDS: List[str] = [
    "agree",
    "accept",
    "concede",
    "concession",
    "compromise",
    "mutual",
    "reciprocal",
    "cooperate",
    "cooperation",
    "lower",
    "reduce",
    "reduction",
    "flexibility",
    "flexible",
    "willing",
    "open to",
    "consider",
    "adjust",
    "accommodate",
    "partnership",
    "common ground",
    "shared interest",
    "balanced",
    "fair",
    "acknowledge",
    "proposal",
    "offer",
]

_COMBATIVE_KEYWORDS: List[str] = [
    "reject",
    "refuse",
    "unacceptable",
    "non-negotiable",
    "demand",
    "insist",
    "firmly",
    "absolutely not",
    "never",
    "oppose",
    "block",
    "veto",
    "escalate",
    "retaliate",
    "sanction",
    "punish",
    "protectionist",
    "red line",
    "ultimatum",
]


def _count_keywords(text: str, keywords: List[str]) -> int:
    """Count total keyword occurrences in *text* (case-insensitive)."""
    lower_text = text.lower()
    return sum(lower_text.count(kw) for kw in keywords)


def _priority_coverage(history: List[Dict], positions: Dict) -> float:
    """
    Measures how much each country's proposals mention *their own* priority
    topics, producing a proxy for topic relevance (0.0–1.0).

    A high score means the agents stayed on topic — a prerequisite for any
    real agreement.
    """
    all_usa_text = " ".join(
        entry.get("usa_proposal", "") for entry in history
    ).lower()
    all_china_text = " ".join(
        entry.get("china_response", "") for entry in history
    ).lower()

    usa_priorities: List[str] = positions.get("usa", {}).get("priorities", [])
    china_priorities: List[str] = positions.get("china", {}).get("priorities", [])

    def coverage(text: str, priorities: List[str]) -> float:
        if not priorities:
            return 0.0
        # Split each priority into significant words (>= 4 chars) and check presence
        hits = 0
        for priority in priorities:
            words = [w for w in priority.lower().split() if len(w) >= 4]
            if any(w in text for w in words):
                hits += 1
        return hits / len(priorities)

    usa_cov = coverage(all_usa_text, usa_priorities)
    china_cov = coverage(all_china_text, china_priorities)
    return (usa_cov + china_cov) / 2.0


def calculate_compromise(history: List[Dict], positions: Dict) -> float:
    """
    Analyses the full negotiation history and returns a normalised
    compromise score in the range [0.0, 1.0].

    Parameters
    ----------
    history : List[Dict]
        Ordered list of round objects.  Each dict must contain at least:
          - ``usa_proposal``   (str) : USA agent's proposal text.
          - ``china_response`` (str) : China agent's response text.
    positions : Dict
        The full trade_positions.json structure (both countries).

    Returns
    -------
    float
        A value between 0.0 (no compromise) and 1.0 (full agreement).
    """
    if not history:
        return 0.0

    # ------------------------------------------------------------------
    # 1. Aggregate all text from both sides
    # ------------------------------------------------------------------
    all_text_parts: List[str] = []
    for entry in history:
        all_text_parts.append(entry.get("usa_proposal", ""))
        all_text_parts.append(entry.get("china_response", ""))
    all_text = " ".join(all_text_parts)

    # ------------------------------------------------------------------
    # 2. Concession vs combative ratio  (weight: 0.45)
    # ------------------------------------------------------------------
    concession_count = _count_keywords(all_text, _CONCESSION_KEYWORDS)
    combative_count = _count_keywords(all_text, _COMBATIVE_KEYWORDS)
    total_signal = concession_count + combative_count

    if total_signal == 0:
        keyword_score = 0.5  # neutral — no strong signals either way
    else:
        keyword_score = concession_count / total_signal

    # ------------------------------------------------------------------
    # 3. Priority coverage — did agents stay on topic? (weight: 0.35)
    # ------------------------------------------------------------------
    coverage_score = _priority_coverage(history, positions)

    # ------------------------------------------------------------------
    # 4. History length bonus — more rounds → more opportunity to converge
    #    Soft-capped via a logarithmic function.  (weight: 0.20)
    # ------------------------------------------------------------------
    # At 1 round → 0.0, at 5 rounds → ~0.7, at 10 rounds → ~1.0
    length_score = min(1.0, math.log(len(history) + 1) / math.log(10))

    # ------------------------------------------------------------------
    # 5. Weighted combination
    # ------------------------------------------------------------------
    raw_score = (
        0.45 * keyword_score
        + 0.35 * coverage_score
        + 0.20 * length_score
    )

    # Clamp firmly to [0.0, 1.0] to guard against floating-point drift
    return max(0.0, min(1.0, round(raw_score, 4)))
