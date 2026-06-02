"""Redis-backed store for FinTube — channel registry + distilled-video ledger."""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

try:
    import redis
except Exception:  # noqa: BLE001
    redis = None  # type: ignore

logger = logging.getLogger("fintube.store")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

CHANNELS_KEY = "fintube:channels"
FEED_KEY = "fintube:feed"          # list of distilled-video JSON (newest appended)
SEEN_KEY = "fintube:seen"          # set of video ids already distilled
FEED_MAX = 400

CATEGORIES = ["finance", "ai-coding", "science", "engineering", "general"]

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
