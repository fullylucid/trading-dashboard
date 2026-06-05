"""Tests for chart-condition smart alerts: condition logic, evaluate + dedup, CRUD,
evaluate_all delivery — hermetic via a fake redis + stubbed delivery."""

import pytest

import chart_alerts as al
from indicator_spec import SpecError


class _FakeRedis:
    def __init__(self):
        self.h = {}

    def ping(self):
        return True

    def hgetall(self, k):
        return dict(self.h)

    def hget(self, k, f):
        return self.h.get(f)

    def hset(self, k, f, v):
        self.h[f] = v
        return 1

    def hdel(self, k, f):
        return 1 if self.h.pop(f, None) is not None else 0

    def hlen(self, k):
        return len(self.h)


@pytest.fixture
def store(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(al, "_r", lambda: fake)
    return al


def _price_spec():
    return {
        "name": "Price",
        "steps": [{"id": "c", "op": "series", "ref": "close"}],
        "plots": [{"step": "c", "label": "Close"}],
    }


def _bars(closes, start_ts=1000, step=86400):
    return [
        {"timestamp": start_ts + i * step, "open": c, "high": c, "low": c, "close": c, "volume": 1}
        for i, c in enumerate(closes)
    ]


# --- condition logic --------------------------------------------------------
def test_condition_met():
    assert al._condition_met("gt", 100, None, 101) is True
    assert al._condition_met("gt", 100, None, 99) is False
    assert al._condition_met("lt", 100, None, 99) is True
    assert al._condition_met("cross_up", 100, 98, 102) is True
    assert al._condition_met("cross_up", 100, 101, 102) is False  # already above
    assert al._condition_met("cross_down", 100, 102, 98) is True
    assert al._condition_met("cross_up", 100, None, 102) is False  # no prev


# --- CRUD -------------------------------------------------------------------
def test_save_list_get_delete(store):
    a = store.save_alert("aapl", _price_spec(), "c", "gt", 100, channel="log", note="hi")
    assert a["symbol"] == "AAPL" and a["op"] == "gt" and a["active"] is True
    assert store.list_alerts()[0]["id"] == a["id"]
    assert store.get_alert(a["id"])["note"] == "hi"
    assert store.delete_alert(a["id"]) is True
    assert store.list_alerts() == []


def test_save_rejects_bad_input(store):
    with pytest.raises(ValueError):
        store.save_alert("AAPL", _price_spec(), "c", "bogus_op", 100)
    with pytest.raises(ValueError):
        store.save_alert("AAPL", _price_spec(), "missing", "gt", 100)  # plot_step not in spec
    with pytest.raises(SpecError):
        store.save_alert("AAPL", {"name": "x"}, "c", "gt", 100)  # invalid spec


# --- evaluate + dedup -------------------------------------------------------
def test_evaluate_gt_fires_once_per_bar(store):
    a = store.save_alert("AAPL", _price_spec(), "c", "gt", 100, channel="log")
    bars = _bars([95, 98, 105])  # last close 105 > 100
    fired, msg = al.evaluate(a, bars)
    assert fired is True and "AAPL" in msg
    # same bars again -> dedup (already fired on this bar)
    fired2, _ = al.evaluate(a, bars)
    assert fired2 is False
    # a new bar still above -> fires again
    bars2 = _bars([95, 98, 105, 106])
    fired3, _ = al.evaluate(a, bars2)
    assert fired3 is True


def test_evaluate_cross_up(store):
    a = store.save_alert("AAPL", _price_spec(), "c", "cross_up", 100, channel="log")
    assert al.evaluate(a, _bars([98, 102]))[0] is True   # 98 -> 102 crosses 100
    a2 = store.save_alert("AAPL", _price_spec(), "c", "cross_up", 100, channel="log")
    assert al.evaluate(a2, _bars([101, 103]))[0] is False  # already above, no cross


def test_evaluate_all_delivers(store, monkeypatch):
    sent = []
    monkeypatch.setattr(al, "_deliver", lambda ch, txt: sent.append((ch, txt)) or True)
    monkeypatch.setattr(al, "_bars_for", lambda sym, days=400: _bars([90, 95, 110]))
    store.save_alert("AAPL", _price_spec(), "c", "gt", 100, channel="log")
    res = store.evaluate_all()
    assert res["fired"] == 1 and len(sent) == 1
