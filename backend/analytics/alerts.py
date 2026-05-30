"""Multi-signal alert ranking, what-if scenarios, and rebalancing flags. PURE.

This is the Phase-3 *actionability* layer. It consumes the analytics blocks the
rest of the pipeline already produces (the per-ticker ``signals`` / ``insider``
sub-blocks, the payload-level ``regime`` block, the per-ticker risk fields, and
the per-holding ``sector_rotation`` tag) and fuses them into a single ranked
read per ticker:

    score_alert(...) -> {
        "bucket": "alert" | "watch" | "log",     # >=80 / 60-79 / <60
        "confidence": float,                      # 0..100 confluence score
        "direction": "bullish" | "bearish" | "neutral",
        "contributing_factors": [ {factor, detail, points, direction}, ... ],
        "score_breakdown": {...},
    }

Plus two portfolio-scenario helpers that operate purely on the additive
``portfolio_risk`` block (the output of ``scan_analytics.portfolio_risk``):

    what_if_add(portfolio_risk, new_position)     -> incremental beta / VaR /
                                                     concentration (HHI/ENS) deltas
    rebalancing_suggestions(portfolio_risk)       -> trim / diversify / correlation-
                                                     redundancy flags

Design rules (matching the rest of backend/analytics/*):
- **PURE / deterministic**: numpy + stdlib only. No network, no disk, no global
  state. Inputs are the already-computed analytics dicts; outputs are dicts.
- **Tolerant**: every input field is optional. Missing data simply contributes
  no points (it never raises). A ticker with no analytics scores 0 / "log".
- **Bounded**: confidence is clamped to [0, 100]; the bucket thresholds match
  Tradeskeebot's standard 80 / 60 alert grades (mirrors
  ``insider.score_insider_signal``).

Scoring philosophy
------------------
Confluence, not a single oracle. Each independent evidence stream contributes a
bounded number of points toward a *directional* conviction. Bullish streams add
to the bullish tally; bearish streams add to the bearish tally. The dominant
side's tally (capped at 100) is the ``confidence``; ``direction`` is whichever
side won. This means a name only reaches "alert" (>=80) when *several*
independent signals agree — exactly the multi-signal confirmation a swing trader
wants before acting, and the opposite of the deleted PRNG scanners that fired on
one fabricated number.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

import numpy as np

__all__ = [
    "score_alert",
    "what_if_add",
    "rebalancing_suggestions",
    "ALERT_THRESHOLD",
    "WATCH_THRESHOLD",
]

# Standard Tradeskeebot buckets (mirror insider.score_insider_signal).
ALERT_THRESHOLD = 80.0
WATCH_THRESHOLD = 60.0

# Maximum points any single stream can add to one directional tally. Keeps a
# single loud signal from single-handedly producing an "alert" — confluence is
# required.
_MAX_PER_FACTOR = 30.0


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _num(x: Any) -> Optional[float]:
    """Coerce to a finite float, else None."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def _bucket(confidence: float) -> str:
    """Map a 0..100 confidence to the standard alert/watch/log bucket."""
    if confidence >= ALERT_THRESHOLD:
        return "alert"
    if confidence >= WATCH_THRESHOLD:
        return "watch"
    return "log"


def _cap(points: float) -> float:
    """Clamp a single factor's contribution to [0, _MAX_PER_FACTOR]."""
    return float(max(0.0, min(_MAX_PER_FACTOR, points)))


# --------------------------------------------------------------------------- #
# per-ticker alert scoring
# --------------------------------------------------------------------------- #
def score_alert(
    *,
    symbol: Optional[str] = None,
    signals: Optional[Mapping[str, Any]] = None,
    insider: Optional[Mapping[str, Any]] = None,
    regime: Optional[Mapping[str, Any]] = None,
    risk: Optional[Mapping[str, Any]] = None,
    sector_rotation: Optional[Mapping[str, Any]] = None,
    composite_score: Optional[float] = None,
) -> Dict[str, Any]:
    """Fuse a ticker's analytics into a ranked, directional confluence alert.

    Each evidence stream contributes bounded points to a *bullish* or *bearish*
    tally. The winning side's capped tally is the ``confidence``; the bucket is
    ``alert`` (>=80) / ``watch`` (60-79) / ``log`` (<60).

    Parameters
    ----------
    symbol : str, optional
        Echoed back into the result for convenience (ranking / display).
    signals : mapping, optional
        The per-ticker ``signals`` sub-block (``rsi``, ``macd``, ``divergence``,
        ``ma_structure``, ``roc``, ``relative_strength``, ``rvol``,
        ``pct_of_52w_range``, ``days_to_earnings``). All fields optional.
    insider : mapping, optional
        The per-ticker ``insider`` sub-block (``has_cluster``, ``confidence``,
        ``num_insiders``, ``total_value``). Open-market Form-4 buy clusters are
        a bullish smart-money tell.
    regime : mapping, optional
        The payload-level ``regime`` block (``regime_class`` in
        uptrend/choppy/downtrend/neutral). Acts as a directional *tilt* — a
        bullish setup in a downtrend regime is discounted, and vice-versa.
    risk : mapping, optional
        The per-ticker risk fields from the ``analytics`` block — notably
        ``unrealized_r`` (R-multiple) and ``distance_to_stop_pct``. A position
        already deep in profit (high R) is a momentum confirmation; a position
        sitting on / through its stop is a bearish risk flag.
    sector_rotation : mapping, optional
        The per-holding ``sector_rotation`` tag (``status`` rotating-IN /
        rotating-OUT, ``rotation_score``). Rotating-IN = tailwind (bullish),
        rotating-OUT = headwind (bearish).
    composite_score : float, optional
        Charlotte's existing 0-10 composite verdict, folded in as a mild
        confirming/contradicting nudge (>=7 bullish, <=3 bearish).

    Returns
    -------
    dict
        ``{"symbol", "bucket", "confidence", "direction",
           "contributing_factors": [ {factor, detail, points, direction} ],
           "score_breakdown": {"bullish": float, "bearish": float}}``.

    Notes
    -----
    Deterministic and side-effect free. Absent inputs contribute nothing; a
    fully-empty call yields ``confidence == 0`` / ``"log"`` / ``"neutral"``.
    """
    sig = dict(signals) if isinstance(signals, Mapping) else {}
    ins = dict(insider) if isinstance(insider, Mapping) else {}
    reg = dict(regime) if isinstance(regime, Mapping) else {}
    rsk = dict(risk) if isinstance(risk, Mapping) else {}
    rot = dict(sector_rotation) if isinstance(sector_rotation, Mapping) else {}

    factors: List[Dict[str, Any]] = []
    bullish = 0.0
    bearish = 0.0

    def _add(factor: str, detail: str, points: float, direction: str) -> None:
        nonlocal bullish, bearish
        pts = _cap(points)
        if pts <= 0:
            return
        factors.append(
            {"factor": factor, "detail": detail, "points": round(pts, 2), "direction": direction}
        )
        if direction == "bullish":
            bullish += pts
        elif direction == "bearish":
            bearish += pts

    # --- Momentum: rate-of-change (1-month) ---
    roc = _num(sig.get("roc"))
    if roc is not None:
        if roc >= 5.0:
            _add("momentum", f"ROC(21) +{roc:.1f}%", min(roc, 20.0) * 0.9, "bullish")
        elif roc <= -5.0:
            _add("momentum", f"ROC(21) {roc:.1f}%", min(abs(roc), 20.0) * 0.9, "bearish")

    # --- Relative strength vs SPY ---
    rs = _num(sig.get("relative_strength"))
    if rs is not None:
        if rs >= 3.0:
            _add("relative_strength", f"+{rs:.1f}pp vs SPY", min(rs, 15.0) * 1.2, "bullish")
        elif rs <= -3.0:
            _add("relative_strength", f"{rs:.1f}pp vs SPY", min(abs(rs), 15.0) * 1.2, "bearish")

    # --- RSI: overbought / oversold extremes ---
    rsi = _num(sig.get("rsi"))
    if rsi is not None:
        if rsi <= 30.0:
            _add("rsi_oversold", f"RSI {rsi:.0f} (oversold)", (35.0 - rsi) * 1.5, "bullish")
        elif rsi >= 70.0:
            _add("rsi_overbought", f"RSI {rsi:.0f} (overbought)", (rsi - 65.0) * 1.2, "bearish")

    # --- MACD histogram sign (momentum confirmation) ---
    macd = sig.get("macd")
    if isinstance(macd, Mapping):
        hist = _num(macd.get("hist"))
        if hist is not None:
            if hist > 0:
                _add("macd", "MACD histogram positive", 10.0, "bullish")
            elif hist < 0:
                _add("macd", "MACD histogram negative", 10.0, "bearish")

    # --- Divergence (leading reversal warning) ---
    div = sig.get("divergence")
    if div == "bullish":
        _add("divergence", "bullish RSI divergence", 14.0, "bullish")
    elif div == "bearish":
        _add("divergence", "bearish RSI divergence", 14.0, "bearish")

    # --- Moving-average structure ---
    ma = sig.get("ma_structure")
    if isinstance(ma, Mapping):
        if ma.get("golden_cross") is True:
            _add("ma_structure", "golden cross (50>200)", 18.0, "bullish")
        elif ma.get("death_cross") is True:
            _add("ma_structure", "death cross (50<200)", 18.0, "bearish")
        elif ma.get("stacked_bullish") is True:
            _add("ma_structure", "price > MA50 > MA200 (stacked)", 12.0, "bullish")
        elif ma.get("above_200") is False:
            _add("ma_structure", "below 200-day MA", 10.0, "bearish")

    # --- Relative volume (conviction multiplier on a directional move) ---
    rvol = _num(sig.get("rvol"))
    if rvol is not None and rvol >= 1.5:
        # RVOL confirms whichever side currently leads; if neutral so far, treat
        # as a mild bullish accumulation tell (volume-led breakouts).
        side = "bullish" if bullish >= bearish else "bearish"
        _add("rvol", f"RVOL {rvol:.1f}x (volume surge)", min(rvol, 4.0) * 4.0, side)

    # --- 52-week range position ---
    pct52 = _num(sig.get("pct_of_52w_range"))
    if pct52 is not None:
        if pct52 >= 90.0:
            _add("range_52w", f"{pct52:.0f}% of 52w range (near highs)", 8.0, "bullish")
        elif pct52 <= 10.0:
            _add("range_52w", f"{pct52:.0f}% of 52w range (near lows)", 8.0, "bearish")

    # --- Insider open-market buy cluster (smart money) ---
    if ins:
        ins_conf = _num(ins.get("confidence"))
        if ins.get("has_cluster") and ins_conf is not None and ins_conf > 0:
            n_ins = ins.get("num_insiders")
            detail = f"Form-4 buy cluster ({n_ins} insiders)" if n_ins else "Form-4 buy cluster"
            # Scale the insider 0..100 confidence into this layer's point budget.
            _add("insider_cluster", detail, ins_conf * 0.25, "bullish")

    # --- Risk geometry (R-multiple + distance to stop) ---
    if rsk:
        ur = _num(rsk.get("unrealized_r"))
        if ur is not None:
            if ur >= 1.0:
                _add("risk_geometry", f"+{ur:.1f}R in profit", min(ur, 4.0) * 4.0, "bullish")
            elif ur <= -0.5:
                _add("risk_geometry", f"{ur:.1f}R (through/near stop)", min(abs(ur), 1.0) * 20.0, "bearish")

    # --- Sector rotation tailwind / headwind ---
    if rot:
        status = str(rot.get("status") or "").lower()
        rscore = _num(rot.get("rotation_score"))
        if "in" in status and "out" not in status:  # rotating-in
            pts = (abs(rscore) * 0.2) if rscore is not None else 10.0
            _add("sector_rotation", "sector rotating IN (tailwind)", max(pts, 8.0), "bullish")
        elif "out" in status:  # rotating-out
            pts = (abs(rscore) * 0.2) if rscore is not None else 10.0
            _add("sector_rotation", "sector rotating OUT (headwind)", max(pts, 8.0), "bearish")

    # --- Charlotte composite verdict (mild confirmation) ---
    comp = _num(composite_score)
    if comp is not None:
        if comp >= 7.0:
            _add("composite", f"composite {comp:.1f}/10", (comp - 6.0) * 4.0, "bullish")
        elif comp <= 3.0:
            _add("composite", f"composite {comp:.1f}/10", (4.0 - comp) * 4.0, "bearish")

    # --- Regime tilt: discount conviction that fights the market regime ---
    regime_class = str(reg.get("regime_class") or "").lower()
    if regime_class == "downtrend":
        bullish *= 0.7  # fade longs in a downtrend
    elif regime_class == "uptrend":
        bearish *= 0.7  # fade shorts in an uptrend
    if regime_class:
        factors.append(
            {
                "factor": "regime",
                "detail": f"market regime: {regime_class}",
                "points": 0.0,
                "direction": "context",
            }
        )

    bullish = float(min(100.0, bullish))
    bearish = float(min(100.0, bearish))

    if bullish > bearish:
        direction = "bullish"
        confidence = bullish
    elif bearish > bullish:
        direction = "bearish"
        confidence = bearish
    else:
        direction = "neutral"
        confidence = bullish  # == bearish; could be 0

    confidence = round(float(max(0.0, min(100.0, confidence))), 2)

    # Order factors by contribution (context rows last).
    factors.sort(key=lambda f: f.get("points", 0.0), reverse=True)

    return {
        "symbol": symbol,
        "bucket": _bucket(confidence),
        "confidence": confidence,
        "direction": direction,
        "contributing_factors": factors,
        "score_breakdown": {"bullish": round(bullish, 2), "bearish": round(bearish, 2)},
    }


# --------------------------------------------------------------------------- #
# what-if: incremental impact of adding a new position
# --------------------------------------------------------------------------- #
def what_if_add(
    portfolio_risk: Optional[Mapping[str, Any]],
    new_position: Mapping[str, Any],
) -> Dict[str, Any]:
    """Incremental risk deltas from adding a hypothetical new position. PURE.

    Computes the change in portfolio **beta**, **concentration** (HHI / effective
    number of positions), and a first-order **VaR** estimate when ``new_position``
    of a given dollar amount is added on top of the current book described by the
    additive ``portfolio_risk`` block.

    The math is the standard re-weighting identity. Let the current book have
    value ``V0`` with weights ``w_i`` (from ``portfolio_risk["weights"]``) and a
    new name of value ``a`` be added, so the new total is ``V1 = V0 + a`` and the
    new weight of the added name is ``wa = a / V1`` with every existing weight
    scaled by ``V0 / V1``.

    - **beta**: ``beta_new = (1 - wa) * beta_old + wa * beta_added`` where
      ``beta_old`` is the book beta and ``beta_added`` is the new name's beta
      (defaults to 1.0 if unknown — a neutral market assumption).
    - **HHI / ENS**: recomputed from the re-weighted weight vector.
    - **VaR (parametric, first-order)**: scaled by the beta ratio as a quick
      proxy (``var_new ≈ var_old * |beta_new / beta_old|``) when a book VaR is
      present. This is a deliberately simple, transparent estimate — a true
      re-derivation needs the new name's return series, which is not in the
      block.

    Parameters
    ----------
    portfolio_risk : mapping or None
        The additive ``portfolio_risk`` block (needs ``weights``; optionally
        ``beta_to_spy``, ``per_holding_beta``, ``var_95``). ``None``/empty →
        the new position becomes 100% of a fresh book.
    new_position : mapping
        ``{"symbol": str, "market_value": float, "beta": float (optional)}``.
        ``market_value`` is the dollar amount to add (required, > 0).

    Returns
    -------
    dict
        ``{"symbol", "added_value", "new_portfolio_value", "new_weight",
           "beta": {before, after, delta},
           "hhi": {before, after, delta},
           "effective_number": {before, after, delta},
           "var_95_parametric": {before, after, delta} | None,
           "concentration_flag": bool, "notes": [...]}``.
        ``concentration_flag`` is True when the added name would exceed 20% of
        the book or push HHI up materially.

    Notes
    -----
    Deterministic, no IO. Never raises on missing fields — unknown betas default
    to 1.0 and absent VaR yields a ``None`` VaR delta.
    """
    pr = dict(portfolio_risk) if isinstance(portfolio_risk, Mapping) else {}
    notes: List[str] = []

    sym = str(new_position.get("symbol") or "NEW").upper()
    added = _num(new_position.get("market_value")) or 0.0
    if added <= 0:
        return {
            "symbol": sym,
            "error": "new_position market_value must be > 0",
            "added_value": added,
        }

    # Reconstruct current absolute weights -> dollar values via the weight map.
    weights_map = pr.get("weights") if isinstance(pr.get("weights"), Mapping) else {}
    cur_weights: Dict[str, float] = {}
    for k, v in (weights_map or {}).items():
        fv = _num(v)
        if fv is not None and fv > 0:
            cur_weights[str(k).upper()] = fv
    w_total = sum(cur_weights.values())

    # Normalize existing weights (defensive: they should already ~sum to 1).
    if w_total > 0:
        cur_weights = {k: v / w_total for k, v in cur_weights.items()}

    # Treat the current book as value 1.0 (relative); the added name is `wa`.
    # V0 = 1 (in weight space); a_weight_units = added / V0_dollars is unknown,
    # so we let the caller's `added` be a FRACTION-of-current-book amount when no
    # absolute book value is available. If portfolio_value is present, use it.
    v0 = _num(pr.get("portfolio_value"))
    if v0 is not None and v0 > 0:
        v1 = v0 + added
        wa = added / v1
    else:
        # No absolute book value: interpret `added` as a dollar amount and the
        # current book as unknown size -> fall back to treating `added` relative
        # to an implied book of 1.0 only if weights exist; otherwise 100%.
        if cur_weights:
            # Assume current book == $1 unit; caller passed `added` in same units.
            v0 = 1.0
            v1 = v0 + added
            wa = added / v1
            notes.append("no portfolio_value: treated current book as 1.0 unit; "
                         "added interpreted in the same units")
        else:
            v0 = 0.0
            v1 = added
            wa = 1.0
            notes.append("empty current book: new position is 100% of portfolio")

    # New weight vector: existing names scaled by (1 - wa), plus the new name.
    new_weights: Dict[str, float] = {k: v * (1.0 - wa) for k, v in cur_weights.items()}
    new_weights[sym] = new_weights.get(sym, 0.0) + wa

    # --- concentration: HHI + ENS, before vs after ---
    def _hhi(wmap: Mapping[str, float]) -> Optional[float]:
        vals = np.array([float(x) for x in wmap.values()], dtype=float)
        tot = vals.sum()
        if tot <= 0:
            return None
        vals = vals / tot
        return float(np.sum(vals ** 2))

    hhi_before = _num(pr.get("hhi"))
    if hhi_before is None:
        hhi_before = _hhi(cur_weights)
    hhi_after = _hhi(new_weights)

    ens_before = (1.0 / hhi_before) if (hhi_before and hhi_before > 0) else None
    ens_after = (1.0 / hhi_after) if (hhi_after and hhi_after > 0) else None

    # --- beta: re-weighted book beta ---
    beta_old = _num(pr.get("beta_to_spy"))
    per_beta = pr.get("per_holding_beta") if isinstance(pr.get("per_holding_beta"), Mapping) else {}
    beta_added = _num(new_position.get("beta"))
    if beta_added is None:
        # Use the name's existing per-holding beta if it's already in the book.
        beta_added = _num((per_beta or {}).get(sym))
    if beta_added is None:
        beta_added = 1.0
        notes.append(f"{sym} beta unknown -> assumed market beta 1.0")

    beta_after: Optional[float]
    if beta_old is not None:
        beta_after = (1.0 - wa) * beta_old + wa * beta_added
    else:
        beta_after = beta_added if wa >= 1.0 else None
        if beta_after is None:
            notes.append("book beta unknown -> beta delta unavailable")

    # --- VaR (parametric) first-order scaling by beta ratio ---
    var_block = pr.get("var_95") if isinstance(pr.get("var_95"), Mapping) else {}
    var_before = _num((var_block or {}).get("parametric"))
    var_after: Optional[float] = None
    if var_before is not None and beta_old not in (None, 0) and beta_after is not None:
        try:
            var_after = var_before * abs(beta_after / beta_old)
        except ZeroDivisionError:  # pragma: no cover - guarded above
            var_after = None
    if var_before is not None and var_after is None:
        notes.append("VaR delta needs a non-zero book beta -> unavailable")

    def _delta(before: Optional[float], after: Optional[float]) -> Optional[Dict[str, Any]]:
        if before is None and after is None:
            return None
        d = None
        if before is not None and after is not None:
            d = after - before
        return {
            "before": None if before is None else round(before, 6),
            "after": None if after is None else round(after, 6),
            "delta": None if d is None else round(d, 6),
        }

    concentration_flag = bool(wa >= 0.20) or bool(
        hhi_before is not None and hhi_after is not None and hhi_after - hhi_before >= 0.05
    )
    if wa >= 0.20:
        notes.append(f"{sym} would be {wa * 100:.0f}% of the book (>=20% concentration)")

    return {
        "symbol": sym,
        "added_value": round(added, 4),
        "new_portfolio_value": round(v1, 4),
        "new_weight": round(wa, 6),
        "beta": _delta(beta_old, beta_after),
        "hhi": _delta(hhi_before, hhi_after),
        "effective_number": _delta(ens_before, ens_after),
        "var_95_parametric": _delta(var_before, var_after),
        "concentration_flag": concentration_flag,
        "notes": notes,
    }


# --------------------------------------------------------------------------- #
# rebalancing suggestions
# --------------------------------------------------------------------------- #
def rebalancing_suggestions(
    portfolio_risk: Optional[Mapping[str, Any]],
    *,
    max_position_weight: float = 0.25,
    min_effective_number: float = 5.0,
    high_corr_threshold: float = 0.80,
) -> Dict[str, Any]:
    """Trim / diversify / correlation-redundancy flags from the risk block. PURE.

    Inspects the additive ``portfolio_risk`` block and emits actionable flags:

    - **trim**: any single position whose weight exceeds ``max_position_weight``
      (default 25%) — oversized concentration risk.
    - **diversify**: the book's effective number of positions (1/HHI) is below
      ``min_effective_number`` (default 5) — too few effective bets.
    - **correlation_redundancy**: any pair of holdings whose rolling correlation
      meets/exceeds ``high_corr_threshold`` (default 0.80) — they are largely the
      same bet, so they double risk without diversifying. Each redundant pair is
      reported with the lower-weight name suggested for trimming.

    Parameters
    ----------
    portfolio_risk : mapping or None
        The additive ``portfolio_risk`` block (uses ``weights``,
        ``effective_number``/``hhi``, ``correlation_matrix``). ``None``/empty →
        no flags.
    max_position_weight : float, default 0.25
    min_effective_number : float, default 5.0
    high_corr_threshold : float, default 0.80

    Returns
    -------
    dict
        ``{"flags": [ {type, ...} ], "summary": str,
           "metrics": {largest_position, largest_weight, effective_number,
                       hhi, num_holdings}}``.
        ``flags`` is empty when the book is already well-balanced.

    Notes
    -----
    Deterministic, no IO. Tolerant of missing sub-blocks — each check is skipped
    when its inputs are absent.
    """
    pr = dict(portfolio_risk) if isinstance(portfolio_risk, Mapping) else {}
    flags: List[Dict[str, Any]] = []

    weights_map = pr.get("weights") if isinstance(pr.get("weights"), Mapping) else {}
    weights: Dict[str, float] = {}
    for k, v in (weights_map or {}).items():
        fv = _num(v)
        if fv is not None:
            weights[str(k).upper()] = fv

    # --- trim: oversized single positions ---
    largest_sym: Optional[str] = None
    largest_w: Optional[float] = None
    if weights:
        largest_sym, largest_w = max(weights.items(), key=lambda kv: kv[1])
        for sym, w in sorted(weights.items(), key=lambda kv: kv[1], reverse=True):
            if w >= max_position_weight:
                flags.append(
                    {
                        "type": "trim",
                        "symbol": sym,
                        "weight": round(w, 4),
                        "threshold": max_position_weight,
                        "detail": f"{sym} is {w * 100:.0f}% of the book "
                                  f"(>= {max_position_weight * 100:.0f}% cap) — consider trimming",
                    }
                )

    # --- diversify: too few effective positions ---
    ens = _num(pr.get("effective_number"))
    hhi_val = _num(pr.get("hhi"))
    if ens is None and hhi_val is not None and hhi_val > 0:
        ens = 1.0 / hhi_val
    if ens is not None and ens < min_effective_number:
        flags.append(
            {
                "type": "diversify",
                "effective_number": round(ens, 3),
                "threshold": min_effective_number,
                "detail": f"effective number of positions is {ens:.1f} "
                          f"(< {min_effective_number:.0f}) — book is concentrated; add uncorrelated names",
            }
        )

    # --- correlation redundancy: highly-correlated pairs ---
    corr = pr.get("correlation_matrix") if isinstance(pr.get("correlation_matrix"), Mapping) else {}
    seen_pairs = set()
    redundant: List[Dict[str, Any]] = []
    for i, row in (corr or {}).items():
        if not isinstance(row, Mapping):
            continue
        for j, val in row.items():
            if str(i).upper() == str(j).upper():
                continue
            key = tuple(sorted((str(i).upper(), str(j).upper())))
            if key in seen_pairs:
                continue
            c = _num(val)
            if c is not None and c >= high_corr_threshold:
                seen_pairs.add(key)
                a, b = key
                wa = weights.get(a)
                wb = weights.get(b)
                # Suggest trimming the smaller-weight (or, ties, second) name.
                if wa is not None and wb is not None:
                    trim = a if wa <= wb else b
                elif wa is not None:
                    trim = b
                elif wb is not None:
                    trim = a
                else:
                    trim = b
                pair_entry = {
                    "type": "correlation_redundancy",
                    "pair": [a, b],
                    "correlation": round(c, 4),
                    "threshold": high_corr_threshold,
                    "suggested_trim": trim,
                    "detail": f"{a} and {b} are {c * 100:.0f}% correlated "
                              f"(>= {high_corr_threshold * 100:.0f}%) — redundant exposure; "
                              f"consider trimming {trim}",
                }
                redundant.append(pair_entry)
    # Most-correlated pairs first.
    redundant.sort(key=lambda f: f.get("correlation", 0.0), reverse=True)
    flags.extend(redundant)

    num_holdings = len(weights) if weights else (
        len(pr.get("holdings_used")) if isinstance(pr.get("holdings_used"), list) else 0
    )

    if not flags:
        summary = "Book looks balanced — no trim/diversify/redundancy flags."
    else:
        kinds = sorted({f["type"] for f in flags})
        summary = f"{len(flags)} rebalancing flag(s): {', '.join(kinds)}."

    return {
        "flags": flags,
        "summary": summary,
        "metrics": {
            "largest_position": largest_sym,
            "largest_weight": None if largest_w is None else round(largest_w, 4),
            "effective_number": None if ens is None else round(ens, 3),
            "hhi": None if hhi_val is None else round(hhi_val, 4),
            "num_holdings": num_holdings,
        },
    }
