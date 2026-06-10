"""Tests for the HQ orchestrator's pure decision helpers (scripts/hq_orchestrator.py).

No Redis/tmux/transcript I/O — the module is loaded by path (it lives in scripts/, not on
sys.path, same as the collector in test_hq.py) and only the pure functions are exercised:
transition detection, the loop-guard signature, milestone boundary, lead/pane resolution,
the notify message, the relay job shape, and the per-arming budget reset.
"""

import importlib.util
from pathlib import Path

import pytest


def _load():
    path = Path(__file__).resolve().parents[2] / "scripts" / "hq_orchestrator.py"
    spec = importlib.util.spec_from_file_location("hq_orchestrator", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


orch = _load()


# --------------------------------------------------------------------------- transitions
def test_detect_finishes_only_working_to_idle_edge():
    prev = {"a": "working", "b": "idle", "c": "working", "d": "waiting-input"}
    curr = {"a": "idle", "b": "idle", "c": "working", "d": "idle", "e": "idle"}
    # a: real finish · b: already idle · c: still working · d: waiting->idle (an answered
    # prompt, not a finish) · e: never seen before (first sighting must not fire)
    assert orch.detect_finishes(prev, curr) == ["a"]


def test_detect_finishes_empty_prev_never_fires():
    assert orch.detect_finishes({}, {"a": "idle", "b": "idle"}) == []


# --------------------------------------------------------------------------- loop-guard
def test_task_signature_stable_and_distinct():
    s1 = orch.task_signature("data-gaia", "2026-06-09T01:00:00Z", "opened PR #12")
    s2 = orch.task_signature("data-gaia", "2026-06-09T01:00:00Z", "opened PR #12")
    s3 = orch.task_signature("data-gaia", "2026-06-09T02:00:00Z", "opened PR #13")
    assert s1 == s2          # same finished task -> same sig (never re-notified)
    assert s1 != s3          # a new turn -> new sig (next finish notifies again)
    assert len(s1) == 16


def test_task_signature_handles_none_timestamp():
    assert orch.task_signature("x", None, "") != orch.task_signature("y", None, "")


# --------------------------------------------------------------------------- milestone boundary
def _leaf(text, status, checked=False, milestone=None):
    return {"text": text, "checked": checked, "status": status,
            "milestone": milestone, "children": []}


def test_milestone_reached_all_done_before_marker():
    nodes = [
        {"text": "Epic", "checked": None, "milestone": None, "status": "group", "children": [
            _leaf("t1", "done", True),
            _leaf("t2", "done", True),
            _leaf("marker item", "planned", False, milestone="R12"),
            _leaf("after", "planned", False),   # past the line — must not count
        ]},
    ]
    assert orch.milestone_reached(nodes, "R12") is True


def test_milestone_not_reached_with_open_item_before_marker():
    nodes = [
        _leaf("t1", "done", True),
        _leaf("t2", "in_progress", False),
        _leaf("boundary", "planned", False, milestone="R12"),
    ]
    assert orch.milestone_reached(nodes, "R12") is False


def test_milestone_marker_missing_returns_none():
    assert orch.milestone_reached([_leaf("t1", "done", True)], "R99") is None


def test_milestone_match_is_case_insensitive_and_nested():
    nodes = [
        {"text": "Epic", "checked": None, "milestone": None, "status": "group", "children": [
            _leaf("t1", "done", True),
            {"text": "", "checked": None, "milestone": "r12", "status": "group", "children": []},
        ]},
        _leaf("later epic task", "planned", False),
    ]
    assert orch.milestone_reached(nodes, "R12") is True


# --------------------------------------------------------------------------- lead resolution
FLEET = {
    "rooms": [
        {"id": "cyborganic", "open_prs": [
            {"number": 41, "title": "feat: gaia bus v2", "head": "data-gaia"},
            {"number": 42, "title": "fix: other", "head": "sim-gaia"},
        ]},
    ],
    "heads": [
        {"name": "sim-gaia", "room": "cyborganic", "status": "idle",
         "tmux": {"window": 3, "pane": "%7"}},
        {"name": "data-gaia", "room": "cyborganic", "status": "idle", "tmux": None},
    ],
}


def test_resolve_lead_uses_config_map():
    assert orch.resolve_lead("cyborganic", {"cyborganic": "sim-gaia"}) == "sim-gaia"
    assert orch.resolve_lead("cribdar", {"cyborganic": "sim-gaia"}) is None


def test_lead_pane_found_and_missing():
    assert orch.lead_pane(FLEET, "sim-gaia") == ("%7", "idle")
    assert orch.lead_pane(FLEET, "data-gaia") == (None, "idle")   # no tmux pane
    assert orch.lead_pane(FLEET, "ghost") == (None, None)


def test_head_open_prs_filters_by_worker():
    prs = orch.head_open_prs(FLEET, "cyborganic", "data-gaia")
    assert [p["number"] for p in prs] == [41]
    assert orch.head_open_prs(FLEET, "nope", "data-gaia") == []


# --------------------------------------------------------------------------- notify message
def test_build_notify_contains_the_essentials():
    msg = orch.build_notify(
        worker="data-gaia", room="cyborganic", milestone="R12", dispatch_n=3, cap=8,
        branch="feat/bus-v2", ahead=4, last_commit="feat: bus v2 relay",
        open_prs=[{"number": 41, "title": "feat: gaia bus v2"}],
        handoff="Opened PR #41; needs review. Suggest wiring the heartbeat next.",
    )
    for needle in ("data-gaia", "cyborganic", "R12", "3/8", "feat/bus-v2", "PR #41",
                   "REVIEW", "escalate", "merge"):
        assert needle in msg
    assert len(msg) <= orch.NOTIFY_MAX_CHARS


def test_build_notify_caps_length():
    msg = orch.build_notify(
        worker="w", room="r", milestone="M", dispatch_n=1, cap=8,
        branch=None, ahead=0, last_commit=None, open_prs=[],
        handoff="x" * 20000,
    )
    assert len(msg) <= orch.NOTIFY_MAX_CHARS
    assert msg.endswith("…")


def test_scrub_secrets_in_handoff_path():
    dirty = "pushed with token=ghp_abcdefghijklmnop1234 done"
    assert "ghp_" not in orch.scrub_secrets(dirty)
    assert "[REDACTED]" in orch.scrub_secrets(dirty)


# --------------------------------------------------------------------------- relay job shape
def test_input_job_mirrors_console_shape():
    job = orch.input_job("sim-gaia", "%7", "hello", 1780000000.9)
    assert set(job) == {"id", "head", "pane", "text", "by", "ts"}
    assert job["head"] == "sim-gaia"
    assert job["pane"] == "%7"
    assert job["by"] == "hq-orchestrator"
    assert job["ts"] == 1780000000
    assert isinstance(job["id"], str) and len(job["id"]) == 12


# --------------------------------------------------------------------------- budget reset
def test_room_state_resets_on_rearm():
    state = {}
    intent1 = {"milestone": "R12", "requested_at": 100}
    rs = orch.room_state_for(state, "cyborganic", intent1)
    rs["dispatches"] = 8
    rs["paused"] = {"reason": "cap-reached", "ts": 123}

    # same arming -> same slot (pause + budget persist)
    again = orch.room_state_for(state, "cyborganic", intent1)
    assert again["dispatches"] == 8 and again["paused"]

    # re-arming (new requested_at) -> fresh budget, pause cleared
    fresh = orch.room_state_for(state, "cyborganic", {"milestone": "R13", "requested_at": 200})
    assert fresh["dispatches"] == 0 and fresh["paused"] is None
