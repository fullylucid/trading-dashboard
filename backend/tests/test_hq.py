"""Tests for Hydra HQ Slice 1 — the /api/hq/fleet passthrough and the collector's pure
status/redaction/room-derivation helpers.

Two isolated surfaces, no network/Redis/host I/O:
- ``hq_routes.fleet`` over a fake Redis via an isolated TestClient (passthrough + miss).
- ``hq_collector`` pure functions, loaded by path (it lives in scripts/, not on sys.path).
"""

import importlib.util
import json
from pathlib import Path

import pytest

import hq_routes


# --------------------------------------------------------------------------- #
# /api/hq/fleet passthrough
#
# TestClient (httpx) is imported lazily so this module still COLLECTS where httpx
# isn't installed (the host dev env); httpx ships in requirements.txt so these run
# in the backend/CI env. The pure-helper tests below run everywhere.
# --------------------------------------------------------------------------- #
class _FakeRedis:
    def __init__(self, store=None):
        self.store = store or {}

    def ping(self):
        return True

    def get(self, k):
        return self.store.get(k)


def _client(monkeypatch, redis_obj):
    pytest.importorskip("httpx")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    monkeypatch.setattr(hq_routes, "_r", lambda: redis_obj)
    app = FastAPI()
    app.include_router(hq_routes.hq_router)
    return TestClient(app)


def test_fleet_passthrough(monkeypatch):
    snap = {"generated_at": 1780000000, "rooms": [], "heads": [{"name": "charts"}]}
    c = _client(monkeypatch, _FakeRedis({"hq:fleet": json.dumps(snap)}))
    out = c.get("/api/hq/fleet").json()
    assert out["available"] is True
    assert out["heads"][0]["name"] == "charts"
    assert out["generated_at"] == 1780000000


def test_fleet_missing_key_returns_unavailable(monkeypatch):
    c = _client(monkeypatch, _FakeRedis({"hq:fleet": None}))
    assert c.get("/api/hq/fleet").json() == {"available": False}


def test_fleet_no_redis_returns_unavailable(monkeypatch):
    c = _client(monkeypatch, None)
    assert c.get("/api/hq/fleet").json() == {"available": False}


def test_fleet_bad_json_returns_unavailable(monkeypatch):
    c = _client(monkeypatch, _FakeRedis({"hq:fleet": "{not json"}))
    assert c.get("/api/hq/fleet").json() == {"available": False}


# --------------------------------------------------------------------------- #
# /api/hq/room/{id}
# --------------------------------------------------------------------------- #
_FLEET = {
    "generated_at": 1780000000,
    "rooms": [
        {"id": "cribdar", "name": "Cribdar", "repo": "fullylucid/cribdar", "heads": ["cribdar"], "open_prs": []},
    ],
    "heads": [
        {"name": "cribdar", "room": "cribdar"},
        {"name": "charts", "room": "trading-dashboard"},
    ],
}
_ROOMS = {"rooms": {"cribdar": {"docs": [{"key": "readme", "label": "README", "path": "README.md", "markdown": "# Hi"}]}}}


def test_room_merges_heads_and_docs(monkeypatch):
    c = _client(monkeypatch, _FakeRedis({"hq:fleet": json.dumps(_FLEET), "hq:rooms": json.dumps(_ROOMS)}))
    out = c.get("/api/hq/room/cribdar").json()
    assert out["available"] is True
    assert out["room"]["name"] == "Cribdar"
    assert out["room"]["docs"][0]["label"] == "README"
    assert [h["name"] for h in out["heads"]] == ["cribdar"]  # only this room's heads


def test_room_unknown_returns_404(monkeypatch):
    c = _client(monkeypatch, _FakeRedis({"hq:fleet": json.dumps(_FLEET)}))
    assert c.get("/api/hq/room/nope").status_code == 404


def test_room_no_docs_key_still_works(monkeypatch):
    c = _client(monkeypatch, _FakeRedis({"hq:fleet": json.dumps(_FLEET)}))
    out = c.get("/api/hq/room/cribdar").json()
    assert out["available"] is True
    assert out["room"]["docs"] == []


def test_room_no_snapshot_unavailable(monkeypatch):
    c = _client(monkeypatch, _FakeRedis({"hq:fleet": None}))
    assert c.get("/api/hq/room/cribdar").json() == {"available": False}


# --------------------------------------------------------------------------- #
# /api/hq/memory + /api/hq/memory/{name}
# --------------------------------------------------------------------------- #
_MEMORY = {
    "generated_at": 1780000000,
    "index": [
        {"name": "alpha", "title": "Alpha", "description": "a", "type": "project", "scope": None, "updated": "2026-06-01", "n_links": 1},
        {"name": "beta", "title": "Beta", "description": "b", "type": "feedback", "scope": None, "updated": None, "n_links": 0},
    ],
    "docs": {
        "alpha": {"name": "alpha", "title": "Alpha", "description": "a", "type": "project",
                  "body": "links [[beta]] and [[ghost]]", "links_out": ["beta", "ghost"], "links_in": []},
        "beta": {"name": "beta", "title": "Beta", "description": "b", "type": "feedback",
                 "body": "the beta doc", "links_out": [], "links_in": ["alpha"]},
    },
}


def test_memory_index(monkeypatch):
    c = _client(monkeypatch, _FakeRedis({"hq:memory": json.dumps(_MEMORY)}))
    out = c.get("/api/hq/memory").json()
    assert out["available"] is True
    assert [e["name"] for e in out["index"]] == ["alpha", "beta"]
    assert "docs" not in out  # index endpoint stays lightweight


def test_memory_doc_annotates_broken_links(monkeypatch):
    c = _client(monkeypatch, _FakeRedis({"hq:memory": json.dumps(_MEMORY)}))
    out = c.get("/api/hq/memory/alpha").json()
    assert out["available"] is True
    assert out["doc"]["links_in"] == []
    assert {"name": "beta", "exists": True} in out["doc"]["links_out"]
    assert {"name": "ghost", "exists": False} in out["doc"]["links_out"]  # broken link flagged


def test_memory_doc_unknown_404(monkeypatch):
    c = _client(monkeypatch, _FakeRedis({"hq:memory": json.dumps(_MEMORY)}))
    assert c.get("/api/hq/memory/nope").status_code == 404


def test_memory_no_snapshot_unavailable(monkeypatch):
    c = _client(monkeypatch, _FakeRedis({"hq:memory": None}))
    assert c.get("/api/hq/memory").json() == {"available": False}


# --------------------------------------------------------------------------- #
# collector memory helpers (pure)
# --------------------------------------------------------------------------- #
_FM_DOC = """---
name: trading-dashboard-project
description: "Trading dashboard — repo, stack"
metadata:
  type: project
  scope: trading-dashboard
  updated: 2026-05-30
---

Body line one. See [[trading-dashboard-operating-guardrails]] and [[hydra-heads]].
Also [[hydra-heads]] again (dedup) and an aliased [[box-hosting-architecture|the box]].
"""


def test_split_frontmatter():
    fm, body = hq.split_frontmatter(_FM_DOC)
    assert "name: trading-dashboard-project" in fm
    assert body.startswith("Body line one.")
    # no frontmatter -> ("", text)
    assert hq.split_frontmatter("no fence here") == ("", "no fence here")


def test_parse_frontmatter():
    fm = hq.parse_frontmatter(_FM_DOC)
    assert fm["name"] == "trading-dashboard-project"
    assert fm["description"] == "Trading dashboard — repo, stack"  # quotes stripped
    assert fm["metadata"]["type"] == "project"
    assert fm["metadata"]["scope"] == "trading-dashboard"
    assert fm["metadata"]["updated"] == "2026-05-30"


def test_extract_wikilinks_dedups_and_unaliases():
    links = hq.extract_wikilinks(_FM_DOC)
    assert links == [
        "trading-dashboard-operating-guardrails",
        "hydra-heads",
        "box-hosting-architecture",  # alias [[a|b]] -> a, deduped
    ]


def test_extract_wikilinks_empty():
    assert hq.extract_wikilinks("") == []
    assert hq.extract_wikilinks("no links") == []


# --------------------------------------------------------------------------- #
# activity feed pure helpers
# --------------------------------------------------------------------------- #
_PRS = [
    {"number": 82, "title": "feat: X", "state": "MERGED", "headRefName": "feat/x",
     "mergeable": "MERGEABLE", "createdAt": "2026-06-06T15:59:54Z", "mergedAt": "2026-06-06T16:00:16Z"},
    {"number": 80, "title": "feat: mem", "state": "OPEN", "headRefName": "feat/hq-memory",
     "mergeable": "MERGEABLE", "createdAt": "2026-06-06T15:53:25Z", "mergedAt": None},
    {"number": 5, "title": "ancient", "state": "MERGED", "headRefName": "old",
     "mergeable": "CONFLICTING", "createdAt": "2020-01-01T00:00:00Z", "mergedAt": "2020-01-02T00:00:00Z"},
]


def test_open_prs_from_filters_to_open():
    out = hq.open_prs_from(_PRS)
    assert [p["number"] for p in out] == [80]
    assert out[0]["mergeable"] is True
    assert out[0]["branch"] == "feat/hq-memory"


def test_pr_events_within_window_only():
    since = hq._iso_to_epoch("2026-06-01T00:00:00Z")
    ev = hq.pr_events_from(_PRS, "o/r", "room1", {"feat/hq-memory": "hq"}, since)
    kinds = sorted((e["kind"], e["number"]) for e in ev)
    # #82 opened+merged, #80 opened (still open); ancient #5 excluded by window
    assert ("pr_opened", 82) in kinds
    assert ("pr_merged", 82) in kinds
    assert ("pr_opened", 80) in kinds
    assert all(e["number"] != 5 for e in ev)
    # head mapping via branch_to_head
    assert next(e for e in ev if e["number"] == 80)["head"] == "hq"
    assert next(e for e in ev if e["number"] == 80)["url"] == "https://github.com/o/r/pull/80"


def test_finalize_activity_dedups_sorts_caps():
    items = [
        {"kind": "commit", "sha": "a", "ts": 100, "text": "a"},
        {"kind": "commit", "sha": "a", "ts": 100, "text": "dup"},   # dup by (kind,sha)
        {"kind": "pr_merged", "number": 9, "ts": 300, "text": "p"},
        {"kind": "commit", "sha": "b", "ts": 200, "text": "b"},
        {"kind": "commit", "sha": "c", "ts": None, "text": "skip"},  # no ts -> dropped
    ]
    out = hq.finalize_activity(items, cap=2)
    assert [x["ts"] for x in out] == [300, 200]  # newest-first, capped at 2
    full = hq.finalize_activity(items)
    assert len(full) == 3  # one dup + one None removed from 5


# --------------------------------------------------------------------------- #
# collector pure helpers
# --------------------------------------------------------------------------- #
def _load_collector():
    path = Path(__file__).resolve().parents[2] / "scripts" / "hq_collector.py"
    spec = importlib.util.spec_from_file_location("hq_collector", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hq = _load_collector()


@pytest.mark.parametrize("workdir,room_id,room_name", [
    ("/home/user/hydra-worktrees/trading-dashboard__hq", "trading-dashboard", "Trading Dashboard"),
    ("/home/user/hydra-worktrees/cyborganic__data-gaia", "cyborganic", "Cyborganic"),
    ("/home/user/cribdar", "cribdar", "Cribdar"),
    ("/home/user/Employ", "Employ", "Employ"),
    ("/home/user/trading-dashboard/", "trading-dashboard", "Trading Dashboard"),
])
def test_room_for(workdir, room_id, room_name):
    assert hq.room_for(workdir) == (room_id, room_name)


def test_transcript_dir_name():
    assert hq.transcript_dir_name("/home/user/hydra-worktrees/trading-dashboard__hq") == \
        "-home-user-hydra-worktrees-trading-dashboard--hq"
    assert hq.transcript_dir_name("/home/user/cribdar") == "-home-user-cribdar"


@pytest.mark.parametrize("raw,must_not_contain", [
    ("using key ghp_ABCDEFGHIJKLMNOP1234567890", "ghp_ABCDEF"),
    ("token=supersecretvalue123", "supersecretvalue123"),
    ("aws AKIAIOSFODNN7EXAMPLE done", "AKIAIOSFODNN7EXAMPLE"),
    ("sk-abc123def456ghi789jkl", "sk-abc123"),
])
def test_redact_scrubs_secrets(raw, must_not_contain):
    out = hq.redact(raw)
    assert must_not_contain not in out
    assert "[REDACTED]" in out


def test_redact_truncates_and_collapses_whitespace():
    out = hq.redact("a\n\n  lot   of    space")
    assert "  " not in out
    long = hq.redact("x" * 500)
    assert len(long) <= hq.CURRENT_MAX_LEN


def test_redact_empty():
    assert hq.redact(None) == ""
    assert hq.redact("") == ""


@pytest.mark.parametrize("pane_cmd,age,stop,waiting,expected", [
    (None, None, None, False, "offline"),
    ("sh", 5, None, False, "offline"),
    ("claude", 5, "tool_use", True, "waiting-input"),     # waiting wins
    ("claude", 5, None, False, "working"),                # recent, mid-turn
    ("claude", 5, "end_turn", False, "idle"),             # turn ended
    ("claude", 9999, None, False, "idle"),                # stale -> idle
    ("claude", None, None, False, "idle"),                # no transcript activity
])
def test_derive_status(pane_cmd, age, stop, waiting, expected):
    assert hq.derive_status(pane_cmd, age, stop, waiting) == expected


def test_pane_is_waiting():
    assert hq.pane_is_waiting("│ Do you want to proceed?\n❯ 1. Yes")
    assert hq.pane_is_waiting("press ENTER to continue")
    assert not hq.pane_is_waiting("⏵⏵ auto mode on · Remote Control active")
    assert not hq.pane_is_waiting(None)


def test_pane_is_rc_paired():
    assert hq.pane_is_rc_paired("...\n  Remote Control active")
    assert not hq.pane_is_rc_paired("just a prompt")


@pytest.mark.parametrize("url,expected", [
    ("git@github.com:fullylucid/trading-dashboard.git", "fullylucid/trading-dashboard"),
    ("https://github.com/fullylucid/cribdar.git", "fullylucid/cribdar"),
    ("https://github.com/fullylucid/cribdar", "fullylucid/cribdar"),
    ("", None),
])
def test_parse_remote(url, expected):
    assert hq.parse_remote(url) == expected
