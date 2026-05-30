"""Market-regime → trading-bias adapter.

Two layers, cleanly separated:

1. ``regime_bias(regime_state)`` — **PURE** (numpy/stdlib only, no network, no
   disk, no toolkit import). Maps a regime descriptor dict to a sizing / stop
   bias: how much of normal size to take and how wide to set ATR stops in the
   detected regime. This is the unit-tested part.

2. ``get_regime_with_bias(prices)`` — async IO wrapper. Calls the (now-fixed)
   :meth:`quant_bridge.QuantSignalBridge.get_regime_state`, then runs the pure
   ``regime_bias`` on the result. Every failure path degrades to a NEUTRAL
   default — it never raises into the caller.

Regime → bias mapping (rationale)
---------------------------------
Trend-following with risk-on/risk-off sizing. In a confirmed uptrend you want
full risk and normal stops (let winners run). In a choppy / sideways tape you
size down and widen stops to avoid getting whipsawed out of noise. In a
downtrend / crash you cut size hardest (capital preservation) and keep stops
wide so a single volatile bar does not stop you out at the worst price.

    regime class      size_multiplier   stop_atr_multiplier
    --------------     ---------------   -------------------
    uptrend / bull          1.0                2.0   (normal)
    choppy / sideways       0.7                2.5   (wider)
    downtrend / bear        0.5                3.0   (wider)
    neutral / unknown       0.7                2.5   (treat as choppy)

``stop_atr_multiplier`` is the number of ATRs to place a protective stop away
from entry; ``size_multiplier`` scales the *base* position size (e.g. the
fixed-fractional 2-3%-risk size) the caller already computed.

Regime-state schema (input)
---------------------------
Accepts the dict produced by ``QuantSignalBridge.get_regime_state`` /
``_map_regime`` / ``_default_regime``:

    {
      "hmm_phase": int,                 # 0=bear, 1=neutral, 2=bull
      "trend_direction": str,           # "bullish" | "neutral" | "bearish"
      "volatility_regime": str,         # "low" | "normal" | "high"
      "raw_regime": str,                # toolkit label, e.g. "bull_calm",
                                        #   "bear_stressed", "neutral", ...
      "estimated_probability": float,   # confidence in [0, 1]
      ...
    }

It is intentionally lenient: it will also accept a bare ``{"label": "..."}``
or ``{"regime": "..."}`` dict, or anything exposing one of the recognized keys.
The classification precedence is: explicit label/regime/raw_regime string →
trend_direction → hmm_phase → neutral fallback.

Sources
-------
- Risk-on/risk-off regime sizing: standard trend-following practice; see e.g.
  Andreas Clenow, *Trading Evolved* (volatility-targeted position sizing).
- ATR-based stops: J. Welles Wilder, *New Concepts in Technical Trading
  Systems* (1978) — the ATR and the "x ATRs from entry" stop convention.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

# --------------------------------------------------------------------------- #
# bias presets per regime class
# --------------------------------------------------------------------------- #
# Keyed by canonical regime class. Each preset is the (size, stop, note) bias.
_BIAS_PRESETS: Dict[str, Dict[str, Any]] = {
    "uptrend": {
        "size_multiplier": 1.0,
        "stop_atr_multiplier": 2.0,
        "note": "Uptrend/bull regime: full size, normal stops.",
    },
    "choppy": {
        "size_multiplier": 0.7,
        "stop_atr_multiplier": 2.5,
        "note": "Choppy/sideways regime: reduced size (0.7x), wider stops.",
    },
    "downtrend": {
        "size_multiplier": 0.5,
        "stop_atr_multiplier": 3.0,
        "note": "Downtrend/crash regime: reduced size (0.5x), wider stops.",
    },
    "neutral": {
        "size_multiplier": 0.7,
        "stop_atr_multiplier": 2.5,
        "note": "Neutral/unknown regime: treated as choppy — reduced size, wider stops.",
    },
}

# Substrings that classify a regime label into a canonical class. Order matters:
# the first class whose any-keyword matches wins. "bull"/"up" -> uptrend,
# "bear"/"down"/"crash" -> downtrend, "chop"/"side"/"range"/"transition" ->
# choppy. Anything else (incl. "neutral", "unknown", "insufficient") -> neutral.
_LABEL_KEYWORDS = (
    ("uptrend", ("bull", "uptrend", "up_", "improving", "leading")),
    ("downtrend", ("bear", "downtrend", "down", "crash", "lagging")),
    ("choppy", ("chop", "side", "range", "transition", "weakening", "stressed")),
)


def _neutral_bias() -> Dict[str, Any]:
    """Return a fresh copy of the neutral bias preset (safe default)."""
    return dict(_BIAS_PRESETS["neutral"])


def _classify_label(label: str) -> Optional[str]:
    """Map a free-form regime label string to a canonical class, or None.

    Case-insensitive substring match against ``_LABEL_KEYWORDS``. Note that the
    ``stressed`` keyword maps to *choppy*: a "bull_stressed" / "bear_stressed"
    tape is a high-volatility, low-conviction environment, so we down-size and
    widen stops rather than treating it as a clean trend. Clean trend labels
    ("bull_calm" / "bear_calm") fall through to uptrend / downtrend.
    """
    if not label:
        return None
    text = str(label).strip().lower()
    if not text:
        return None
    # "stressed" must win over the bull/bear prefix → check choppy keywords too,
    # but only after confirming it is not a calm trend. We do this by checking
    # the choppy "stressed" keyword first when present.
    if "stressed" in text or "transition" in text:
        return "choppy"
    for cls, keywords in _LABEL_KEYWORDS:
        if any(kw in text for kw in keywords):
            return cls
    return None


def _classify(regime_state: Mapping[str, Any]) -> str:
    """Resolve a regime-state mapping to a canonical class.

    Precedence: explicit label/regime/raw_regime string → trend_direction →
    hmm_phase → "neutral".
    """
    # 1. explicit label-ish string fields
    for key in ("label", "regime", "raw_regime"):
        if key in regime_state:
            cls = _classify_label(regime_state.get(key))
            if cls is not None:
                return cls

    # 2. trend_direction
    trend = regime_state.get("trend_direction")
    if trend is not None:
        t = str(trend).strip().lower()
        if t in ("bullish", "bull", "up", "uptrend"):
            return "uptrend"
        if t in ("bearish", "bear", "down", "downtrend"):
            return "downtrend"
        if t in ("neutral", "sideways", "choppy", "flat"):
            return "neutral"

    # 3. hmm_phase (0=bear, 1=neutral, 2=bull)
    phase = regime_state.get("hmm_phase")
    if phase is not None:
        try:
            p = int(phase)
        except (TypeError, ValueError):
            p = None
        if p == 2:
            return "uptrend"
        if p == 0:
            return "downtrend"
        if p == 1:
            return "neutral"

    # 4. fallback
    return "neutral"


def regime_bias(regime_state: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Map a regime-state dict to a position-sizing / stop bias. PURE.

    Parameters
    ----------
    regime_state : mapping or None
        A regime descriptor (see module docstring for the recognized schema).
        ``None`` or a non-mapping degrades to the neutral default.

    Returns
    -------
    dict
        ``{"size_multiplier": float, "stop_atr_multiplier": float,
           "note": str, "regime_class": str}``.

        - ``size_multiplier`` scales the caller's base position size.
        - ``stop_atr_multiplier`` is the number of ATRs for the protective stop.
        - ``regime_class`` is the canonical class the input resolved to
          (``uptrend`` / ``choppy`` / ``downtrend`` / ``neutral``).

    Notes
    -----
    Deterministic and side-effect free. The returned dict is a fresh copy, so
    callers may mutate it freely without affecting the presets.

    Examples
    --------
    >>> regime_bias({"trend_direction": "bullish"})["size_multiplier"]
    1.0
    >>> regime_bias({"raw_regime": "bear_stressed"})["size_multiplier"]
    0.7
    >>> regime_bias({"hmm_phase": 0})["stop_atr_multiplier"]
    3.0
    """
    if not isinstance(regime_state, Mapping):
        bias = _neutral_bias()
        bias["regime_class"] = "neutral"
        return bias

    cls = _classify(regime_state)
    bias = dict(_BIAS_PRESETS.get(cls, _BIAS_PRESETS["neutral"]))
    bias["regime_class"] = cls
    return bias


async def get_regime_with_bias(prices: Optional[Any] = None) -> Dict[str, Any]:
    """Fetch the current regime and attach its trading bias. Exception-wrapped.

    IO wrapper (NOT pure): instantiates / reuses a
    :class:`quant_bridge.QuantSignalBridge`, calls its async
    ``get_regime_state(prices)``, then runs the pure :func:`regime_bias`.

    Any failure — import error, bridge construction failure, regime-call
    exception — degrades to a NEUTRAL default so the caller always receives a
    usable dict and never sees an exception from here.

    Parameters
    ----------
    prices : list[float] | array-like | None
        Recent close prices (e.g. SPY history) handed straight to the bridge.
        The bridge returns its default regime when ``prices`` is missing/short,
        so a neutral bias falls out naturally.

    Returns
    -------
    dict
        ``{"regime_state": dict, "bias": dict}`` where ``bias`` is the output of
        :func:`regime_bias`. On any error, ``regime_state`` is a neutral default
        and ``bias`` is the neutral bias.
    """
    neutral_state: Dict[str, Any] = {
        "hmm_phase": 1,
        "volatility_regime": "normal",
        "market_heat": 0.5,
        "trend_direction": "neutral",
        "estimated_probability": 0.33,
    }
    try:
        from quant_bridge import QuantSignalBridge  # local import: keeps module pure-importable

        bridge = QuantSignalBridge()
        regime_state = await bridge.get_regime_state(prices)
        if not isinstance(regime_state, Mapping):
            regime_state = neutral_state
    except Exception:
        # Degrade to neutral on ANY failure (import/build/call). Never raise.
        regime_state = neutral_state

    return {"regime_state": dict(regime_state), "bias": regime_bias(regime_state)}
