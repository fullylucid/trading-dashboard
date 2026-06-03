"""Redis-backed store for FinTube — channel registry + distilled-video ledger."""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

try:
    import redis
except Exception:  # noqa: BLE001
    redis = None  # type: ignore

logger = logging.getLogger("fintube.store")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

CHANNELS_KEY = "fintube:channels"
TOPICS_KEY = "fintube:topics"      # list of discovery search queries (the scout's brief)
FEED_KEY = "fintube:feed"          # list of distilled-video JSON (newest appended)
SEEN_KEY = "fintube:seen"          # set of video ids already distilled
FEED_MAX = 400

CATEGORIES = ["finance", "ai-coding", "science", "engineering", "general"]

# Discovery search queries for the scout. Tech/strategy weighted (finance ideas are
# already covered by the curated channel registry above); a couple of high-signal quant
# queries keep light finance coverage. Editable at runtime via /api/fintube/topics.
SEED_TOPICS = [
    # strategies: indicator algos & trading-bot architectures
    {"id": "algo-trading-py", "query": "algorithmic trading strategy python backtest", "category": "finance"},
    {"id": "trading-bot-arch", "query": "trading bot architecture build", "category": "engineering"},
    {"id": "custom-indicator", "query": "custom tradingview indicator pine script strategy", "category": "finance"},
    {"id": "quant-strategy", "query": "quantitative trading strategy explained", "category": "finance"},
    # AI agent enhancements
    {"id": "ai-agents", "query": "AI agent architecture LLM tutorial", "category": "ai-coding"},
    {"id": "agent-frameworks", "query": "new AI agent framework 2026", "category": "ai-coding"},
    {"id": "claude-agents", "query": "Claude agent SDK MCP server build", "category": "ai-coding"},
    # new repos & feature ideas
    {"id": "new-ai-tools", "query": "new open source AI developer tool", "category": "ai-coding"},
    {"id": "github-trending-ai", "query": "github trending AI project walkthrough", "category": "ai-coding"},
]

# seeded once if the registry is empty
SEED_CHANNELS = [
    {"id": "UCJtfma0mE_XrBAD9uakcjfA", "handle": "FelixFriends", "name": "Felix & Friends (Goat Academy)", "category": "finance"},
    {"id": "UCnMn36GT_H0X-w5_ckLtlgQ", "handle": "FinancialEducation", "name": "Financial Education", "category": "finance"},
    {"id": "UCV6KDgJskWaEckne5aPA0aQ", "handle": "grahamstephan", "name": "Graham Stephan", "category": "finance"},
    {"id": "UCUvvj5lwue7PspotMDjk5UA", "handle": "meetkevin", "name": "Meet Kevin", "category": "finance"},
    {"id": "UC0BGhWsIbV7Dm-lsvhdlMbA", "handle": "ziptrader", "name": "ZipTrader", "category": "finance"},
    {"id": "UC-m6zNItyoDk5lSykDlhE4Q", "handle": "stockedup", "name": "StockedUp", "category": "finance"},
]

_client: Optional["redis.Redis"] = None


def r() -> Optional["redis.Redis"]:
    global _client
    if redis is None:
        return None
    if _client is None:
        try:
            _client = redis.from_url(REDIS_URL, decode_responses=True)
            _client.ping()
        except Exception as e:  # noqa: BLE001
            logger.warning("fintube redis unavailable: %s", e)
            _client = None
    return _client


# ---------------------------------------------------------------- channels
def list_channels() -> List[Dict[str, Any]]:
    c = r()
    if c is None:
        return []
    raw = c.get(CHANNELS_KEY)
    if not raw:
        c.set(CHANNELS_KEY, json.dumps(SEED_CHANNELS))
        return list(SEED_CHANNELS)
    return json.loads(raw)


def add_channel(ch: Dict[str, Any]) -> List[Dict[str, Any]]:
    c = r()
    if c is None:
        return []
    chans = list_channels()
    if not any(x["id"] == ch["id"] for x in chans):
        chans.append(ch)
        c.set(CHANNELS_KEY, json.dumps(chans))
    return chans


def remove_channel(channel_id: str) -> List[Dict[str, Any]]:
    c = r()
    if c is None:
        return []
    chans = [x for x in list_channels() if x["id"] != channel_id]
    c.set(CHANNELS_KEY, json.dumps(chans))
    return chans


# ---------------------------------------------------------------- topics (scout)
def list_topics() -> List[Dict[str, Any]]:
    c = r()
    if c is None:
        return list(SEED_TOPICS)
    raw = c.get(TOPICS_KEY)
    if not raw:
        c.set(TOPICS_KEY, json.dumps(SEED_TOPICS))
        return list(SEED_TOPICS)
    return json.loads(raw)


def add_topic(topic: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Add or update a discovery query. Keyed by `id` (slug); regenerated from the
    query text if absent."""
    c = r()
    if c is None:
        return []
    tid = topic.get("id") or re.sub(r"[^a-z0-9]+", "-", topic.get("query", "").lower()).strip("-")[:40]
    cat = topic.get("category") if topic.get("category") in CATEGORIES else "general"
    entry = {"id": tid, "query": topic.get("query", "").strip(), "category": cat,
             "enabled": topic.get("enabled", True)}
    topics = [t for t in list_topics() if t.get("id") != tid]
    topics.append(entry)
    c.set(TOPICS_KEY, json.dumps(topics))
    return topics


def remove_topic(topic_id: str) -> List[Dict[str, Any]]:
    c = r()
    if c is None:
        return []
    topics = [t for t in list_topics() if t.get("id") != topic_id]
    c.set(TOPICS_KEY, json.dumps(topics))
    return topics


# ---------------------------------------------------------------- video feed
def already_seen(video_id: str) -> bool:
    c = r()
    return bool(c and c.sismember(SEEN_KEY, video_id))


def save_video(doc: Dict[str, Any]) -> None:
    c = r()
    if c is None:
        return
    c.sadd(SEEN_KEY, doc["video_id"])
    c.rpush(FEED_KEY, json.dumps(doc))
    c.ltrim(FEED_KEY, -FEED_MAX, -1)


def get_feed(limit: int = 60, category: Optional[str] = None) -> List[Dict[str, Any]]:
    c = r()
    if c is None:
        return []
    docs = [json.loads(x) for x in c.lrange(FEED_KEY, -400, -1)]
    if category and category != "all":
        docs = [d for d in docs if d.get("category") == category]
    docs.reverse()  # newest first
    return docs[:limit]


def get_video(video_id: str) -> Optional[Dict[str, Any]]:
    c = r()
    if c is None:
        return None
    for x in c.lrange(FEED_KEY, 0, -1):
        d = json.loads(x)
        if d.get("video_id") == video_id:
            return d
    return None
