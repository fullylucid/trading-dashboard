"""Tests for the HQ ratewatch detector's pure helpers + the cap→wait→resume cycle
(scripts/hq_ratewatch.py).

The pure functions are exercised with no I/O (the module is loaded by path — it lives in
scripts/, not on sys.path, same as the collector/orchestrator tests). The cycle-level tests
monkeypatch the thin I/O seam (get_json / capture_pane / read_handoff / _redis / set_json /
rpush_capped / notify_schyler) with in-memory fakes, so the WATCHING→CAPPED→RESUMING state
machine is verified end to end without Redis, tmux, or transcripts.
"""

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest


def _load():
    path = Path(__file__).resolve().parents[2] / "scripts" / "hq_ratewatch.py"
    spec = importlib.util.spec_from_file_location("hq_ratewatch", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rw = _load()


# --------------------------------------------------------------------------- binding window
def _usage(session=None, weekly=None, sonnet=None):
    return {
        "session_pct": session, "session_resets_at": "2026-06-10T15:50:00+00:00",
        "weekly_pct": weekly, "weekly_resets_at": "2026-06-14T12:00:00+00:00",
        "sonnet_pct": sonnet, "sonnet_resets_at": None,
    }


def test_binding_window_picks_highest_pct():
    name, pct, resets = rw.binding_window(_usage(session=99.0, weekly=17.0))
    assert name == "session" and pct == 99.0 and resets.startswith("2026-06-10")


def test_binding_window_weekly_can_bind():
    name, pct, _ = rw.binding_window(_usage(session=20.0, weekly=99.5))
    assert name == "weekly" and pct == 99.5


def test_binding_window_no_numeric_window():
    assert rw.binding_window(_usage()) == (None, 0.0, None)


# --------------------------------------------------------------------------- threshold + confirm
def test_over_threshold():
    assert rw.over_threshold(_usage(session=99.0), 99.0) is True
    assert rw.over_threshold(_usage(session=98.9), 99.0) is False


def test_cap_line_re_matches_known_variants():
    for line in ["Claude usage limit reached",
                 "your limit will reset at 3pm",
                 "You're approaching your usage limit",
                 "Run /upgrade to increase your limit"]:
        assert rw.cap_confirmed([f"...\n{line}\n..."]) is True


def test_cap_confirmed_rejects_normal_output():
    assert rw.cap_confirmed(["$ pytest -q\n3 passed", "Edited file foo.py"]) is False
    assert rw.cap_confirmed([]) is False


def test_is_capped_requires_both_threshold_and_pane_confirmation():
    over = _usage(session=99.5)
    # over threshold but no pane line (spillover, or scrolled off) => NOT capped (safe failure)
    assert rw.is_capped(over, 99.0, ["working normally"]) is False
    # threshold + a confirming pane => capped
    assert rw.is_capped(over, 99.0, ["usage limit reached"]) is True
    # confirmed pane but under threshold => not capped (don't fire on a stray match)
    assert rw.is_capped(_usage(session=40.0), 99.0, ["usage limit reached"]) is False


# --------------------------------------------------------------------------- weekly classification
def test_is_weekly():
    assert rw.is_weekly("weekly") is True
    assert rw.is_weekly("sonnet") is True
    assert rw.is_weekly("session") is False
    assert rw.is_weekly(None) is False


# --------------------------------------------------------------------------- snapshot working
def test_snapshot_working_filters_status_and_name():
    fleet = {"heads": [
        {"name": "a", "status": "working"},
        {"name": "b", "status": "idle"},
        {"name": "c", "status": "working"},
        {"status": "working"},  # nameless — dropped
    ]}
    assert [h["name"] for h in rw.snapshot_working(fleet)] == ["a", "c"]


# --------------------------------------------------------------------------- timing
# A realistic 2026 epoch consistent with the ISO reset stamps in _usage() (session resets at
# 15:50, weekly on the 14th — both in the future relative to this 15:00 "now").
NOW = datetime(2026, 6, 10, 15, 0, 0, tzinfo=timezone.utc).timestamp()


def test_seconds_until_future_and_past():
    # iso = NOW + 100s; buffer 60 => ~160s left
    future = datetime.fromtimestamp(NOW + 100, timezone.utc).isoformat()
    assert rw.seconds_until(future, 60, NOW) == 160
    past = datetime.fromtimestamp(NOW - 1000, timezone.utc).isoformat()
    assert rw.seconds_until(past, 60, NOW) < 0


def test_seconds_until_bad_timestamp_is_none():
    assert rw.seconds_until(None, 60, NOW) is None
    assert rw.seconds_until("not-a-date", 60, NOW) is None


def test_resets_after():
    past = datetime.fromtimestamp(NOW - 10, timezone.utc).isoformat()
    future = datetime.fromtimestamp(NOW + 10, timezone.utc).isoformat()
    assert rw.resets_after(past, 0, NOW) is True
    assert rw.resets_after(future, 60, NOW) is False
    assert rw.resets_after(None, 60, NOW) is False  # bad data never "after"


def test_seconds_until_naive_iso_treated_as_utc():
    # a naive timestamp (no tz) must be read as UTC, not local
    assert rw.seconds_until("2026-06-10T15:50:00", 0, NOW) is not None


# --------------------------------------------------------------------------- signature + loop-guard
def test_task_signature_stable_and_progress_sensitive():
    s1 = rw.task_signature("hydra1", "2026-06-10T01:00:00Z", "still writing the parser")
    s2 = rw.task_signature("hydra1", "2026-06-10T01:00:00Z", "still writing the parser")
    s3 = rw.task_signature("hydra1", "2026-06-10T02:00:00Z", "opened PR #5")
    assert s1 == s2 and s1 != s3 and len(s1) == 16


def test_should_backoff_same_sig_or_max():
    assert rw.should_backoff("abc", "abc", 0, 1) is True      # zero progress => back off
    assert rw.should_backoff("abc", "def", 0, 1) is False     # progressed => ok
    assert rw.should_backoff(None, "def", 0, 1) is False      # first window => ok
    assert rw.should_backoff("abc", "def", 1, 1) is True      # already at max resumes


# --------------------------------------------------------------------------- pluggable resume
def test_resume_target_tmux():
    assert rw.resume_target({"name": "hydra1", "tmux": {"pane": "%7"}}, {}) == ("tmux", "%7")


def test_resume_target_external_bus():
    assert rw.resume_target({"name": "win-gaia"}, {"win-gaia": "bus"}) == ("bus", "win-gaia")


def test_resume_target_paneless_unknown_is_none():
    assert rw.resume_target({"name": "ghost"}, {"win-gaia": "bus"}) is None


def test_build_nudge_is_a_resume_not_a_restart():
    n = rw.build_nudge().lower()
    assert "resume" in n and "don't restart" in n


def test_input_job_shape_matches_relay():
    job = rw.input_job("hydra1", "%7", "hi", NOW, "jid123")
    assert set(job) == {"id", "head", "pane", "text", "by", "ts"}
    assert job["by"] == rw.SENDER and job["pane"] == "%7" and job["id"] == "jid123"


# --------------------------------------------------------------------------- cycle-level (fake I/O)
class FakeIO:
    """In-memory stand-in for the Redis/tmux/transcript seam."""
    def __init__(self, usage, fleet, panes, state=None):
        self.store = {rw.USAGE_KEY: usage, rw.FLEET_KEY: fleet}
        if state is not None:
            self.store[rw.STATE_KEY] = state
        self.panes = panes            # pane id -> captured text
        self.rpushes = []             # (key, payload)
        self.notes = []               # escalation/summary texts

    def install(self, monkeypatch):
        monkeypatch.setattr(rw, "get_json", lambda k: self.store.get(k))
        monkeypatch.setattr(rw, "set_json", lambda k, v, ttl_s=None: self.store.__setitem__(k, v) or True)
        monkeypatch.setattr(rw, "rpush_capped", lambda k, v, cap: self.rpushes.append((k, v)))
        monkeypatch.setattr(rw, "_redis", lambda args, input_text=None, timeout=10.0:
                            self._redis(args, input_text))
        monkeypatch.setattr(rw, "capture_pane", lambda pane: self.panes.get(pane, ""))
        monkeypatch.setattr(rw, "read_handoff", lambda wd: f"handoff:{wd}")
        monkeypatch.setattr(rw, "notify_schyler", lambda text: self.notes.append(text) or True)
        monkeypatch.setattr(rw, "stop_flagged", lambda head=None: None)
        monkeypatch.setattr(rw.time, "time", lambda: NOW)

    def _redis(self, args, input_text):
        # only the INPUT_QUEUE RPUSH path is exercised live in the cycle
        if args[:2] == ["-x", "RPUSH"]:
            self.rpushes.append((args[2], input_text))
        return ""


def _queued(io):
    """The nudges actually written to the input queue (excludes audit rpushes)."""
    return [p for (k, p) in io.rpushes if k == rw.INPUT_QUEUE]


def _fleet(*working):
    heads = [{"name": n, "status": "working", "tmux": {"pane": p}, "workdir": f"/w/{n}",
              "last_active": "2026-06-10T01:00:00Z", "room": "trading-dashboard"}
             for n, p in working]
    return {"heads": heads}


def test_cycle_watching_no_cap_is_noop(monkeypatch):
    io = FakeIO(_usage(session=20.0), _fleet(("hydra1", "%1")), {})
    io.install(monkeypatch)
    rw.run_cycle(drive=False)
    assert io.store[rw.STATE_KEY]["phase"] == "WATCHING"
    assert io.rpushes == []  # audit rpushes are stubbed out; no input-queue writes


def test_cycle_enters_capped_then_waits_then_resumes(monkeypatch):
    # 1) over threshold + a confirming pane => CAPPED
    usage = _usage(session=99.5)
    io = FakeIO(usage, _fleet(("hydra1", "%1"), ("charts", "%2")),
                {"%1": "Claude usage limit reached", "%2": "working"})
    io.install(monkeypatch)
    rw.run_cycle(drive=True)
    st = io.store[rw.STATE_KEY]
    assert st["phase"] == "CAPPED"
    assert sorted(s["name"] for s in st["snapshot"]) == ["charts", "hydra1"]
    assert _queued(io) == []  # nothing sent to the input queue while waiting

    # 2) still waiting (reset is in the future) => no resume
    rw.run_cycle(drive=True)
    assert io.store[rw.STATE_KEY]["phase"] == "CAPPED" and _queued(io) == []

    # 3) reset has passed => RESUMING fires a tmux nudge per head, back to WATCHING
    io.store[rw.STATE_KEY]["resets_at"] = "2026-06-10T00:00:00+00:00"  # well in the past vs NOW
    rw.run_cycle(drive=True)
    assert io.store[rw.STATE_KEY]["phase"] == "WATCHING"
    queued = _queued(io)
    assert len(queued) == 2  # one nudge per working head
    assert any(rw.SENDER in p for p in queued)
    assert any("Resumed 2 head" in n for n in io.notes)  # lead summary fired


def test_cycle_dry_run_sends_nothing_but_advances(monkeypatch):
    usage = _usage(session=99.9)
    state = {"phase": "CAPPED", "binding": "session", "resets_at": "2026-06-10T00:00:00+00:00",
             "capped_at": int(NOW) - 100,
             "snapshot": [{"name": "hydra1", "sig": "s1", "target": ["tmux", "%1"], "backoff": False}],
             "resumes": {}}
    io = FakeIO(usage, _fleet(("hydra1", "%1")), {}, state=state)
    io.install(monkeypatch)
    rw.run_cycle(drive=False)
    assert io.store[rw.STATE_KEY]["phase"] == "WATCHING"          # state advanced
    assert [p for (k, p) in io.rpushes if k == rw.INPUT_QUEUE] == []  # but no live nudge


def test_cycle_weekly_cap_holds_and_escalates(monkeypatch):
    usage = _usage(session=20.0, weekly=99.9)  # weekly binds
    io = FakeIO(usage, _fleet(("hydra1", "%1")), {"%1": "usage limit reached"})
    io.install(monkeypatch)
    rw.run_cycle(drive=True)
    assert io.store[rw.STATE_KEY]["phase"] == "WEEKLY_HOLD"
    assert any("WEEKLY" in n for n in io.notes)
    assert [p for (k, p) in io.rpushes if k == rw.INPUT_QUEUE] == []  # held, not resumed


def test_cycle_loop_guard_backs_off_same_sig(monkeypatch):
    # head re-caps on the SAME signature it was resumed on last window => backoff + escalate
    usage = _usage(session=99.9)
    prev = {"sigs": {"hydra1": rw.task_signature("hydra1", "2026-06-10T01:00:00Z", "handoff:/w/hydra1")}}
    io = FakeIO(usage, _fleet(("hydra1", "%1")), {"%1": "usage limit reached"},
                state={"phase": "WATCHING", "last_window": prev})
    io.install(monkeypatch)
    rw.run_cycle(drive=True)
    snap = io.store[rw.STATE_KEY]["snapshot"]
    assert snap[0]["backoff"] is True
    assert any("backing off" in n for n in io.notes)
