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
