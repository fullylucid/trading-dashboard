"""Crack-a-Dawn — pre-market intelligence agent. See crack-a-dawn-agent-spec.md."""
from .scoring import (
    Config,
    MoverInput,
    MoverScore,
    score_mover,
    rank_movers,
    gap_stats,
    TIER_ACT,
    TIER_KNOW,
    TIER_NOTE,
    TIER_UNEXPLAINED,
    TIER_EMOJI,
    ball,
)

__all__ = [
    "Config", "MoverInput", "MoverScore", "score_mover", "rank_movers", "gap_stats",
    "TIER_ACT", "TIER_KNOW", "TIER_NOTE", "TIER_UNEXPLAINED", "TIER_EMOJI", "ball",
]
