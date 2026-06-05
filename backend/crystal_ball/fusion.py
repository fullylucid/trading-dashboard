"""
Crystal Ball fusion — turn the physics + reversal layers into ONE honest read.

Design philosophy (the whole point of this tab):

  *We do not predict tops and bottoms with certainty.* We estimate the
  probability that a local reversal is near, we say which direction, and we are
  explicit about our own confidence — which is GATED by how predictable the
  regime actually is. A statistically unpredictable (high-entropy) tape caps the
  confidence at "low" no matter how many indicators are screaming, because in a
  random-walk regime those indicators are noise.

Pipeline
--------
1. Compute physics measures (Hurst, OU half-life/z, permutation entropy) and the
   classic reversal signals (divergence, BB-extension, RSI-extreme, vol-climax).
2. Each contributor casts a *signed, weighted* vote:
       top  -> +score   (reversal DOWN is near)
       bottom -> -score  (reversal UP is near)
   weighted by the contributor's reliability weight × its firing strength.
3. The net signed vote is squashed through a logistic into a directional
   probability; |net| sets the reversal probability magnitude.
4. The physics layer MODULATES rather than just votes:
       - Hurst < 0.5 (mean-reverting) AMPLIFIES reversal odds; > 0.5 dampens them
         (in a trending regime, "overbought" persists).
       - A stretched OU z-score with a short half-life adds directional pressure.
       - Permutation entropy sets the confidence ceiling (honesty gate).
5. Emit a plain-language thesis + an explicit invalidation level.

The output dict is JSON-ready and self-describing so the frontend is pure
rendering and the caller can always see *why*.
"""

from __future__ import annotations

from math import exp
from typing import Any, Dict, List, Optional

import numpy as np

from .physics import hurst_exponent, ou_mean_reversion, permutation_entropy
from .reversal import all_reversal_signals


def _logistic(x: float, k: float = 1.0) -> float:
    return 1.0 / (1.0 + exp(-k * x))


def _confidence_label(score: float) -> str:
    if score >= 0.66:
        return "high"
    if score >= 0.33:
        return "medium"
    return "low"


def crystal_ball_read(
    symbol: str,
    close,
    volume=None,
    *,
    last_price: Optional[float] = None,
) -> Dict[str, Any]:
    """Produce the fused reversal read for one symbol.

    Parameters
    ----------
    symbol : str
    close  : array-like adjusted-close, COMPLETED bars only (no look-ahead).
    volume : optional array-like volume aligned to ``close``.
    last_price : optional float, the live/last price for the invalidation note.

    Returns a JSON-ready dict — see ``_assemble`` for the shape.
    """
    c = np.asarray(close, dtype=float).ravel()
    c = c[np.isfinite(c)]
    n = c.size

    # Hard floor: without enough history this is guesswork, and we say so.
    if n < 60:
        return _assemble(
            symbol, direction="none", reversal_probability=0.0, confidence="low",
            predictability=None, physics={}, signals=[],
            thesis="Not enough price history to form a read (need ~60+ bars).",
            invalidation=None, data_ok=False,
        )

    log_c = np.log(c)

    # --- Physics layer -----------------------------------------------------
    hurst = hurst_exponent(log_c)
    ou = ou_mean_reversion(log_c)
    # Permutation entropy on the log-PRICE PATH (not returns). Daily returns are
    # near-noise for every liquid name (entropy ~1.0), which would pin confidence
    # at "low" forever. The price path carries the exploitable ordinal structure
    # (trends/reversals), giving a usable predictability spread. Order 4 = 24
    # ordinal patterns for finer resolution.
    pe = permutation_entropy(log_c, order=4)

    physics = {
        "hurst": hurst,
        "ou_half_life": ou.get("half_life"),
        "ou_z": ou.get("z"),
        "permutation_entropy": round(pe, 3) if pe is not None else None,
    }

    # --- Classic reversal signals -----------------------------------------
    signals = all_reversal_signals(c, volume)

    # --- Signed weighted vote from the classic signals ---------------------
    net = 0.0
    weight_sum = 0.0
    for s in signals:
        w = float(s.get("weight", 0.5)) * float(s.get("strength", 0.0))
        weight_sum += float(s.get("weight", 0.5))
        if s["vote"] == "top":
            net += w
        elif s["vote"] == "bottom":
            net -= w

    # --- Physics modulation -----------------------------------------------
    # OU stretch contributes directional pressure: stretched ABOVE equilibrium
    # (z>0) argues for a top, stretched BELOW (z<0) for a bottom. Scaled and
    # capped so it informs rather than dominates the classic signals.
    ou_z = ou.get("z")
    if ou_z is not None and np.isfinite(ou_z):
        ou_push = float(np.clip(ou_z / 3.0, -1.0, 1.0)) * 0.6
        net += ou_push  # z>0 -> +net -> top; z<0 -> bottom

    # Hurst regime gain: mean-reverting tape (H<0.5) amplifies reversal odds,
    # trending tape (H>0.5) dampens them. Gain in ~[0.6, 1.4].
    regime_gain = 1.0
    if hurst is not None:
        regime_gain = float(np.clip(1.0 + (0.5 - hurst) * 1.6, 0.6, 1.4))
    net *= regime_gain

    # --- Direction + probability ------------------------------------------
    direction = "none"
    if net > 0.15:
        direction = "top"
    elif net < -0.15:
        direction = "bottom"

    # Reversal-probability magnitude: squash |net| into (0,1). k tuned so that a
    # single strong divergence (~0.95 strength × 1.0 weight) lands around ~0.6.
    magnitude = _logistic(abs(net), k=1.6) * 2.0 - 1.0  # maps |net|>=0 -> [0,1)
    reversal_probability = float(np.clip(magnitude, 0.0, 0.95))

    # --- Confidence: agreement × regime structure (the honesty gate) -------
    # Confidence reflects (a) how strongly the contributors AGREE, (b) how much
    # fired, and (c) whether the REGIME is structured enough to trust at all.
    # Predictability is measured by the Hurst DISTANCE FROM A RANDOM WALK
    # (|H-0.5|): near 0.5 the tape is a coin-flip and confidence is pulled down
    # no matter how loud the indicators. (Permutation entropy of daily bars
    # saturates near 1.0 for every liquid name, so it is kept only as a reported
    # diagnostic — NOT a gate. Validated: it could not separate trend from noise.)
    fired = [s for s in signals if s["vote"] != "none"]
    agree = 0.0
    if fired:
        top_w = sum(s["weight"] * s["strength"] for s in fired if s["vote"] == "top")
        bot_w = sum(s["weight"] * s["strength"] for s in fired if s["vote"] == "bottom")
        denom = top_w + bot_w
        agree = abs(top_w - bot_w) / denom if denom > 0 else 0.0
    base_conf = float(np.clip(0.5 * reversal_probability + 0.5 * agree, 0.0, 1.0))

    # Predictability from Hurst: exploitable memory = distance from random walk.
    predictability = None
    pred_factor = 0.6  # neutral if Hurst is unavailable
    coherence = 1.0
    if hurst is not None:
        predictability = round(float(np.clip(abs(hurst - 0.5) / 0.35, 0.0, 1.0)), 3)
        # Steep floor: a true random walk (predictability~0) must collapse to
        # "low" confidence even when chance-aligned signals agree strongly.
        pred_factor = float(np.clip(0.25 + predictability * 0.75, 0.25, 1.0))
        # Regime coherence: a reversal call in a TRENDING tape (H>0.5) fights the
        # trend -> trust it less; in a mean-reverting tape it is supported.
        if direction != "none":
            coherence = float(np.clip(1.0 - max(0.0, hurst - 0.5) * 1.4, 0.5, 1.0))
    confidence_score = float(np.clip(base_conf * pred_factor * coherence, 0.0, 1.0))
    confidence = _confidence_label(confidence_score)

    # --- Narrative ---------------------------------------------------------
    thesis = _build_thesis(direction, reversal_probability, confidence, hurst, ou,
                           predictability, fired)
    invalidation = _build_invalidation(direction, c, last_price)

    return _assemble(
        symbol, direction=direction, reversal_probability=round(reversal_probability, 3),
        confidence=confidence, predictability=predictability, physics=physics,
        signals=signals, thesis=thesis, invalidation=invalidation, data_ok=True,
        extras={
            "net_vote": round(net, 3),
            "regime_gain": round(regime_gain, 3),
            "confidence_score": round(confidence_score, 3),
            "bars": int(n),
        },
    )


# ---------------------------------------------------------------------------
# narrative helpers
# ---------------------------------------------------------------------------

def _build_thesis(direction, prob, confidence, hurst, ou, predictability, fired) -> str:
    if direction == "none":
        return ("No reversal edge right now — the signals are quiet or conflicting. "
                "Crystal Ball stays silent rather than manufacture a call.")

    side = "local TOP (bearish reversal)" if direction == "top" else "local BOTTOM (bullish reversal)"
    parts = [f"Crystal Ball reads ~{prob * 100:.0f}% odds of a {side} forming, "
             f"confidence {confidence}."]

    if fired:
        names = ", ".join(s["label"] for s in fired)
        parts.append(f"Firing: {names}.")

    if hurst is not None:
        if hurst < 0.45:
            parts.append(f"Hurst {hurst:.2f} (mean-reverting regime) supports a snap-back.")
        elif hurst > 0.55:
            parts.append(f"Hurst {hurst:.2f} (trending regime) argues the move can persist — "
                         f"reversal calls are riskier here.")
        else:
            parts.append(f"Hurst {hurst:.2f} (near random-walk) — memory gives no edge.")

    hl = ou.get("half_life")
    z = ou.get("z")
    if hl is not None and z is not None:
        parts.append(f"OU stretch {z:+.1f}σ with a {hl:.0f}-bar mean-reversion half-life.")

    if predictability is not None and predictability < 0.30:
        parts.append("⚠ Regime sits near a random walk (little exploitable structure) — "
                     "confidence is deliberately reduced; treat as a weak read and size down.")

    return " ".join(parts)


def _build_invalidation(direction, close: np.ndarray, last_price: Optional[float]) -> Optional[Dict[str, Any]]:
    """A concrete level that would kill the reversal thesis.

    For a TOP call: a close back above the recent swing high invalidates.
    For a BOTTOM call: a close back below the recent swing low invalidates.
    """
    if direction == "none" or close.size < 20:
        return None
    win = close[-20:]
    px = float(last_price) if last_price is not None and np.isfinite(last_price) else float(close[-1])
    if direction == "top":
        level = float(np.max(win))
        return {"level": round(level, 4), "rule": "close above 20-bar high",
                "distance_pct": round((level / px - 1.0) * 100.0, 2)}
    level = float(np.min(win))
    return {"level": round(level, 4), "rule": "close below 20-bar low",
            "distance_pct": round((level / px - 1.0) * 100.0, 2)}


def _assemble(symbol, *, direction, reversal_probability, confidence, predictability,
              physics, signals, thesis, invalidation, data_ok,
              extras: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "symbol": symbol,
        "direction": direction,                  # "top" | "bottom" | "none"
        "reversal_probability": reversal_probability,  # 0..1
        "confidence": confidence,                # "low" | "medium" | "high"
        "predictability": predictability,        # 0..1 (1 - normalized entropy) or None
        "physics": physics,
        "signals": signals,
        "thesis": thesis,
        "invalidation": invalidation,
        "data_ok": data_ok,
        "disclaimer": ("Probabilistic reversal estimate, not a guarantee. Markets are "
                       "non-stationary; confidence is gated by regime predictability. "
                       "Not financial advice."),
    }
    if extras:
        out["_debug"] = extras
    return out
