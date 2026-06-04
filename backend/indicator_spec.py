"""Constrained indicator-spec engine — the safe core of the AI-written-indicators feature.

The keystone of the Charts Phase-3 work: AI (or a human) describes a technical
indicator as a **constrained JSON spec**, and this module computes it. Crucially,
the spec is NOT runnable code — it is a small DAG of *whitelisted* primitive ops
over named OHLCV series, evaluated by a deterministic NumPy interpreter we own.
There is no ``eval``/``exec`` anywhere; an attacker who fully controls the spec can
at worst produce NaNs or a validation error. This matches the project's security
posture (constrained spec computed in a sandbox, never arbitrary eval).

The interpreter is a PURE function of ``(spec, bars)``: the caller passes the exact
OHLCV bars to compute over (the frontend hands in the bars it is already rendering),
so the resulting series align perfectly on the chart and the whole thing is trivial
to unit-test. No data fetching, no global state.

Spec shape (validated by :func:`validate_spec`)::

    {
      "name": "EMA Ribbon",
      "short_name": "RIBBON",     # optional; defaults from name
      "pane": "overlay",          # "overlay" (on candles) | "separate" (sub-pane)
      "precision": 2,             # optional, 0..8
      "steps": [                  # ordered DAG; a step may only reference earlier ids
        {"id": "c",  "op": "series", "ref": "close"},
        {"id": "e8", "op": "ema", "input": "c", "period": 8},
        {"id": "e21","op": "ema", "input": "c", "period": 21}
      ],
      "plots": [                  # which step series get drawn
        {"step": "e8",  "label": "EMA8",  "type": "line", "color": "#00ff41"},
        {"step": "e21", "label": "EMA21", "type": "line", "color": "#ff3b3b"}
      ]
    }

Binary-op operands (``inputs: [a, b]``) may each be a step id (string) or a numeric
constant, so ``sma ± k*stddev`` style indicators need no scaffolding steps.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

# --- Reuse the app's tested primitives so engine values match the rest of the
# app (RSI/EMA shown elsewhere). Fall back to local impls if analytics is absent
# so the router still loads in a stripped environment. ---
try:
    from analytics.signals import _ema as _signals_ema, _rsi_series as _signals_rsi
    _HAS_SIGNALS = True
except Exception:  # pragma: no cover - import guard
    _HAS_SIGNALS = False


# ============================================================================
# Limits — every spec is bounded so a hostile/huge spec can't exhaust resources.
# ============================================================================

MAX_STEPS = 40
MAX_PLOTS = 8
MAX_PERIOD = 1000
MAX_BARS = 6000
MAX_NAME_LEN = 40

PANES = ("overlay", "separate")
PLOT_TYPES = ("line", "histogram", "baseline")

OHLCV_SERIES = ("open", "high", "low", "close", "volume", "hl2", "hlc3", "ohlc4")

# Op groups (validation + dispatch).
SOURCE_OPS = {"series", "const"}
WINDOW_OPS = {"sma", "ema", "wma", "rsi", "stddev", "max", "min", "shift", "diff"}
BINARY_OPS = {"add", "sub", "mul", "div", "cross"}
UNARY_OPS = {"abs"}
CLAMP_OP = {"clamp"}
ALL_OPS = SOURCE_OPS | WINDOW_OPS | BINARY_OPS | UNARY_OPS | CLAMP_OP

# Ops whose ``period`` is optional (with a default) vs required.
_DEFAULT_PERIOD = {"rsi": 14, "diff": 1, "shift": 1}

_ID_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


class SpecError(ValueError):
    """Raised by :func:`validate_spec`; ``.errors`` holds every problem found."""

    def __init__(self, errors: List[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors) if errors else "invalid spec")


# ============================================================================
# Validation — collects ALL errors (not just the first) for good editor UX.
# ============================================================================

def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and np.isfinite(float(x))


def _valid_id(s: Any) -> bool:
    return isinstance(s, str) and 1 <= len(s) <= 24 and s[0] not in "0123456789" and all(c in _ID_OK for c in s)


def validate_spec(spec: Any) -> Dict[str, Any]:
    """Validate + normalize a spec. Returns the normalized dict or raises SpecError.

    Normalization fills defaults (short_name, precision, plot type) so downstream
    code and the stored "arsenal" form are canonical.
    """
    errors: List[str] = []
    if not isinstance(spec, dict):
        raise SpecError(["spec must be an object"])

    name = spec.get("name")
    if not isinstance(name, str) or not (1 <= len(name.strip()) <= MAX_NAME_LEN):
        errors.append(f"name must be a 1..{MAX_NAME_LEN} char string")
        name = (name if isinstance(name, str) else "indicator")[:MAX_NAME_LEN] or "indicator"

    pane = spec.get("pane", "separate")
    if pane not in PANES:
        errors.append(f"pane must be one of {PANES}")
        pane = "separate"

    precision = spec.get("precision", 2)
    if not (isinstance(precision, int) and not isinstance(precision, bool) and 0 <= precision <= 8):
        errors.append("precision must be an int 0..8")
        precision = 2

    short_name = spec.get("short_name")
    if short_name is not None and not (isinstance(short_name, str) and 1 <= len(short_name) <= 16):
        errors.append("short_name must be a 1..16 char string")
        short_name = None

    steps = spec.get("steps")
    norm_steps: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    if not isinstance(steps, list) or not steps:
        errors.append("steps must be a non-empty list")
        steps = []
    elif len(steps) > MAX_STEPS:
        errors.append(f"too many steps (max {MAX_STEPS})")
        steps = steps[:MAX_STEPS]

    for i, step in enumerate(steps):
        where = f"steps[{i}]"
        if not isinstance(step, dict):
            errors.append(f"{where} must be an object")
            continue
        sid = step.get("id")
        if not _valid_id(sid):
            errors.append(f"{where}.id must match [A-Za-z_][A-Za-z0-9_]{{0,23}}")
            continue
        if sid in seen_ids:
            errors.append(f"{where}.id '{sid}' is duplicated")
            continue
        op = step.get("op")
        if op not in ALL_OPS:
            errors.append(f"{where}.op '{op}' is not a supported op")
            seen_ids.add(sid)
            norm_steps.append(step)
            continue
        # Per-op structural validation. Refs may only point at EARLIER ids
        # (this both enforces a DAG and makes evaluation order = declared order).
        _validate_step_refs(op, step, seen_ids, where, errors)
        seen_ids.add(sid)
        norm_steps.append(_normalize_step(op, step))

    plots = spec.get("plots")
    norm_plots: List[Dict[str, Any]] = []
    if not isinstance(plots, list) or not plots:
        errors.append("plots must be a non-empty list")
        plots = []
    elif len(plots) > MAX_PLOTS:
        errors.append(f"too many plots (max {MAX_PLOTS})")
        plots = plots[:MAX_PLOTS]
    for i, plot in enumerate(plots):
        where = f"plots[{i}]"
        if not isinstance(plot, dict):
            errors.append(f"{where} must be an object")
            continue
        ref = plot.get("step")
        if ref not in seen_ids:
            errors.append(f"{where}.step '{ref}' does not reference a defined step id")
        ptype = plot.get("type", "line")
        if ptype not in PLOT_TYPES:
            errors.append(f"{where}.type must be one of {PLOT_TYPES}")
            ptype = "line"
        color = plot.get("color")
        if color is not None and not (isinstance(color, str) and 0 < len(color) <= 32):
            errors.append(f"{where}.color must be a short string")
            color = None
        label = plot.get("label")
        if label is not None and not (isinstance(label, str) and len(label) <= 32):
            errors.append(f"{where}.label must be a <=32 char string")
            label = None
        norm_plots.append({
            "step": ref,
            "label": label or (ref if isinstance(ref, str) else "plot"),
            "type": ptype,
            **({"color": color} if color else {}),
        })

    if errors:
        raise SpecError(errors)

    return {
        "name": name.strip(),
        "short_name": short_name or _auto_short(name),
        "pane": pane,
        "precision": precision,
        "steps": norm_steps,
        "plots": norm_plots,
    }


def _auto_short(name: str) -> str:
    cleaned = "".join(c for c in name.upper() if c.isalnum() or c == " ").strip()
    return (cleaned[:8] or "IND").strip()


def _validate_step_refs(op: str, step: Dict[str, Any], prior: set[str], where: str, errors: List[str]) -> None:
    """Validate a step's operands/params against the ops already defined before it."""
    if op == "series":
        if step.get("ref") not in OHLCV_SERIES:
            errors.append(f"{where}.ref must be one of {OHLCV_SERIES}")
        return
    if op == "const":
        if not _is_number(step.get("value")):
            errors.append(f"{where}.value must be a finite number")
        return

    if op in WINDOW_OPS:
        inp = step.get("input")
        if inp not in prior:
            errors.append(f"{where}.input '{inp}' must reference an earlier step")
        period = step.get("period", _DEFAULT_PERIOD.get(op))
        if not (isinstance(period, int) and not isinstance(period, bool) and 1 <= period <= MAX_PERIOD):
            errors.append(f"{where}.period must be an int 1..{MAX_PERIOD}")
        return

    if op in BINARY_OPS:
        inputs = step.get("inputs")
        if not (isinstance(inputs, list) and len(inputs) == 2):
            errors.append(f"{where}.inputs must be a list of exactly 2 operands")
            return
        for j, operand in enumerate(inputs):
            if isinstance(operand, str):
                if operand not in prior:
                    errors.append(f"{where}.inputs[{j}] '{operand}' must reference an earlier step")
            elif not _is_number(operand):
                errors.append(f"{where}.inputs[{j}] must be an earlier step id or a finite number")
        return

    if op in UNARY_OPS:
        if step.get("input") not in prior:
            errors.append(f"{where}.input must reference an earlier step")
        return

    if op == "clamp":
        if step.get("input") not in prior:
            errors.append(f"{where}.input must reference an earlier step")
        lo, hi = step.get("min"), step.get("max")
        if lo is not None and not _is_number(lo):
            errors.append(f"{where}.min must be a finite number or omitted")
        if hi is not None and not _is_number(hi):
            errors.append(f"{where}.max must be a finite number or omitted")
        if lo is None and hi is None:
            errors.append(f"{where} clamp needs at least one of min/max")
        return


def _normalize_step(op: str, step: Dict[str, Any]) -> Dict[str, Any]:
    """Canonical step form with defaults applied (period for rsi/diff/shift)."""
    out: Dict[str, Any] = {"id": step["id"], "op": op}
    if op == "series":
        out["ref"] = step["ref"]
    elif op == "const":
        out["value"] = float(step["value"])
    elif op in WINDOW_OPS:
        out["input"] = step["input"]
        out["period"] = int(step.get("period", _DEFAULT_PERIOD.get(op)))
    elif op in BINARY_OPS:
        out["inputs"] = [x if isinstance(x, str) else float(x) for x in step["inputs"]]
    elif op in UNARY_OPS:
        out["input"] = step["input"]
    elif op == "clamp":
        out["input"] = step["input"]
        if step.get("min") is not None:
            out["min"] = float(step["min"])
        if step.get("max") is not None:
            out["max"] = float(step["max"])
    return out


# ============================================================================
# Interpreter — pure function of (validated spec, bars).
# ============================================================================

def _ema(values: np.ndarray, span: int) -> np.ndarray:
    if _HAS_SIGNALS:
        return np.asarray(_signals_ema(values, span), dtype=float)
    return pd.Series(values).ewm(span=span, adjust=False).mean().to_numpy(dtype=float)


def _rsi(values: np.ndarray, period: int) -> np.ndarray:
    if _HAS_SIGNALS:
        return np.asarray(_signals_rsi(values, period=period), dtype=float)
    s = pd.Series(values)
    delta = s.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).to_numpy(dtype=float)


def _bars_to_series(bars: List[Dict[str, Any]]) -> Tuple[List[int], Dict[str, np.ndarray]]:
    """Extract aligned epoch timestamps + OHLCV (and derived) series from bars."""
    n = len(bars)
    ts: List[int] = []
    o = np.full(n, np.nan)
    h = np.full(n, np.nan)
    low = np.full(n, np.nan)
    c = np.full(n, np.nan)
    v = np.full(n, np.nan)
    for i, b in enumerate(bars):
        ts.append(int(b.get("timestamp", 0)))
        o[i] = _f(b.get("open"))
        h[i] = _f(b.get("high"))
        low[i] = _f(b.get("low"))
        c[i] = _f(b.get("close"))
        v[i] = _f(b.get("volume"))
    series = {
        "open": o, "high": h, "low": low, "close": c, "volume": v,
        "hl2": (h + low) / 2.0,
        "hlc3": (h + low + c) / 3.0,
        "ohlc4": (o + h + low + c) / 4.0,
    }
    return ts, series


def _f(x: Any) -> float:
    try:
        val = float(x)
        return val if np.isfinite(val) else np.nan
    except (TypeError, ValueError):
        return np.nan


def _rolling(values: np.ndarray, period: int, fn: str) -> np.ndarray:
    s = pd.Series(values)
    r = s.rolling(window=period, min_periods=period)
    if fn == "sma":
        return r.mean().to_numpy(dtype=float)
    if fn == "stddev":
        return r.std(ddof=0).to_numpy(dtype=float)
    if fn == "max":
        return r.max().to_numpy(dtype=float)
    if fn == "min":
        return r.min().to_numpy(dtype=float)
    raise ValueError(fn)  # pragma: no cover


def _wma(values: np.ndarray, period: int) -> np.ndarray:
    weights = np.arange(1, period + 1, dtype=float)
    wsum = weights.sum()
    out = np.full(len(values), np.nan)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1: i + 1]
        if np.all(np.isfinite(window)):
            out[i] = float(np.dot(window, weights) / wsum)
    return out


def _cross(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    out = np.zeros(len(a))
    for i in range(1, len(a)):
        if not (np.isfinite(a[i]) and np.isfinite(b[i]) and np.isfinite(a[i - 1]) and np.isfinite(b[i - 1])):
            continue
        if a[i - 1] <= b[i - 1] and a[i] > b[i]:
            out[i] = 1.0
        elif a[i - 1] >= b[i - 1] and a[i] < b[i]:
            out[i] = -1.0
    return out


def interpret(spec: Dict[str, Any], bars: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute a (pre-validated) spec over bars. Returns render-ready plots.

    Returns ``{name, short_name, pane, precision, plots: [{step, label, type,
    color?, points: [{time, value}]}], bars: n}``. Warm-up NaNs / non-finite
    values are dropped per-plot. Assumes ``spec`` already passed validate_spec.
    """
    if not isinstance(bars, list) or not bars:
        raise ValueError("bars must be a non-empty list")
    if len(bars) > MAX_BARS:
        raise ValueError(f"too many bars (max {MAX_BARS})")

    ts, base = _bars_to_series(bars)
    n = len(bars)
    env: Dict[str, np.ndarray] = {}

    def operand(x: Union[str, float]) -> np.ndarray:
        if isinstance(x, str):
            return env[x]
        return np.full(n, float(x))

    for step in spec["steps"]:
        op = step["op"]
        if op == "series":
            res = base[step["ref"]].copy()
        elif op == "const":
            res = np.full(n, float(step["value"]))
        elif op == "ema":
            res = _ema(env[step["input"]], step["period"])
        elif op == "rsi":
            res = _rsi(env[step["input"]], step["period"])
        elif op == "wma":
            res = _wma(env[step["input"]], step["period"])
        elif op in ("sma", "stddev", "max", "min"):
            res = _rolling(env[step["input"]], step["period"], op)
        elif op == "shift":
            res = pd.Series(env[step["input"]]).shift(step["period"]).to_numpy(dtype=float)
        elif op == "diff":
            src = pd.Series(env[step["input"]])
            res = (src - src.shift(step["period"])).to_numpy(dtype=float)
        elif op == "abs":
            res = np.abs(env[step["input"]])
        elif op == "clamp":
            res = np.clip(env[step["input"]], step.get("min", -np.inf), step.get("max", np.inf))
        elif op in ("add", "sub", "mul", "div"):
            a, b = operand(step["inputs"][0]), operand(step["inputs"][1])
            with np.errstate(divide="ignore", invalid="ignore"):
                if op == "add":
                    res = a + b
                elif op == "sub":
                    res = a - b
                elif op == "mul":
                    res = a * b
                else:  # div
                    res = np.where(b != 0, a / b, np.nan)
        elif op == "cross":
            res = _cross(operand(step["inputs"][0]), operand(step["inputs"][1]))
        else:  # pragma: no cover - validate_spec guarantees a known op
            raise ValueError(f"unknown op {op}")
        env[step["id"]] = np.asarray(res, dtype=float)

    precision = spec["precision"]
    plots_out: List[Dict[str, Any]] = []
    for plot in spec["plots"]:
        arr = env[plot["step"]]
        points: List[Dict[str, Any]] = []
        for i in range(n):
            val = arr[i]
            if ts[i] and np.isfinite(val):
                points.append({"time": ts[i], "value": round(float(val), precision)})
        plots_out.append({
            "step": plot["step"],
            "label": plot["label"],
            "type": plot["type"],
            **({"color": plot["color"]} if plot.get("color") else {}),
            "points": points,
        })

    return {
        "name": spec["name"],
        "short_name": spec["short_name"],
        "pane": spec["pane"],
        "precision": precision,
        "plots": plots_out,
        "bars": n,
    }
