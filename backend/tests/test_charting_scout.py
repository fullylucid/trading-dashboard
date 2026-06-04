"""Tests for the charting-ideas scout: arXiv parsing, AI→spec generation (worker
stubbed), the Redis idea ledger, scout orchestration, and accept→arsenal — all
hermetic (fake redis + a fake agent_bridge injected via sys.modules)."""

import asyncio
import json
import sys
import types

import pytest

import charting_scout as scout


# --------------------------------------------------------------------------- #
# Fake redis supporting the list+set ops the scout uses (pipeline = immediate).
# --------------------------------------------------------------------------- #
class _FakeRedis:
    def __init__(self):
        self.lists: dict = {}
        self.sets: dict = {}

    def ping(self):
        return True

    def rpush(self, key, *vals):
        self.lists.setdefault(key, []).extend(vals)
        return len(self.lists[key])

    def lrange(self, key, start, end):
        lst = self.lists.get(key, [])
        n = len(lst)
        s = start if start >= 0 else max(0, n + start)
        e = (end if end >= 0 else n + end) + 1
        return lst[s:e]

    def ltrim(self, key, start, end):
        self.lists[key] = self.lrange(key, start, end)

    def delete(self, key):
        self.lists.pop(key, None)
        self.sets.pop(key, None)
        return 1

    def sadd(self, key, *vals):
        self.sets.setdefault(key, set()).update(vals)
        return len(vals)

    def sismember(self, key, val):
        return val in self.sets.get(key, set())

    def pipeline(self):  # immediate-execution pipeline
        return self

    def execute(self):
        return []


@pytest.fixture
def fake_redis(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(scout, "_r", lambda: fake)
    return fake


def _stub_worker(monkeypatch, return_json: dict | str):
    """Inject a fake agent_bridge whose run_agent_job returns canned output."""
    mod = types.ModuleType("agent_bridge")
    payload = return_json if isinstance(return_json, str) else json.dumps(return_json)

    async def _run(content, kind="data", timeout=None):
        return payload

    mod.run_agent_job = _run  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "agent_bridge", mod)


_VALID_SPEC = {
    "name": "Test EMA",
    "pane": "overlay",
    "steps": [
        {"id": "c", "op": "series", "ref": "close"},
        {"id": "e", "op": "ema", "input": "c", "period": 10},
    ],
    "plots": [{"step": "e", "label": "EMA10"}],
}


# --------------------------------------------------------------------------- #
# arXiv parsing
# --------------------------------------------------------------------------- #
def test_parse_arxiv():
    xml = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>A Momentum Indicator</title>
        <summary>We propose an indicator based on EMA crossovers.</summary>
        <id>http://arxiv.org/abs/2601.00001</id>
      </entry>
      <entry>
        <title>Another Paper</title>
        <summary>Volatility scaling for signals.</summary>
        <id>http://arxiv.org/abs/2601.00002</id>
      </entry>
    </feed>"""
    out = scout._parse_arxiv(xml, limit=5)
    assert len(out) == 2
    assert out[0]["source_type"] == "arxiv"
    assert "Momentum" in out[0]["title"]
    assert out[0]["url"].endswith("2601.00001")


# --------------------------------------------------------------------------- #
# AI -> spec generation
# --------------------------------------------------------------------------- #
def test_generate_idea_valid_spec(monkeypatch):
    _stub_worker(monkeypatch, {
        "title": "Test EMA", "technique": "ema", "description": "d",
        "why_useful": "trend", "confidence": 0.8, "spec": _VALID_SPEC,
    })
    idea = asyncio.run(scout.generate_idea("T", "text", "youtube", "http://u/1"))
    assert idea is not None
    assert idea["spec_valid"] is True
    assert idea["spec"]["short_name"]  # normalized
    assert idea["confidence"] == 0.8
    assert idea["accepted"] is False


def test_generate_idea_invalid_spec_kept_with_errors(monkeypatch):
    _stub_worker(monkeypatch, {
        "title": "Bad", "confidence": 0.5,
        "spec": {"name": "x", "steps": [], "plots": []},  # invalid
    })
    idea = asyncio.run(scout.generate_idea("T", "text", "arxiv", "http://u/2"))
    assert idea is not None
    assert idea["spec_valid"] is False
    assert idea["spec_errors"]


def test_generate_idea_non_json_returns_none(monkeypatch):
    _stub_worker(monkeypatch, "sorry, no indicator here")
    idea = asyncio.run(scout.generate_idea("T", "text", "youtube", "http://u/3"))
    assert idea is None


# --------------------------------------------------------------------------- #
# Ledger + dedupe
# --------------------------------------------------------------------------- #
def test_ledger_save_list_dedupe(fake_redis):
    scout._save_idea({"id": "a", "source_url": "http://u/a", "title": "A"})
    scout._save_idea({"id": "b", "source_url": "http://u/b", "title": "B"})
    ideas = scout.list_ideas()
    assert [i["id"] for i in ideas] == ["b", "a"]  # newest first
    assert scout._seen("http://u/a") is True
    assert scout._seen("http://u/zzz") is False
    assert scout.get_idea("a")["title"] == "A"
    assert scout.delete_idea("a") is True
    assert [i["id"] for i in scout.list_ideas()] == ["b"]


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def test_run_scout_stages_ideas(monkeypatch, fake_redis):
    monkeypatch.setattr(scout, "SOURCES", {
        "fake": {"adapter": lambda: [
            {"title": "T", "text": "ema crossover indicator", "url": "http://u/x", "source_type": "fake"},
        ], "implemented": True},
    })
    _stub_worker(monkeypatch, {
        "title": "Test EMA", "confidence": 0.7, "spec": _VALID_SPEC,
    })
    result = asyncio.run(scout.run_scout(sources=["fake"], max_ideas=5))
    assert result["staged"] == 1
    assert result["by_source"]["fake"] == 1
    assert len(scout.list_ideas()) == 1


def test_run_scout_awaits_async_adapter(monkeypatch, fake_redis):
    async def aadapter():
        return [{"title": "T", "text": "ema crossover", "url": "http://u/async", "source_type": "fake"}]

    monkeypatch.setattr(scout, "SOURCES", {"fake": {"adapter": aadapter, "implemented": True}})
    _stub_worker(monkeypatch, {"title": "Test EMA", "confidence": 0.7, "spec": _VALID_SPEC})
    result = asyncio.run(scout.run_scout(sources=["fake"], max_ideas=5))
    assert result["staged"] == 1
    assert len(scout.list_ideas()) == 1


def test_youtube_candidates_dedicated_discovery(monkeypatch, fake_redis):
    """Dedicated discovery: runs charting queries, pulls transcripts, drops no-transcript."""
    ft = types.ModuleType("fintube")
    disc = types.ModuleType("fintube.discover")
    trans = types.ModuleType("fintube.transcripts")
    disc.discover = lambda topics, lookback_days=21, per_query=8: [  # type: ignore[attr-defined]
        {"url": "http://yt/1", "title": "Vid 1"},
        {"url": "http://yt/2", "title": "Vid 2"},  # no transcript -> dropped
    ]
    trans.fetch_transcript = lambda url: (  # type: ignore[attr-defined]
        "transcript about RSI divergence strategy" if url.endswith("1") else None
    )
    ft.discover = disc  # type: ignore[attr-defined]
    ft.transcripts = trans  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fintube", ft)
    monkeypatch.setitem(sys.modules, "fintube.discover", disc)
    monkeypatch.setitem(sys.modules, "fintube.transcripts", trans)

    out = asyncio.run(scout.youtube_candidates(limit=5))
    assert len(out) == 1  # only Vid 1 had a transcript
    assert out[0]["source_type"] == "youtube"
    assert "RSI" in out[0]["text"]
    assert scout.CHARTING_TOPICS  # the dedicated brief exists


# --------------------------------------------------------------------------- #
# Accept -> arsenal
# --------------------------------------------------------------------------- #
def test_accept_idea_promotes_to_arsenal(monkeypatch, fake_redis):
    import indicator_arsenal
    saved = {}
    monkeypatch.setattr(
        indicator_arsenal, "save_item",
        lambda spec, source="manual", tags=None: saved.update(
            {"id": "ars-1", "spec": spec, "source": source, "tags": tags}
        ) or {"id": "ars-1"},
    )
    scout._save_idea({
        "id": "idea1", "source_url": "http://u/1", "title": "X", "technique": "ema",
        "source_type": "arxiv", "spec_valid": True, "spec": _VALID_SPEC, "accepted": False,
    })
    item = scout.accept_idea("idea1")
    assert item["id"] == "ars-1"
    assert saved["source"] == "scout:arxiv"
    assert scout.get_idea("idea1")["accepted"] is True
    assert scout.get_idea("idea1")["arsenal_id"] == "ars-1"


def test_accept_idea_rejects_invalid(monkeypatch, fake_redis):
    scout._save_idea({"id": "bad", "source_url": "u", "spec_valid": False, "spec": None})
    with pytest.raises(ValueError):
        scout.accept_idea("bad")
    with pytest.raises(KeyError):
        scout.accept_idea("nonexistent")
