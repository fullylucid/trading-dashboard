"""
Crack-a-Dawn — Attention Score (P0 core, no LLM, no network).

Replaces an arbitrary fixed-% mover threshold with a context-relative score.
A move earns attention when it is abnormal FOR THIS STOCK, driven by THIS company
(not just the market), backed by VOLUME, and RELEVANT to the book.

Four independent axes -> composite -> attention tier. Pure functions; all weights
and thresholds live in `Config` so they can be calibrated after a week of live runs
(per the locked spec). See ~/.claude/plans/crack-a-dawn-agent-spec.md.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import mean, pstdev
from typing import List, Optional, Sequence


# --------------------------------------------------------------------------- #
# Tiers
# --------------------------------------------------------------------------- #
TIER_ACT = "ACT"            # 🔴 decide before open
TIER_KNOW = "KNOW"          # 🟡 understand the why
TIER_NOTE = "NOTE"          # ⚪ on the radar
TIER_UNEXPLAINED = "UNEXPLAINED"  # ❓ high-sigma, no catalyst found (set in the catalyst phase)

TIER_EMOJI = {TIER_ACT: "🔴", TIER_KNOW: "🟡", TIER_NOTE: "⚪", TIER_UNEXPLAINED: "❓"}
_TIER_RANK = {TIER_ACT: 3, TIER_UNEXPLAINED: 2, TIER_KNOW: 1, TIER_NOTE: 0}


@dataclass
class Config:
    """Calibration knobs (defaults now; tune after live runs)."""
    sigma_window: int = 30          # trading days for the baseline distribution
    sigma_full_score: float = 4.0   # |z| that maps to a full 1.0 abnormality score
    rvol_full_score: float = 3.0    # RVOL that maps to a full 1.0 volume score
    rvol_floor: float = 0.5         # below this, the move is volume-discounted
    # composite weights
    w_significance: float = 0.6
    w_relevance: float = 0.4
    # tier thresholds (on 0..1 composite / significance)
    act_significance: float = 0.55
    act_relevance: float = 0.55
    know_significance: float = 0.55
    note_significance: float = 0.30
    # relevance base scores
    rel_watchlist: float = 0.30
    rel_held: float = 0.60


@dataclass
class MoverInput:
    ticker: str
    move_pct: float                     # prior close -> current (pre-market) %
    hist_returns: Sequence[float]       # ~30d of daily/overnight returns (fractions or %, consistent w/ move_pct)
    market_move_pct: float = 0.0        # market (e.g., SPY) move over the same window
    beta: float = 1.0                   # asset beta vs market
    premarket_volume: Optional[float] = None
    avg_volume: Optional[float] = None  # typical session volume (for RVOL)
    held: bool = False
    weight: float = 0.0                 # position weight, 0..1 of book
    level_flag: Optional[str] = None    # "at_stop" | "through_entry" | "near_support" | ... | None
    intent: Optional[str] = None        # "hold" | "watch_entry" | "watch_exit"
    catalyst_found: Optional[bool] = None  # set later (catalyst phase); None in P0
    # trajectory (locked enhancement): same-direction follow-through vs fade, -1..1
    trajectory: Optional[float] = None  # +1 building, 0 flat, -1 fading


@dataclass
class MoverScore:
    ticker: str
    move_pct: float
    sigma: float                # signed z-score of the raw move
    residual_pct: float         # move minus beta*market (idiosyncratic part)
    residual_sigma: float       # residual normalized by the stock's own vol
    rvol: Optional[float]
    abnormality: float          # 0..1
    idiosyncrasy: float         # 0..1
    volume_conviction: float    # 0..1 (1.0 when unknown -> neutral)
    relevance: float            # 0..1
    significance: float         # 0..1 combined move-notability (vol-adjusted)
    composite: float            # 0..1 final attention score
    tier: str
    direction: str              # "up" | "down"
    reasons: List[str] = field(default_factory=list)


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def gap_stats(returns: Sequence[float]) -> tuple[float, float]:
    """Mean and (population) std of the recent return distribution. Std floored to
    avoid divide-by-zero on a flat history."""
    vals = [float(r) for r in returns if r is not None and not math.isnan(float(r))]
    if len(vals) < 3:
        return 0.0, 0.0
    return mean(vals), pstdev(vals)


def _relevance(m: MoverInput, cfg: Config, reasons: List[str]) -> float:
    if m.level_flag in ("at_stop", "through_entry"):
        reasons.append(f"level:{m.level_flag} (max relevance)")
        return 1.0
    base = cfg.rel_held if m.held else cfg.rel_watchlist
    score = base + min(m.weight, 0.4)  # size adds up to +0.4
    if m.level_flag:
        score += 0.1
        reasons.append(f"near {m.level_flag}")
    if m.held:
        reasons.append(f"held ({m.weight*100:.0f}% of book)")
    return _clamp(score)


def score_mover(m: MoverInput, cfg: Optional[Config] = None) -> MoverScore:
    cfg = cfg or Config()
    reasons: List[str] = []

    mu, sd = gap_stats(m.hist_returns)
    sigma = (m.move_pct - mu) / sd if sd > 0 else 0.0
    abnormality = _clamp(abs(sigma) / cfg.sigma_full_score)
    if abs(sigma) >= 2:
        reasons.append(f"{abs(sigma):.1f}sigma move (vs its own {cfg.sigma_window}d range)")

    expected = m.beta * m.market_move_pct
    residual = m.move_pct - expected
    residual_sigma = residual / sd if sd > 0 else 0.0
    idiosyncrasy = _clamp(abs(residual_sigma) / cfg.sigma_full_score)
    if abs(residual) >= abs(m.move_pct) * 0.6 and abs(sigma) >= 2:
        reasons.append(f"idiosyncratic ({residual:+.1f}% after market/beta)")
    elif abs(expected) >= abs(m.move_pct) * 0.6:
        reasons.append("mostly market/beta-driven")

    # Volume conviction: 1.0 = neutral when unknown; boosts on RVOL, discounts when thin.
    rvol = None
    volume_conviction = 1.0
    if m.premarket_volume is not None and m.avg_volume and m.avg_volume > 0:
        rvol = m.premarket_volume / m.avg_volume
        if rvol >= 1.0:
            volume_conviction = _clamp(0.7 + 0.3 * min(rvol / cfg.rvol_full_score, 1.0))
            reasons.append(f"{rvol:.1f}x volume")
        else:
            volume_conviction = _clamp(rvol / cfg.rvol_floor) * 0.7 + 0.3
            if rvol < cfg.rvol_floor:
                reasons.append(f"thin volume ({rvol:.1f}x) — discounted")

    # Significance = the move is notable if EITHER raw-abnormal OR idiosyncratic,
    # then scaled by volume conviction.
    significance = max(abnormality, idiosyncrasy) * volume_conviction

    # Trajectory nudges significance (building corroborates, fading discounts).
    if m.trajectory is not None:
        significance = _clamp(significance * (1.0 + 0.15 * m.trajectory))
        if m.trajectory > 0.3:
            reasons.append("building (held/extended overnight)")
        elif m.trajectory < -0.3:
            reasons.append("fading from the spike")

    relevance = _relevance(m, cfg, reasons)
    composite = _clamp(cfg.w_significance * significance + cfg.w_relevance * relevance)

    # Hard override: at a level you care about + a real move => ACT.
    level_override = m.level_flag in ("at_stop", "through_entry") and abs(sigma) >= 1.5

    if level_override or (significance >= cfg.act_significance and relevance >= cfg.act_relevance):
        tier = TIER_ACT
    elif significance >= cfg.know_significance:
        # high-sigma but no catalyst found yet -> flag for a human look
        tier = TIER_UNEXPLAINED if m.catalyst_found is False else TIER_KNOW
    elif significance >= cfg.note_significance:
        tier = TIER_NOTE
    else:
        tier = TIER_NOTE

    return MoverScore(
        ticker=m.ticker, move_pct=m.move_pct, sigma=sigma,
        residual_pct=residual, residual_sigma=residual_sigma, rvol=rvol,
        abnormality=abnormality, idiosyncrasy=idiosyncrasy,
        volume_conviction=volume_conviction, relevance=relevance,
        significance=significance, composite=composite, tier=tier,
        direction="up" if m.move_pct >= 0 else "down", reasons=reasons,
    )


def rank_movers(inputs: Sequence[MoverInput], cfg: Optional[Config] = None) -> List[MoverScore]:
    """Score and rank — by tier first, then composite. (Rank, don't gate: callers
    surface the top of the list so quiet mornings still yield the most-notable names.)"""
    scored = [score_mover(m, cfg) for m in inputs]
    scored.sort(key=lambda s: (_TIER_RANK[s.tier], s.composite), reverse=True)
    return scored
