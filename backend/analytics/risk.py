"""Portfolio and position risk metrics — pure, deterministic functions.

Every function here is side-effect free: it takes data IN (numpy arrays,
pandas Series/DataFrames, weight vectors, scalars) and returns numbers or
dicts. No network, no disk, no global state. Data fetching is the caller's
job (the wiring layer).

Conventions
-----------
- **Adjusted close** semantics: callers must pass ADJUSTED-close-derived
  price/return series so that dividends and splits are already accounted
  for. These functions never re-adjust.
- **Completed bars only**: signals/metrics are computed on the clean series
  the caller passes; callers are responsible for dropping the in-progress
  (today's incomplete) bar to avoid look-ahead.
- **Returns** are simple periodic returns (e.g. daily) unless noted. Annualize
  with the `periods` argument (252 trading days by default).

Dependency-light: numpy + pandas + stdlib only.
"""

from __future__ import annotations

from typing import Dict, Iterable, Mapping, Sequence, Union

import numpy as np
import pandas as pd

ArrayLike = Union[Sequence[float], np.ndarray, pd.Series]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _as_array(x: ArrayLike) -> np.ndarray:
    """Coerce a sequence / Series / ndarray to a 1-D float ndarray, dropping NaNs."""
    arr = np.asarray(x, dtype=float).ravel()
    return arr[~np.isnan(arr)]


# ---------------------------------------------------------------------------
# beta
# ---------------------------------------------------------------------------
def beta(asset_returns: ArrayLike, market_returns: ArrayLike) -> float:
    """Market beta of an asset.

    Formula
    -------
        beta = Cov(asset, market) / Var(market)

    This is algebraically identical to the slope of the OLS regression of
    asset returns on market returns. Returns must be aligned and the same
    length (caller aligns dates).

    Parameters
    ----------
    asset_returns, market_returns : array-like
        Aligned simple periodic returns (e.g. daily). Same length.

    Returns
    -------
    float
        Beta. ``nan`` if fewer than 2 paired points or market variance is 0.

    Examples
    --------
    If ``asset = 2 * market`` exactly, beta == 2.0.
    """
    a = np.asarray(asset_returns, dtype=float).ravel()
    m = np.asarray(market_returns, dtype=float).ravel()
    if a.shape != m.shape:
        raise ValueError("asset_returns and market_returns must be the same length")
    mask = ~(np.isnan(a) | np.isnan(m))
    a, m = a[mask], m[mask]
    if a.size < 2:
        return float("nan")
    market_var = np.var(m, ddof=1)
    if market_var == 0:
        return float("nan")
    # ddof cancels in cov/var ratio, but use ddof=1 for both for clarity.
    cov = np.cov(a, m, ddof=1)[0, 1]
    return float(cov / market_var)


# ---------------------------------------------------------------------------
# volatility
# ---------------------------------------------------------------------------
def annualized_volatility(returns: ArrayLike, periods: int = 252) -> float:
    """Annualized volatility (standard deviation of returns scaled by sqrt(periods)).

    Formula
    -------
        sigma_ann = std(returns, ddof=1) * sqrt(periods)

    Parameters
    ----------
    returns : array-like
        Simple periodic returns.
    periods : int
        Periods per year for annualization (252 trading days, 52 weeks, 12 months).

    Returns
    -------
    float
        Annualized volatility. ``nan`` if fewer than 2 observations.
    """
    r = _as_array(returns)
    if r.size < 2:
        return float("nan")
    return float(np.std(r, ddof=1) * np.sqrt(periods))


def portfolio_volatility(weights: ArrayLike, cov_matrix: ArrayLike) -> float:
    """Annualized/periodic portfolio volatility from a full covariance matrix.

    Formula
    -------
        sigma_p = sqrt( w^T * Sigma * w )

    The result is in the same time units as ``cov_matrix``. If the covariance
    matrix is already annualized, the output is annualized; if it is a periodic
    (e.g. daily) covariance, annualize by multiplying the variance by ``periods``
    before the sqrt, or scale the input matrix.

    Parameters
    ----------
    weights : array-like, shape (n,)
        Portfolio weights. Need not sum to 1 (caller's choice), but typically do.
    cov_matrix : array-like, shape (n, n)
        Covariance matrix of asset returns. Accepts a DataFrame.

    Returns
    -------
    float
        Portfolio volatility (sqrt of portfolio variance).
    """
    w = np.asarray(weights, dtype=float).ravel()
    cov = np.asarray(cov_matrix, dtype=float)
    if cov.ndim != 2 or cov.shape[0] != cov.shape[1]:
        raise ValueError("cov_matrix must be square")
    if w.size != cov.shape[0]:
        raise ValueError("weights length must match cov_matrix dimension")
    var = float(w @ cov @ w)
    # Guard tiny negative values from floating-point error.
    return float(np.sqrt(max(var, 0.0)))


def portfolio_volatility_diag(weights: ArrayLike, variances: ArrayLike) -> float:
    """Simplified portfolio volatility assuming ZERO cross-correlation.

    Uses only the diagonal (individual variances); ignores covariances.
    Useful as a quick lower-bound proxy when a full covariance matrix is
    unavailable.

    Formula
    -------
        sigma_p = sqrt( sum_i ( w_i^2 * var_i ) )

    Parameters
    ----------
    weights : array-like, shape (n,)
    variances : array-like, shape (n,)
        Per-asset return variances (diagonal of the covariance matrix).

    Returns
    -------
    float
    """
    w = np.asarray(weights, dtype=float).ravel()
    v = np.asarray(variances, dtype=float).ravel()
    if w.size != v.size:
        raise ValueError("weights and variances must be the same length")
    var = float(np.sum((w ** 2) * v))
    return float(np.sqrt(max(var, 0.0)))


# ---------------------------------------------------------------------------
# value at risk
# ---------------------------------------------------------------------------
def value_at_risk(returns: ArrayLike, conf: float = 0.95) -> Dict[str, float]:
    """Value at Risk (VaR) at a given confidence level, two methods.

    VaR here is reported as a **positive loss magnitude** (a positive number
    means "you can lose this fraction or more with probability 1 - conf").

    Methods
    -------
    historical : empirical percentile
        VaR = -percentile(returns, (1 - conf) * 100)
        i.e. the (1-conf) quantile of the return distribution, sign-flipped.
    parametric : Gaussian / variance-covariance
        VaR = -(mu - z * sigma) = z * sigma - mu
        where z is the standard-normal quantile at ``conf`` and mu, sigma are
        the sample mean and stdev of returns.

    Parameters
    ----------
    returns : array-like
        Simple periodic returns (loss = negative return).
    conf : float
        Confidence level in (0, 1), e.g. 0.95 or 0.99.

    Returns
    -------
    dict
        ``{"historical": float, "parametric": float}`` — positive loss fractions.
    """
    if not (0.0 < conf < 1.0):
        raise ValueError("conf must be in (0, 1)")
    r = _as_array(returns)
    if r.size < 2:
        return {"historical": float("nan"), "parametric": float("nan")}

    alpha = 1.0 - conf
    # Historical: lower-tail empirical quantile, reported as positive loss.
    hist_quantile = np.percentile(r, alpha * 100.0)
    historical = float(-hist_quantile)

    # Parametric (Gaussian). z = inverse-normal CDF at `conf`.
    mu = float(np.mean(r))
    sigma = float(np.std(r, ddof=1))
    z = _norm_ppf(conf)
    parametric = float(z * sigma - mu)

    return {"historical": historical, "parametric": parametric}


def _norm_ppf(p: float) -> float:
    """Inverse standard-normal CDF (quantile function).

    Acklam's rational approximation — accurate to ~1.15e-9, no scipy needed.
    """
    if not (0.0 < p < 1.0):
        raise ValueError("p must be in (0, 1)")
    # Coefficients
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    p_low = 0.02425
    p_high = 1.0 - p_low
    if p < p_low:
        q = np.sqrt(-2.0 * np.log(p))
        return float((((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
                     ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0))
    if p <= p_high:
        q = p - 0.5
        r = q * q
        return float((((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q /
                     (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0))
    q = np.sqrt(-2.0 * np.log(1.0 - p))
    return float(-(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
                 ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0))


# ---------------------------------------------------------------------------
# drawdown
# ---------------------------------------------------------------------------
def max_drawdown(equity_curve: ArrayLike) -> float:
    """Maximum peak-to-trough drawdown of an equity (cumulative value) curve.

    Formula
    -------
        running_peak_t = max(equity[0..t])
        drawdown_t     = equity_t / running_peak_t - 1     (<= 0)
        max_drawdown   = min_t drawdown_t                  (most negative)

    Vectorized via ``np.maximum.accumulate`` (cumulative max).

    Parameters
    ----------
    equity_curve : array-like
        Cumulative portfolio/asset value (NOT returns). Strictly the level
        series, e.g. account value or a cumulative-product growth-of-$1 curve.

    Returns
    -------
    float
        Most-negative drawdown as a fraction, e.g. -0.20 == a 20% drawdown.
        Returns 0.0 for a monotonically non-decreasing curve. ``nan`` if empty.
    """
    eq = _as_array(equity_curve)
    if eq.size == 0:
        return float("nan")
    running_peak = np.maximum.accumulate(eq)
    # Avoid div-by-zero if a peak is 0.
    with np.errstate(divide="ignore", invalid="ignore"):
        drawdowns = np.where(running_peak != 0, eq / running_peak - 1.0, 0.0)
    return float(np.min(drawdowns))


# ---------------------------------------------------------------------------
# risk-adjusted return
# ---------------------------------------------------------------------------
def sharpe(returns: ArrayLike, rf_annual: float = 0.045, periods: int = 252) -> float:
    """Annualized Sharpe ratio.

    Formula
    -------
        rf_per_period = rf_annual / periods
        excess        = returns - rf_per_period
        sharpe        = mean(excess) / std(excess, ddof=1) * sqrt(periods)

    Parameters
    ----------
    returns : array-like
        Simple periodic returns.
    rf_annual : float
        Annual risk-free rate (e.g. 0.045 == 4.5%). De-annualized to per-period.
    periods : int
        Periods per year.

    Returns
    -------
    float
        Annualized Sharpe. ``nan`` if <2 obs or zero excess-return volatility.
    """
    r = _as_array(returns)
    if r.size < 2:
        return float("nan")
    rf_per = rf_annual / periods
    excess = r - rf_per
    sd = np.std(excess, ddof=1)
    if sd == 0:
        return float("nan")
    return float(np.mean(excess) / sd * np.sqrt(periods))


def sortino(returns: ArrayLike, mar: float = 0.0, periods: int = 252) -> float:
    """Annualized Sortino ratio (downside-deviation-adjusted return).

    Formula
    -------
        mar_per_period = mar / periods                  (MAR is given annualized)
        excess         = returns - mar_per_period
        downside       = min(excess, 0)
        downside_dev   = sqrt( mean( downside^2 ) )     (population, includes
                          zeros for up-periods — the standard Sortino convention)
        sortino        = mean(excess) / downside_dev * sqrt(periods)

    Parameters
    ----------
    returns : array-like
        Simple periodic returns.
    mar : float
        Minimum acceptable return, **annualized**. Default 0.0.
    periods : int
        Periods per year.

    Returns
    -------
    float
        Annualized Sortino. ``nan`` if <2 obs or no downside deviation (returns
        ``inf`` if there is positive mean excess but zero downside).
    """
    r = _as_array(returns)
    if r.size < 2:
        return float("nan")
    mar_per = mar / periods
    excess = r - mar_per
    downside = np.minimum(excess, 0.0)
    downside_dev = np.sqrt(np.mean(downside ** 2))
    if downside_dev == 0:
        return float("inf") if np.mean(excess) > 0 else float("nan")
    return float(np.mean(excess) / downside_dev * np.sqrt(periods))


# ---------------------------------------------------------------------------
# correlation
# ---------------------------------------------------------------------------
def correlation_matrix(returns_df: pd.DataFrame) -> pd.DataFrame:
    """Pairwise Pearson correlation matrix of asset returns.

    Rolling-friendly: pass a windowed slice (the audit prescribes a ~1-month
    rolling window, e.g. ``returns_df.tail(21)``), NOT a multi-year history,
    so the matrix reflects the *current* correlation regime.

    Formula
    -------
        rho_ij = Cov(i, j) / (sigma_i * sigma_j)

    Parameters
    ----------
    returns_df : pandas.DataFrame
        Columns = tickers, rows = aligned periodic returns. Uses pairwise-complete
        observations (pandas default), so NaNs are tolerated.

    Returns
    -------
    pandas.DataFrame
        Square symmetric correlation matrix indexed/columned by ticker. Diagonal
        is 1.0.
    """
    if not isinstance(returns_df, pd.DataFrame):
        returns_df = pd.DataFrame(returns_df)
    return returns_df.corr(method="pearson")


# ---------------------------------------------------------------------------
# concentration
# ---------------------------------------------------------------------------
def hhi(weights: ArrayLike) -> float:
    """Herfindahl-Hirschman Index of portfolio concentration.

    Formula
    -------
        HHI = sum_i ( w_i^2 )

    Weights are normalized to sum to 1 first (absolute values used so short
    legs still contribute to concentration). Range: 1/n (perfectly diversified
    across n equal positions) to 1.0 (everything in one name).

    Parameters
    ----------
    weights : array-like
        Portfolio weights. Need not pre-normalize.

    Returns
    -------
    float
        HHI in (0, 1]. ``nan`` if no positive total weight.

    Examples
    --------
    n equal weights -> HHI == 1/n.
    """
    w = np.abs(np.asarray(weights, dtype=float).ravel())
    total = w.sum()
    if total == 0:
        return float("nan")
    w = w / total
    return float(np.sum(w ** 2))


def effective_number(weights: ArrayLike) -> float:
    """Effective number of positions (ENS) = 1 / HHI.

    Interprets concentration as an equivalent count of equal-weight positions.
    For n equal weights, ENS == n. For a fully concentrated book, ENS == 1.

    Parameters
    ----------
    weights : array-like

    Returns
    -------
    float
        Effective number of positions. ``nan`` if HHI is undefined or zero.
    """
    h = hhi(weights)
    if h is None or np.isnan(h) or h == 0:
        return float("nan")
    return float(1.0 / h)


# ---------------------------------------------------------------------------
# sector exposure
# ---------------------------------------------------------------------------
def sector_exposure(positions: Iterable[Mapping]) -> Dict[str, float]:
    """Aggregate portfolio weight by sector.

    Parameters
    ----------
    positions : iterable of mappings
        Each position must expose a ``weight`` (or ``"weight"``) and a
        ``sector`` (or ``"sector"``) key. Missing sector -> "Unknown".
        Weights are summed per sector (not re-normalized — caller decides
        whether inputs already sum to 1).

    Returns
    -------
    dict
        ``{sector: total_weight}``, sorted descending by weight.

    Examples
    --------
    >>> sector_exposure([
    ...     {"sector": "Tech", "weight": 0.4},
    ...     {"sector": "Tech", "weight": 0.2},
    ...     {"sector": "Energy", "weight": 0.4},
    ... ])
    {'Tech': 0.6, 'Energy': 0.4}
    """
    totals: Dict[str, float] = {}
    for pos in positions:
        sector = pos.get("sector") or "Unknown"
        weight = float(pos.get("weight", 0.0) or 0.0)
        totals[sector] = totals.get(sector, 0.0) + weight
    return dict(sorted(totals.items(), key=lambda kv: kv[1], reverse=True))
