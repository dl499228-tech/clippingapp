"""Modular clip scoring.

The LLM returns 8 raw sub-metrics (0-100). This module converts them into a
single overall score using a configurable weight table. Keeping the weights and
aggregation here (separate from the AI call) makes the scoring system easy to
tune or replace later without re-running analysis.
"""
from __future__ import annotations

from typing import Dict

# Default weights (must cover the 8 sub-metrics). Tune freely.
DEFAULT_WEIGHTS: Dict[str, float] = {
    "hook": 1.6,
    "standalone": 1.3,
    "payoff": 1.3,
    "info_value": 1.0,
    "emotional": 1.0,
    "curiosity": 1.1,
    "context": 0.9,
    "social_appeal": 1.5,
}

SUB_METRICS = list(DEFAULT_WEIGHTS.keys())


def clamp_score(v) -> float:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(100.0, v))


def compute_overall(scores: Dict[str, float], weights: Dict[str, float] = None) -> float:
    """Weighted average of the sub-metrics, returned 0-100 (1 decimal)."""
    weights = weights or DEFAULT_WEIGHTS
    total_w = 0.0
    acc = 0.0
    for metric, w in weights.items():
        acc += clamp_score(scores.get(metric, 0)) * w
        total_w += w
    if total_w == 0:
        return 0.0
    return round(acc / total_w, 1)


def normalize_scores(raw: Dict) -> Dict[str, float]:
    """Ensure every sub-metric exists and is clamped 0-100."""
    return {m: clamp_score(raw.get(m, 0)) for m in SUB_METRICS}
