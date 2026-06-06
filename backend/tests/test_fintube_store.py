"""Unit tests for fintube.store.remove_video against a minimal in-memory Redis fake.

remove_video rewrites the feed list and conditionally clears the SEEN guard — pin both the
'kept the rest' behaviour and the keep_seen semantics that stop a deleted video from being
silently re-added by the scout/refresh.
"""

import json

from fintube import store


class MiniRedis:
    """Just enough Redis for store.remove_video / save_video / already_seen."""
    def __init__(self):
        self.lists: dict = {}
        self.sets: dict = {}

    def lrange(self, k, a, b):
        lst = self.lists.get(k, [])
        if a == 0 and b == -1:
            return list(lst)
        return lst[a: (None if b == -1 else b + 1)]

    def delete(self, *ks):
        for k in ks:
            self.lists.pop(k, None)

    def rpush(self, k, *vals):
        self.lists.setdefault(k, []).extend(vals)

    def ltrim(self, k, a, b):
        self.lists[k] = self.lists.get(k, [])[a: (None if b == -1 else b + 1)]

    def sadd(self, k, *vals):
        self.sets.setdefault(k, set()).update(vals)

    def srem(self, k, *vals):
        self.sets.setdefault(k, set()).difference_update(vals)

    def sismember(self, k, v):
        return v in self.sets.get(k, set())

    def pipeline(self):
        return self           # execute-immediately fake

    def execute(self):
        pass


def _seed(mini, docs):
    mini.lists[store.FEED_KEY] = [json.dumps(d) for d in docs]
    mini.sets[store.SEEN_KEY] = {d["video_id"] for d in docs}


def _ids(mini):
    return [json.loads(x)["video_id"] for x in mini.lists.get(store.FEED_KEY, [])]


def test_remove_video_keeps_the_rest(monkeypatch):
    mini = MiniRedis()
    _seed(mini, [{"video_id": "a"}, {"video_id": "b"}, {"video_id": "c"}])
    monkeypatch.setattr(store, "r", lambda: mini)

    assert store.remove_video("b") is True
    assert _ids(mini) == ["a", "c"]


def test_remove_video_keep_seen_default_blocks_readd(monkeypatch):
    mini = MiniRedis()
    _seed(mini, [{"video_id": "a"}, {"video_id": "b"}])
    monkeypatch.setattr(store, "r", lambda: mini)

    store.remove_video("a")                       # keep_seen=True by default
    assert store.already_seen("a") is True        # stays suppressed from auto-discovery


def test_remove_video_keep_seen_false_allows_readd(monkeypatch):
    mini = MiniRedis()
    _seed(mini, [{"video_id": "a"}, {"video_id": "b"}])
    monkeypatch.setattr(store, "r", lambda: mini)

    store.remove_video("a", keep_seen=False)
    assert store.already_seen("a") is False


def test_remove_video_missing_returns_false(monkeypatch):
    mini = MiniRedis()
    _seed(mini, [{"video_id": "a"}])
    monkeypatch.setattr(store, "r", lambda: mini)

    assert store.remove_video("zzz") is False
    assert _ids(mini) == ["a"]


def test_remove_last_video_empties_feed(monkeypatch):
    mini = MiniRedis()
    _seed(mini, [{"video_id": "only"}])
    monkeypatch.setattr(store, "r", lambda: mini)

    assert store.remove_video("only") is True
    assert _ids(mini) == []
