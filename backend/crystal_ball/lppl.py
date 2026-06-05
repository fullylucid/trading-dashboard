"""
LPPL — Log-Periodic Power Law Singularity (Johansen–Ledoit–Sornette).

The literal physics-of-crashes model. A bubble is modeled as faster-than-
exponential (super-exponential) growth decorated with accelerating log-periodic
oscillations, terminating at a critical time ``tc`` — the most-probable moment of
a regime change (crash for a bubble, rebound for an "anti-bubble"):

    ln p(t) = A + B (tc - t)^m + C (tc - t)^m cos( ω ln(tc - t) - φ )

with 0 < m < 1 (super-exponential), ω the log-periodic angular frequency, and
B < 0 for a bubble (price accelerating up toward the singularity).

HONESTY WARNING (and the reason this whole tab exists): a naive LPPL fit will
"find" a critical time in pure noise — it is one of the most overfit-prone models
in quantitative finance. So we do NOT trust a fit just because it converged. We
apply the standard JLS qualification filters (Sornette/Filimonov):

    - 0.1 <= m <= 0.9
    - 4   <= ω <= 15
    - B < 0 (genuine super-exponential bubble) for a TOP call
    - damping  D = (m |B|) / (ω |C|) >= 0.8   (oscillations don't dominate trend)
    - tc within a sane forward window (not absurdly far out)
    - the fit must beat a plain power-law / linear benchmark on R²

Only a fit that passes ALL filters is reported as a signal; everything else is
"no qualified LPPL bubble". And the only thing that actually decides whether this
adds value is the backtester — see crystal_ball.backtest.

Pure numpy/scipy. The nonlinear search is over just (tc, m, ω); the linear
parameters (A, B, C1, C2) are solved by least squares for each candidate
(the standard "slaving" of the linear subproblem), which makes the fit far more
stable than optimizing all 7 parameters jointly.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import numpy as np


# Qualification ranges (JLS / Filimonov-Sornette typical bounds).
_M_LO, _M_HI = 0.1, 0.9
_W_LO, _W_HI = 4.0, 15.0
_DAMPING_MIN = 0.8


def _linear_fit(t: np.ndarray, y: np.ndarray, tc: float, m: float, w: float
                ) -> Optional[Tuple[np.ndarray, float]]:
    """Solve the linear subproblem (A,B,C1,C2) for fixed (tc,m,w); return (params, sse).

    Design columns: 1, f=(tc-t)^m, g=f*cos(w ln(tc-t)), h=f*sin(w ln(tc-t)).
    Returns None if the configuration is degenerate (tc must exceed all t).
    """
    dt = tc - t
    if np.any(dt <= 1e-6):
        return None
    f = np.power(dt, m)
    ln_dt = np.log(dt)
    g = f * np.cos(w * ln_dt)
    h = f * np.sin(w * ln_dt)
    X = np.column_stack([np.ones_like(t), f, g, h])
    try:
        beta, _res, _rank, _sv = np.linalg.lstsq(X, y, rcond=None)
    except np.linalg.LinAlgError:
        return None
    resid = y - X @ beta
    sse = float(resid @ resid)
    if not np.isfinite(sse):
        return None
    return beta, sse


def fit_lppl(log_price, max_forward_frac: float = 0.2, fast: bool = False) -> Dict[str, Any]:
    """Fit the LPPL model to a log-price window and qualify it.

    Time is indexed 0..N-1 (bars). ``tc`` is searched from just past the window
    end out to ``N * (1 + max_forward_frac)`` — i.e. the critical time may lie up
    to ~20% of the window length into the future. Linear params are slaved; the
    (tc, m, w) grid is coarse then locally refined.

    Returns a dict with the best fit, its R², the derived (B, C, damping, tc in
    bars-from-now), and ``qualified`` — True only if every JLS filter passes.
    """
    y = np.asarray(log_price, dtype=float).ravel()
    y = y[np.isfinite(y)]
    n = y.size
    skeleton = {"qualified": False, "r_squared": None, "tc_bars_ahead": None,
                "m": None, "omega": None, "B": None, "damping": None,
                "kind": None, "reason": "insufficient data"}
    if n < 60:
        return skeleton

    t = np.arange(n, dtype=float)
    sst = float(np.sum((y - y.mean()) ** 2)) or 1e-12

    # --- coarse grid over the nonlinear params (sparser in fast/backtest mode) ---
    n_tc, n_m, n_w = (8, 5, 7) if fast else (14, 9, 12)
    tc_grid = np.linspace(n + 1.0, n * (1.0 + max_forward_frac), n_tc)
    m_grid = np.linspace(_M_LO, _M_HI, n_m)
    w_grid = np.linspace(_W_LO, _W_HI, n_w)

    best = None  # (sse, tc, m, w, beta)
    for tc in tc_grid:
        for m in m_grid:
            for w in w_grid:
                r = _linear_fit(t, y, tc, m, w)
                if r is None:
                    continue
                beta, sse = r
                if best is None or sse < best[0]:
                    best = (sse, tc, m, w, beta)
    if best is None:
        return {**skeleton, "reason": "no convergent fit"}

    # --- local refine around the grid optimum (Nelder-Mead on tc,m,w) ---
    # Skipped in fast mode (per-bar backtest) where the grid alone is good enough.
    if not fast:
        sse0, tc0, m0, w0, beta0 = best
        refined = _refine(t, y, tc0, m0, w0)
        if refined is not None:
            best = refined

    sse, tc, m, w, beta = best
    r2 = 1.0 - sse / sst
    A, B, C1, C2 = (float(beta[0]), float(beta[1]), float(beta[2]), float(beta[3]))
    C = float(np.hypot(C1, C2))
    damping = (m * abs(B)) / (w * abs(C)) if (w > 0 and abs(C) > 1e-12) else np.inf
    tc_ahead = float(tc - (n - 1))

    # --- qualification filters ---
    reasons = []
    if not (_M_LO <= m <= _M_HI):
        reasons.append(f"m={m:.2f} out of [0.1,0.9]")
    if not (_W_LO <= w <= _W_HI):
        reasons.append(f"omega={w:.1f} out of [4,15]")
    if damping < _DAMPING_MIN:
        reasons.append(f"damping={damping:.2f}<0.8")
    if r2 < 0.8:
        reasons.append(f"R2={r2:.2f}<0.8")
    # B<0 -> bubble (super-exponential up) -> TOP risk; B>0 -> anti-bubble -> BOTTOM.
    kind = "bubble_top" if B < 0 else "antibubble_bottom"
    qualified = len(reasons) == 0

    return {
        "qualified": bool(qualified),
        "r_squared": round(r2, 4),
        "tc_bars_ahead": round(tc_ahead, 1),
        "m": round(m, 3),
        "omega": round(w, 2),
        "B": round(B, 5),
        "C": round(C, 5),
        "damping": round(float(damping), 3) if np.isfinite(damping) else None,
        "kind": kind,
        "reason": "qualified" if qualified else "; ".join(reasons),
    }


def _refine(t, y, tc0, m0, w0):
    """Local Nelder-Mead refine of (tc,m,w); returns (sse,tc,m,w,beta) or None."""
    try:
        from scipy.optimize import minimize
    except Exception:  # pragma: no cover
        return None
    n = t.size

    def obj(params):
        tc, m, w = params
        if not (n + 0.5 <= tc <= n * 1.5) or not (0.05 <= m <= 0.95) or not (2.0 <= w <= 18.0):
            return 1e18
        r = _linear_fit(t, y, tc, m, w)
        return r[1] if r is not None else 1e18

    try:
        res = minimize(obj, x0=[tc0, m0, w0], method="Nelder-Mead",
                       options={"maxiter": 300, "xatol": 1e-3, "fatol": 1e-6})
    except Exception:  # noqa: BLE001
        return None
    if not res.success and res.fun >= 1e17:
        return None
    tc, m, w = res.x
    r = _linear_fit(t, y, tc, m, w)
    if r is None:
        return None
    beta, sse = r
    return (sse, float(tc), float(m), float(w), beta)


def lppl_signal(close, horizon: int = 15, window: int = 250, fast: bool = False) -> Dict[str, Any]:
    """Uniform reversal-signal dict from a qualified LPPL fit (for fusion/backtest).

    Fires only when a QUALIFIED bubble/anti-bubble fit places the critical time
    within ``horizon`` bars ahead. Strength scales with fit quality (R²) and how
    imminent ``tc`` is. ``vote``: bubble_top -> "top", antibubble_bottom -> "bottom".
    """
    c = np.asarray(close, dtype=float).ravel()
    c = c[np.isfinite(c)]
    base = {"name": "lppl", "label": "LPPL Singularity", "weight": 0.9}
    if c.size < 80:
        return {**base, "value": "n/a", "vote": "none", "strength": 0.0,
                "note": "Not enough data for an LPPL fit."}
    win = np.log(c[-window:]) if c.size > window else np.log(c)
    fit = fit_lppl(win, fast=fast)
    if not fit["qualified"]:
        return {**base, "value": "unqualified", "vote": "none", "strength": 0.0,
                "note": f"No qualified LPPL bubble ({fit['reason']})."}
    tc_ahead = fit["tc_bars_ahead"] or 1e9
    if tc_ahead < 0 or tc_ahead > horizon:
        return {**base, "value": f"tc {tc_ahead:.0f}b", "vote": "none", "strength": 0.0,
                "note": f"Qualified {fit['kind']} but critical time {tc_ahead:.0f} bars out (beyond {horizon})."}
    vote = "top" if fit["kind"] == "bubble_top" else "bottom"
    imminence = float(np.clip(1.0 - tc_ahead / max(1, horizon), 0.0, 1.0))
    quality = float(np.clip((fit["r_squared"] - 0.8) / 0.2, 0.0, 1.0))
    strength = round(float(np.clip(0.5 * imminence + 0.5 * quality, 0.0, 1.0)), 3)
    arrow = "top (crash risk)" if vote == "top" else "bottom (rebound)"
    return {**base, "value": f"tc≈{tc_ahead:.0f}b R²={fit['r_squared']:.2f}",
            "vote": vote, "strength": strength,
            "note": f"LPPL {fit['kind']} → critical time ≈{tc_ahead:.0f} bars ({arrow})."}
