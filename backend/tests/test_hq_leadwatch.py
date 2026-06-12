"""Tests for the HQ leadwatch director-awareness monitor (scripts/hq_leadwatch.py).

Pure transition/dedup helpers with no I/O, plus a fake-IO cycle that drives the done + stuck
detection end to end (loaded by path like the collector/orchestrator/ratewatch tests).
"""

import importlib.util
from pathlib import Path

import pytest


def _load():
    path = Path(__file__).resolve().parents[2] / "scripts" / "hq_leadwatch.py"
    spec = importlib.util.spec_from_file_location("hq_leadwatch", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lw = _load()


# --------------------------------------------------------------------------- transitions
def test_detect_done_only_working_to_idle_edge():
    prev = {"a": "working", "b": "idle", "c": "working"}
    curr = {"a": "idle", "b": "idle", "c": "working", "d": "idle"}
    assert lw.detect_done(prev, curr) == ["a"]   # b already idle, c still working, d first-seen


def test_detect_crashed_working_to_offline():
    assert lw.detect_crashed({"a": "working", "b": "idle"}, {"a": "offline", "b": "offline"}) == ["a"]


def test_wait_counters_increment_and_reset():
    c1 = lw.update_wait_counters({}, {"a": "waiting-input", "b": "working"})
    assert c1 == {"a": 1, "b": 0}
    c2 = lw.update_wait_counters(c1, {"a": "waiting-input", "b": "waiting-input"})
    assert c2 == {"a": 2, "b": 1}
    c3 = lw.update_wait_counters(c2, {"a": "idle", "b": "waiting-input"})
    assert c3 == {"a": 0, "b": 2}   # a unblocked -> reset


def test_newly_stuck_fires_once_at_threshold():
    assert lw.newly_stuck_waiting({"a": 2, "b": 1, "c": 3}, 2) == ["a"]  # only == threshold, not >


def test_event_signature_stable_and_distinct():
    s1 = lw.event_signature("q", "done", "m1")
    s2 = lw.event_signature("q", "done", "m1")
    s3 = lw.event_signature("q", "done", "m2")
    assert s1 == s2 and s1 != s3 and len(s1) == 16
    assert lw.event_signature("q", "done", "m1") != lw.event_signature("q", "waiting", "m1")


# --------------------------------------------------------------------------- lead resolution + msgs
def test_resolve_lead_and_pane():
    fleet = {"heads": [{"name": "weaver", "tmux": {"pane": "%15"}, "status": "working"}]}
    assert lw.resolve_lead("trading-dashboard", {"trading-dashboard": "weaver"}) == "weaver"
    assert lw.lead_pane(fleet, "weaver") == ("%15", "working")
    assert lw.lead_pane(fleet, "ghost") == (None, None)


def test_messages_carry_intent():
    d = lw.build_done_msg("quanticus", "trading-dashboard", "opened PR #5")
    assert "finished" in d and "REVIEW" in d and "opened PR #5" in d
    s = lw.build_stuck_msg("opticon", "trading-dashboard", "blocked on a prompt", "allow git?")
    assert "STUCK" in s and "blocked on a prompt" in s and "allow git?" in s


def test_input_job_shape():
    j = lw.input_job("weaver", "%15", "hi", 1.0, "jid")
    assert set(j) == {"id", "head", "pane", "text", "by", "ts"} and j["by"] == lw.SENDER


# --------------------------------------------------------------------------- cycle (fake I/O)
class FakeIO:
    def __init__(self, fleet, leads, state=None):
        self.store = {lw.FLEET_KEY: fleet}
        if state is not None:
            self.store[lw.STATE_KEY] = state
        self.leads = leads
        self.queued = []     # input-queue jobs
        self.tg = []         # telegram texts

    def install(self, monkeypatch):
        monkeypatch.setattr(lw, "get_json", lambda k: self.store.get(k))
        monkeypatch.setattr(lw, "set_json", lambda k, v, ttl_s=None: self.store.__setitem__(k, v) or True)
        monkeypatch.setattr(lw, "rpush_capped", lambda k, v, cap: None)
        monkeypatch.setattr(lw, "stop_flagged", lambda: False)
        monkeypatch.setattr(lw, "load_leads", lambda: self.leads)
        monkeypatch.setattr(lw, "read_handoff", lambda wd: f"handoff:{wd}")
        monkeypatch.setattr(lw, "notify_schyler", lambda t: self.tg.append(t) or True)
        monkeypatch.setattr(lw, "time", __import__("types").SimpleNamespace(time=lambda: 1000.0))
        def fake_redis(args, input_text=None, timeout=10.0):
            if args[:2] == ["-x", "RPUSH"] and args[2] == lw.INPUT_QUEUE:
                self.queued.append(input_text)
            return ""
        monkeypatch.setattr(lw, "_redis", fake_redis)


WEAVER = {"name": "weaver", "room": "trading-dashboard", "tmux": {"pane": "%15"}, "status": "working"}
def _worker(name, status, **kw):
    return {"name": name, "room": "trading-dashboard", "status": status,
            "workdir": f"/w/{name}", "last_active": "2026-06-12T01:00:00Z",
            "current": kw.get("current", ""), "tmux": {"pane": kw.get("pane", "%9")}}


def test_cycle_done_notifies_lead(monkeypatch):
    fleet = {"heads": [WEAVER, _worker("quanticus", "idle")]}
    io = FakeIO(fleet, {"trading-dashboard": "weaver"},
                state={"head_status": {"quanticus": "working"}})
    io.install(monkeypatch)
    lw.run_cycle(drive=True)
    assert len(io.queued) == 1                       # one ping to the lead's pane
    assert "weaver" in io.queued[0] and "%15" in io.queued[0] and "finished" in io.queued[0]


def test_cycle_done_dedups(monkeypatch):
    fleet = {"heads": [WEAVER, _worker("quanticus", "idle")]}
    io = FakeIO(fleet, {"trading-dashboard": "weaver"}, state={"head_status": {"quanticus": "working"}})
    io.install(monkeypatch)
    lw.run_cycle(drive=True)                          # fires
    lw.run_cycle(drive=True)                          # idle->idle, same sig -> no re-fire
    assert len(io.queued) == 1


def test_cycle_lead_is_not_watched(monkeypatch):
    # the lead itself going working->idle must NOT notify (it doesn't watch itself)
    fleet = {"heads": [{**WEAVER, "status": "idle"}]}
    io = FakeIO(fleet, {"trading-dashboard": "weaver"}, state={"head_status": {"weaver": "working"}})
    io.install(monkeypatch)
    lw.run_cycle(drive=True)
    assert io.queued == []


def test_cycle_stuck_waiting_fires_after_threshold(monkeypatch):
    # cycle 1: waiting (count 1) -> no fire. cycle 2: waiting (count 2 == threshold) -> fire once.
    fleet = {"heads": [WEAVER, _worker("opticon", "waiting-input", current="allow git log?")]}
    io = FakeIO(fleet, {"trading-dashboard": "weaver"}, state={})
    io.install(monkeypatch)
    lw.run_cycle(drive=True)
    assert io.queued == [] and io.tg == []           # 1 cycle waiting: transient, ignored
    lw.run_cycle(drive=True)
    assert len(io.queued) == 1 and "STUCK" in io.queued[0] and "allow git log?" in io.queued[0]
    assert len(io.tg) == 1                            # telegram'd Schyler too
    lw.run_cycle(drive=True)
    assert len(io.queued) == 1                        # still waiting, same stall -> deduped


def test_cycle_crashed_notifies_and_telegrams(monkeypatch):
    fleet = {"heads": [WEAVER, _worker("quanticus", "offline")]}
    io = FakeIO(fleet, {"trading-dashboard": "weaver"}, state={"head_status": {"quanticus": "working"}})
    io.install(monkeypatch)
    lw.run_cycle(drive=True)
    assert len(io.queued) == 1 and "OFFLINE" in io.queued[0].upper()
    assert len(io.tg) == 1


def test_cycle_dry_run_sends_nothing(monkeypatch):
    fleet = {"heads": [WEAVER, _worker("quanticus", "idle")]}
    io = FakeIO(fleet, {"trading-dashboard": "weaver"}, state={"head_status": {"quanticus": "working"}})
    io.install(monkeypatch)
    lw.run_cycle(drive=False)
    assert io.queued == []                            # notify-only + dry-run => no queue writes
    assert io.store[lw.STATE_KEY]["head_status"]["quanticus"] == "idle"  # state still advances


def test_cycle_no_leads_watches_nothing(monkeypatch):
    fleet = {"heads": [WEAVER, _worker("quanticus", "idle")]}
    io = FakeIO(fleet, {}, state={"head_status": {"quanticus": "working"}})  # no leads configured
    io.install(monkeypatch)
    lw.run_cycle(drive=True)
    assert io.queued == []
