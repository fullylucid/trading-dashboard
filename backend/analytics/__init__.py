"""Pure, deterministic, dependency-light trading analytics.

Every function in this package takes data IN (numpy arrays, pandas Series,
weights, scalars) and returns numbers / dicts. There is NO network or disk
I/O inside these functions — data fetching is the caller's job. Signals are
computed on completed bars only (callers pass clean, already-completed series)
and all price inputs are assumed to use ADJUSTED-CLOSE semantics.

Dependencies are limited to numpy / pandas / the Python standard library.
"""

from .risk import (
    beta,
    annualized_volatility,
    portfolio_volatility,
    portfolio_volatility_diag,
    value_at_risk,
    max_drawdown,
    sharpe,
    sortino,
    correlation_matrix,
    hhi,
    effective_number,
    sector_exposure,
)
from .position import (
    atr,
    atr_levels,
    r_multiple,
    unrealized_r,
    distance_to_stop_pct,
    position_size_fixed_fractional,
    kelly_fraction,
    fractional_kelly,
    days_held,
    position_vol,
    position_beta,
)
from .signals import (
    roc,
    relative_strength,
    rsi,
    macd,
    detect_divergence,
    ma_structure,
    support_resistance,
    rvol,
    gap_pct,
    pct_of_52w_range,
    days_to_earnings,
)
from .insider import (
    filter_open_market_buys,
    cluster_buys,
    score_insider_signal,
    fetch_form4,
    OPEN_MARKET_BUY_CODE,
)
from .regime import (
    regime_bias,
    get_regime_with_bias,
)
from .alerts import (
    score_alert,
    what_if_add,
    rebalancing_suggestions,
    ALERT_THRESHOLD,
    WATCH_THRESHOLD,
)

__all__ = [
    # risk.py
    "beta",
    "annualized_volatility",
    "portfolio_volatility",
    "portfolio_volatility_diag",
    "value_at_risk",
    "max_drawdown",
    "sharpe",
    "sortino",
    "correlation_matrix",
    "hhi",
    "effective_number",
    "sector_exposure",
    # position.py
    "atr",
    "atr_levels",
    "r_multiple",
    "unrealized_r",
    "distance_to_stop_pct",
    "position_size_fixed_fractional",
    "kelly_fraction",
    "fractional_kelly",
    "days_held",
    "position_vol",
    "position_beta",
    # signals.py
    "roc",
    "relative_strength",
    "rsi",
    "macd",
    "detect_divergence",
    "ma_structure",
    "support_resistance",
    "rvol",
    "gap_pct",
    "pct_of_52w_range",
    "days_to_earnings",
    # insider.py
    "filter_open_market_buys",
    "cluster_buys",
    "score_insider_signal",
    "fetch_form4",
    "OPEN_MARKET_BUY_CODE",
    # regime.py
    "regime_bias",
    "get_regime_with_bias",
    # alerts.py
    "score_alert",
    "what_if_add",
    "rebalancing_suggestions",
    "ALERT_THRESHOLD",
    "WATCH_THRESHOLD",
]
