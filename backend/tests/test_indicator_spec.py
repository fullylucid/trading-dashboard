"""Unit + endpoint tests for the constrained indicator-spec engine.

Covers (1) validation — every malformed-spec path raises with collected errors and
good specs normalize; (2) the interpreter — unambiguous ops pinned to hand-computed
values, EMA/RSI pinned against the very primitives the engine reuses; (3) the HTTP
surface via the mocked TestClient.
"""

import numpy as np
import pytest

import indicator_spec as eng
from indicator_spec import SpecError, validate_spec, interpret


@pytest.fixture
def client():
    """A TestClient mounting ONLY the indicator router.

    The engine router has no external deps (no Redis/Finnhub), so we test it in
    isolation rather than through the full-app `client` fixture in conftest — that
    fixture is currently broken on main (it patches module attributes main.py no
    longer defines), and our feature shouldn't ride on it.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from indicator_routes import indicator_router

    app = FastAPI()
    app.include_router(indicator_router)
    return TestClient(app)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _bars(closes, highs=None, lows=None, opens=None, vols=None, start_ts=1000, step=86400):
    n = len(closes)
    highs = highs or closes
    lows = lows or closes
    opens = opens or closes
    vols = vols or [0] * n
    return [
        {
            "timestamp": start_ts + i * step,
            "open": opens[i], "high": highs[i], "low": lows[i],
            "close": closes[i], "volume": vols[i],
        }
        for i in range(n)
    ]


def _spec(steps, plots, **kw):
    base = {"name": "t", "steps": steps, "plots": plots}
    base.update(kw)
    return base


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def test_validate_good_spec_normalizes():
    spec = _spec(
        [{"id": "c", "op": "series", "ref": "close"},
         {"id": "e", "op": "ema", "input": "c", "period": 3}],
        [{"step": "e"}],
        name="  My Indicator  ",
    )
    norm = validate_spec(spec)
    assert norm["name"] == "My Indicator"
    assert norm["short_name"]  # auto-derived
    assert norm["pane"] == "separate"  # default
    assert norm["precision"] == 2
    assert norm["plots"][0]["type"] == "line"  # default
    assert norm["plots"][0]["label"] == "e"  # defaults to step id


def test_validate_rejects_unknown_op():
    with pytest.raises(SpecError):
        validate_spec(_spec([{"id": "x", "op": "frobnicate", "input": "c"}], [{"step": "x"}]))


def test_validate_rejects_forward_reference():
    # 'e' references 'c' which is declared AFTER it -> not an earlier step.
    spec = _spec(
        [{"id": "e", "op": "ema", "input": "c", "period": 3},
         {"id": "c", "op": "series", "ref": "close"}],
        [{"step": "e"}],
    )
    with pytest.raises(SpecError) as ei:
        validate_spec(spec)
    assert any("earlier step" in m for m in ei.value.errors)


def test_validate_rejects_duplicate_ids_and_bad_pane():
    spec = _spec(
        [{"id": "c", "op": "series", "ref": "close"},
         {"id": "c", "op": "series", "ref": "open"}],
        [{"step": "c"}],
        pane="sideways",
    )
    with pytest.raises(SpecError) as ei:
        validate_spec(spec)
    msgs = " ".join(ei.value.errors)
    assert "duplicated" in msgs and "pane" in msgs


def test_validate_plot_must_reference_defined_step():
    with pytest.raises(SpecError):
        validate_spec(_spec([{"id": "c", "op": "series", "ref": "close"}], [{"step": "nope"}]))


def test_validate_too_many_steps():
    steps = [{"id": f"s{i}", "op": "series", "ref": "close"} for i in range(eng.MAX_STEPS + 5)]
    with pytest.raises(SpecError):
        validate_spec(_spec(steps, [{"step": "s0"}]))


def test_validate_period_out_of_range():
    with pytest.raises(SpecError):
        validate_spec(_spec(
            [{"id": "c", "op": "series", "ref": "close"},
             {"id": "e", "op": "ema", "input": "c", "period": 0}],
            [{"step": "e"}],
        ))


# --------------------------------------------------------------------------- #
# Interpreter — unambiguous ops pinned to hand-computed values
# --------------------------------------------------------------------------- #
def test_sma_hand_computed_and_nan_dropped():
    spec = validate_spec(_spec(
        [{"id": "c", "op": "series", "ref": "close"},
         {"id": "m", "op": "sma", "input": "c", "period": 2}],
        [{"step": "m"}],
    ))
    out = interpret(spec, _bars([1, 2, 3, 4]))
    pts = out["plots"][0]["points"]
    # SMA2 of [1,2,3,4] = [nan,1.5,2.5,3.5]; warm-up NaN dropped -> 3 points.
    assert [p["value"] for p in pts] == [1.5, 2.5, 3.5]
    # Timestamps preserved and aligned to bars 2..4.
    assert pts[0]["time"] == 1000 + 86400


def test_stddev_and_boll_band_arithmetic():
    # sma2 + 2*stddev2 on [1,2,3,4]; population stddev of [1,2]=0.5 -> 1.5+1.0=2.5
    spec = validate_spec(_spec(
        [{"id": "c", "op": "series", "ref": "close"},
         {"id": "m", "op": "sma", "input": "c", "period": 2},
         {"id": "sd", "op": "stddev", "input": "c", "period": 2},
         {"id": "k", "op": "mul", "inputs": ["sd", 2]},
         {"id": "up", "op": "add", "inputs": ["m", "k"]}],
        [{"step": "up"}],
    ))
    out = interpret(spec, _bars([1, 2, 3, 4]))
    assert out["plots"][0]["points"][0]["value"] == pytest.approx(2.5)


def test_div_guards_zero():
    spec = validate_spec(_spec(
        [{"id": "c", "op": "series", "ref": "close"},
         {"id": "v", "op": "series", "ref": "volume"},
         {"id": "r", "op": "div", "inputs": ["c", "v"]}],
        [{"step": "r"}],
    ))
    # volume all zero -> every division is nan -> all points dropped.
    out = interpret(spec, _bars([1, 2, 3], vols=[0, 0, 0]))
    assert out["plots"][0]["points"] == []


def test_diff_period_one():
    spec = validate_spec(_spec(
        [{"id": "c", "op": "series", "ref": "close"},
         {"id": "d", "op": "diff", "input": "c", "period": 1}],
        [{"step": "d"}],
    ))
    out = interpret(spec, _bars([10, 13, 11, 20]))
    assert [p["value"] for p in out["plots"][0]["points"]] == [3.0, -2.0, 9.0]


def test_cross_up_and_down():
    # fast crosses above slow then below.
    closes = [1, 2, 3, 2, 1]
    spec = validate_spec(_spec(
        [{"id": "c", "op": "series", "ref": "close"},
         {"id": "k", "op": "const", "value": 2.0},
         {"id": "x", "op": "cross", "inputs": ["c", "k"]}],
        [{"step": "x"}],
    ))
    out = interpret(spec, _bars(closes))
    vals = {p["time"]: p["value"] for p in out["plots"][0]["points"]}
    # close crosses above 2 going 2->3 (bar idx2), below 2 going 2->1 (bar idx4)
    assert vals[1000 + 2 * 86400] == 1.0
    assert vals[1000 + 4 * 86400] == -1.0


def test_hl2_derived_series():
    spec = validate_spec(_spec(
        [{"id": "m", "op": "series", "ref": "hl2"}],
        [{"step": "m"}],
    ))
    out = interpret(spec, _bars([0, 0], highs=[10, 20], lows=[0, 10]))
    assert [p["value"] for p in out["plots"][0]["points"]] == [5.0, 15.0]


def test_ema_matches_engine_primitive():
    closes = [float(x) for x in range(1, 30)]
    spec = validate_spec(_spec(
        [{"id": "c", "op": "series", "ref": "close"},
         {"id": "e", "op": "ema", "input": "c", "period": 5}],
        [{"step": "e"}],
    ))
    out = interpret(spec, _bars(closes))
    expected = eng._ema(np.asarray(closes), 5)
    got = {p["time"]: p["value"] for p in out["plots"][0]["points"]}
    # last bar's EMA matches the primitive the engine reuses.
    last_ts = 1000 + (len(closes) - 1) * 86400
    assert got[last_ts] == pytest.approx(round(float(expected[-1]), 2), abs=1e-6)


def test_rsi_of_rising_series_near_100():
    closes = [float(x) for x in range(1, 40)]
    spec = validate_spec(_spec(
        [{"id": "c", "op": "series", "ref": "close"},
         {"id": "r", "op": "rsi", "input": "c"}],  # default period 14
        [{"step": "r"}],
    ))
    out = interpret(spec, _bars(closes))
    assert out["plots"][0]["points"][-1]["value"] > 95.0


def test_interpret_rejects_empty_and_oversized_bars():
    spec = validate_spec(_spec([{"id": "c", "op": "series", "ref": "close"}], [{"step": "c"}]))
    with pytest.raises(ValueError):
        interpret(spec, [])
    with pytest.raises(ValueError):
        interpret(spec, _bars([1.0] * (eng.MAX_BARS + 1)))


# --------------------------------------------------------------------------- #
# HTTP surface
# --------------------------------------------------------------------------- #
def test_ops_endpoint(client):
    r = client.get("/api/indicator/ops")
    assert r.status_code == 200
    body = r.json()
    assert "ema" in body["ops"]["window"]
    assert "close" in body["series"]
    assert body["limits"]["max_steps"] == eng.MAX_STEPS


def test_validate_endpoint_valid_and_invalid(client):
    good = _spec(
        [{"id": "c", "op": "series", "ref": "close"},
         {"id": "e", "op": "ema", "input": "c", "period": 3}],
        [{"step": "e"}],
    )
    r = client.post("/api/indicator/validate", json={"spec": good})
    assert r.status_code == 200 and r.json()["valid"] is True

    bad = _spec([{"id": "c", "op": "series", "ref": "close"}], [{"step": "missing"}])
    r = client.post("/api/indicator/validate", json={"spec": bad})
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False and body["errors"]


def test_compute_endpoint(client):
    spec = _spec(
        [{"id": "c", "op": "series", "ref": "close"},
         {"id": "m", "op": "sma", "input": "c", "period": 2}],
        [{"step": "m", "label": "SMA2"}],
    )
    bars = _bars([1, 2, 3, 4])
    r = client.post("/api/indicator/compute", json={"spec": spec, "bars": bars})
    assert r.status_code == 200
    body = r.json()
    assert body["plots"][0]["label"] == "SMA2"
    assert [p["value"] for p in body["plots"][0]["points"]] == [1.5, 2.5, 3.5]


def test_compute_endpoint_invalid_spec_400(client):
    r = client.post("/api/indicator/compute", json={"spec": {"name": "x"}, "bars": _bars([1, 2])})
    assert r.status_code == 400


# --------------------------------------------------------------------------- #
# Arsenal — Redis-backed approved-spec library (with an in-memory fake redis)
# --------------------------------------------------------------------------- #
class _FakeRedis:
    """Minimal hash-only fake covering what indicator_arsenal uses."""

    def __init__(self):
        self.h: dict = {}

    def ping(self):
        return True

    def hgetall(self, key):
        return dict(self.h)

    def hget(self, key, field):
        return self.h.get(field)

    def hset(self, key, field, value):
        self.h[field] = value
        return 1

    def hdel(self, key, field):
        return 1 if self.h.pop(field, None) is not None else 0

    def hlen(self, key):
        return len(self.h)


@pytest.fixture
def arsenal(monkeypatch):
    import indicator_arsenal as ars

    fake = _FakeRedis()
    monkeypatch.setattr(ars, "_r", lambda: fake)
    return ars


def _good_spec():
    return _spec(
        [{"id": "c", "op": "series", "ref": "close"},
         {"id": "e", "op": "ema", "input": "c", "period": 9}],
        [{"step": "e"}],
        name="Saver",
    )


def test_arsenal_save_list_get_delete(arsenal):
    item = arsenal.save_item(_good_spec(), source="manual", tags=["trend"])
    assert item["id"].startswith("saver-")
    assert item["spec"]["short_name"]  # normalized
    assert item["tags"] == ["trend"]

    items = arsenal.list_items()
    assert len(items) == 1 and items[0]["id"] == item["id"]
    assert arsenal.get_item(item["id"])["name"] == "Saver"
    assert arsenal.delete_item(item["id"]) is True
    assert arsenal.list_items() == []


def test_arsenal_save_rejects_invalid_spec(arsenal):
    with pytest.raises(SpecError):
        arsenal.save_item({"name": "bad"})  # no steps/plots


def test_arsenal_endpoints(client, arsenal):
    # save
    r = client.post("/api/indicator/arsenal", json={"spec": _good_spec(), "source": "test"})
    assert r.status_code == 200
    item_id = r.json()["id"]
    # list
    r = client.get("/api/indicator/arsenal")
    assert r.status_code == 200 and any(i["id"] == item_id for i in r.json()["items"])
    # delete
    r = client.delete(f"/api/indicator/arsenal/{item_id}")
    assert r.status_code == 200 and r.json()["deleted"] is True


def test_arsenal_save_endpoint_invalid_400(client, arsenal):
    r = client.post("/api/indicator/arsenal", json={"spec": {"name": "x"}})
    assert r.status_code == 400
