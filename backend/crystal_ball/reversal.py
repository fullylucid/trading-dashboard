"""
Classic reversal triggers for Crystal Ball.

These are the well-worn, defensible technical signals that fire near tops and
bottoms — quantified and given a directional vote so the fusion layer can weigh
them against the physics measures. We deliberately REUSE the tested
``analytics.signals`` package (RSI/MACD/divergence/local-extrema) rather than
re-deriving the math, so Crystal Ball stays consistent with the rest of the
dashboard's TA.

Each detector returns a uniform ``Signal`` dict::

    {
        "name":     short id,
        "label":    human-readable name,
        "value":    display value (str|num),
        "vote":     "top" | "bottom" | "none",   # top = reversal DOWN, bottom = reversal UP
        "strength": 0.0..1.0,                      # how strongly this signal is firing
        "weight":   relative importance (set in WEIGHTS),
        "note":     one-line plain-language read,
    }

``vote`` semantics: a "top" vote argues a local TOP is near (bearish reversal);
a "bottom" vote argues a local BOTTOM is near (bullish reversal). "none" = quiet.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

# Reuse the tested indicator library. Import-guarded so a packaging hiccup
# degrades to "no classic signals" instead of crashing the read.
try:
    from analytics.signals import (
        _rsi_series,
        _macd_hist_series,
        detect_divergence,
        rsi as _rsi_last,
    )
    HAS_SIGNALS = True
except Exception:  # pragma: no cover - import guard
    HAS_SIGNALS = False


# Relative importance of each detector in the fused vote. Divergence is the most
# reliable single reversal tell; raw overbought/oversold the least (markets stay
# stretched for a long time), so it is weighted lightest.
WEIGHTS: Dict[str, float] = {
    "divergence": 1.0,
    "bb_extension": 0.7,
    "rsi_extreme": 0.5,
    "volume_exhaustion": 0.6,
}


def _signal(name: str, label: str, value: Any, vote: str, strength: float, note: str) -> Dict[str, Any]:
    return {
        "name": name,
        "label": label,
        "value": value,
        "vote": vote,
        "strength": round(float(np.clip(strength, 0.0, 1.0)), 3),
        "weight": WEIGHTS.get(name, 0.5),
        "note": note,
    }


# ---------------------------------------------------------------------------
# 1. RSI / MACD-hist divergence (momentum disagreeing with price)
# ---------------------------------------------------------------------------

def divergence_signal(close: np.ndarray, lookback: int = 60) -> Dict[str, Any]:
    """Bearish/bullish regular divergence on BOTH RSI and MACD-hist vs price.

    A divergence confirmed by both oscillators is the single strongest classic
    reversal tell; one oscillator alone is a weaker tell. Strength scales with how
    many oscillators agree.
    """
    if not HAS_SIGNALS or close.size < 40:
        return _signal("divergence", "RSI/MACD Divergence", "n/a", "none", 0.0,
                       "Not enough data to assess divergence.")
    votes: List[str] = []
    detail: List[str] = []
    try:
        rsi_arr = _rsi_series(close, period=14)
        d_rsi = detect_divergence(close, rsi_arr, lookback=lookback)
        if d_rsi.get("signal"):
            sig = d_rsi["signal"]
            votes.append("top" if sig == "bearish" else "bottom")
            detail.append(f"RSI {sig}")
    except Exception:  # noqa: BLE001
        pass
    try:
        hist = _macd_hist_series(close, 12, 26, 9)
        d_macd = detect_divergence(close, hist, lookback=lookback)
        if d_macd.get("signal"):
            sig = d_macd["signal"]
            votes.append("top" if sig == "bearish" else "bottom")
            detail.append(f"MACD {sig}")
    except Exception:  # noqa: BLE001
        pass

    if not votes:
        return _signal("divergence", "RSI/MACD Divergence", "none", "none", 0.0,
                       "Price and momentum are in agreement — no divergence.")
    # If the two oscillators disagree on direction, it's noise -> weak/none.
    if len(set(votes)) > 1:
        return _signal("divergence", "RSI/MACD Divergence", "mixed", "none", 0.1,
                       "RSI and MACD divergences disagree — treat as noise.")
    vote = votes[0]
    strength = 0.6 if len(votes) == 1 else 0.95  # both agreeing is a strong tell
    arrow = "top (bearish)" if vote == "top" else "bottom (bullish)"
    return _signal("divergence", "RSI/MACD Divergence", " + ".join(detail), vote, strength,
                   f"Momentum diverging from price -> {arrow} reversal pressure.")


# ---------------------------------------------------------------------------
# 2. Bollinger / z-score extension (statistical over-stretch)
# ---------------------------------------------------------------------------

def bb_extension_signal(close: np.ndarray, window: int = 20) -> Dict[str, Any]:
    """How many std-devs price sits above/below its rolling mean (BB %b cousin).

    |z| >= 2 is the classic Bollinger-band touch; the further beyond, the more
    stretched. A stretched-high reads as top pressure, stretched-low as bottom.
    """
    c = np.asarray(close, dtype=float).ravel()
    c = c[np.isfinite(c)]
    if c.size < window + 1:
        return _signal("bb_extension", "Bollinger Extension", "n/a", "none", 0.0,
                       "Not enough data for band extension.")
    win = c[-window:]
    mean = float(np.mean(win))
    sd = float(np.std(win))
    if sd <= 0:
        return _signal("bb_extension", "Bollinger Extension", "flat", "none", 0.0,
                       "No volatility in window.")
    z = (c[-1] - mean) / sd
    # Strength ramps from 0 at |z|=1 to 1 at |z|>=3.
    strength = float(np.clip((abs(z) - 1.0) / 2.0, 0.0, 1.0))
    if z >= 1.5:
        return _signal("bb_extension", "Bollinger Extension", f"+{z:.2f}σ", "top", strength,
                       f"Price stretched {z:.2f}σ above its {window}-bar mean — snap-back risk.")
    if z <= -1.5:
        return _signal("bb_extension", "Bollinger Extension", f"{z:.2f}σ", "bottom", strength,
                       f"Price stretched {z:.2f}σ below its {window}-bar mean — bounce risk.")
    return _signal("bb_extension", "Bollinger Extension", f"{z:+.2f}σ", "none", strength * 0.3,
                   f"Price within normal range ({z:+.2f}σ).")


# ---------------------------------------------------------------------------
# 3. RSI overbought / oversold (raw extreme)
# ---------------------------------------------------------------------------

def rsi_extreme_signal(close: np.ndarray, period: int = 14) -> Dict[str, Any]:
    """Raw RSI extreme. Weakest reversal tell on its own (trends stay stretched),
    but a useful confirmer alongside divergence + over-extension."""
    if not HAS_SIGNALS or close.size < period + 2:
        return _signal("rsi_extreme", "RSI Extreme", "n/a", "none", 0.0,
                       "Not enough data for RSI.")
    try:
        val = float(_rsi_last(close, period=period))
    except Exception:  # noqa: BLE001
        return _signal("rsi_extreme", "RSI Extreme", "n/a", "none", 0.0, "RSI unavailable.")
    if not np.isfinite(val):
        return _signal("rsi_extreme", "RSI Extreme", "n/a", "none", 0.0, "RSI unavailable.")
    if val >= 70:
        strength = float(np.clip((val - 70) / 20.0, 0.0, 1.0))
        return _signal("rsi_extreme", "RSI Extreme", round(val, 1), "top", strength,
                       f"RSI {val:.0f} — overbought.")
    if val <= 30:
        strength = float(np.clip((30 - val) / 20.0, 0.0, 1.0))
        return _signal("rsi_extreme", "RSI Extreme", round(val, 1), "bottom", strength,
                       f"RSI {val:.0f} — oversold.")
    return _signal("rsi_extreme", "RSI Extreme", round(val, 1), "none", 0.0,
                   f"RSI {val:.0f} — neutral.")


# ---------------------------------------------------------------------------
# 4. Volume exhaustion / climax at an extreme
# ---------------------------------------------------------------------------

def volume_exhaustion_signal(close: np.ndarray, volume: Optional[np.ndarray],
                             window: int = 20) -> Dict[str, Any]:
    """A volume spike (high rvol) coinciding with a local price extreme — the
    classic capitulation/blow-off climax that often marks exhaustion of a move.

    Direction is set by where price sits in its recent range: a spike at the
    window low reads as a selling climax (bottom), at the high as a buying
    climax (top)."""
    if volume is None:
        return _signal("volume_exhaustion", "Volume Climax", "n/a", "none", 0.0,
                       "No volume data.")
    v = np.asarray(volume, dtype=float).ravel()
    c = np.asarray(close, dtype=float).ravel()
    n = min(v.size, c.size)
    if n < window + 1:
        return _signal("volume_exhaustion", "Volume Climax", "n/a", "none", 0.0,
                       "Not enough data for volume climax.")
    v = v[-window:]
    c_win = c[-window:]
    base = float(np.median(v[:-1])) if v.size > 1 else 0.0
    if base <= 0:
        return _signal("volume_exhaustion", "Volume Climax", "n/a", "none", 0.0,
                       "No baseline volume.")
    rvol = v[-1] / base
    if rvol < 1.8:
        return _signal("volume_exhaustion", "Volume Climax", f"{rvol:.1f}x", "none",
                       float(np.clip((rvol - 1.0) / 2.0, 0.0, 0.3)),
                       f"Volume {rvol:.1f}x median — no climax.")
    # Where does the latest close sit in the window range?
    lo, hi = float(np.min(c_win)), float(np.max(c_win))
    rng = hi - lo
    pos = (c_win[-1] - lo) / rng if rng > 0 else 0.5
    strength = float(np.clip((rvol - 1.8) / 2.0, 0.0, 1.0))
    if pos >= 0.8:
        return _signal("volume_exhaustion", "Volume Climax", f"{rvol:.1f}x @ high", "top",
                       strength, f"{rvol:.1f}x volume at range high — possible buying climax.")
    if pos <= 0.2:
        return _signal("volume_exhaustion", "Volume Climax", f"{rvol:.1f}x @ low", "bottom",
                       strength, f"{rvol:.1f}x volume at range low — possible selling climax.")
    return _signal("volume_exhaustion", "Volume Climax", f"{rvol:.1f}x mid", "none",
                   strength * 0.3, f"{rvol:.1f}x volume mid-range — inconclusive.")


def all_reversal_signals(close: np.ndarray, volume: Optional[np.ndarray] = None) -> List[Dict[str, Any]]:
    """Run every classic detector and return their uniform Signal dicts."""
    return [
        divergence_signal(close),
        bb_extension_signal(close),
        rsi_extreme_signal(close),
        volume_exhaustion_signal(close, volume),
    ]
