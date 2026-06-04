"""Charting-ideas scout — mines technical-charting techniques from sources, asks
the AI to express each as a CONSTRAINED indicator spec, and stages them as "idea
cards" for human review → demo → accept-into-arsenal.

Pipeline (mirrors the proven FinTube scout shape):

    source adapters → candidate {title, text, url}      (what techniques are out there)
        → generate_idea() via the Opus worker            (AI emits an idea card + a spec)
            → validate_spec()                            (only well-formed bounded specs survive)
                → Redis `charting:ideas` ledger          (staged for review)
                    → accept_idea() → indicator_arsenal  (human blesses it into the toolkit)

The AI never emits runnable code — only a constrained spec in the engine's op
grammar (injected into the prompt), which is validated before storage. A spec it
gets wrong is kept on the card with its validation errors so it can be fixed, not
silently run. The chart demo (frontend) computes the spec over a real symbol.

Source adapters: `youtube` reuses the existing FinTube distilled feed; `arxiv` is a
real q-fin query; `tradingview` / `reddit` are stubs (they need API keys / scraping
we won't add without consent — see SOURCES).
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import re
import uuid
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    import redis
except Exception:  # noqa: BLE001
    redis = None  # type: ignore

import indicator_spec as _engine
from indicator_spec import SpecError, validate_spec

logger = logging.getLogger("charting.scout")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

IDEAS_KEY = "charting:ideas"     # list of idea-card JSON (newest appended)
SEEN_KEY = "charting:seen"       # set of source urls already processed
IDEAS_MAX = 300

_client: Optional["redis.Redis"] = None


def _r() -> Optional["redis.Redis"]:
    global _client
    if redis is None:
        return None
    if _client is None:
        try:
            _client = redis.from_url(REDIS_URL, decode_responses=True)
            _client.ping()
        except Exception as e:  # noqa: BLE001
            logger.warning("charting scout redis unavailable: %s", e)
            _client = None
    return _client


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(s: str) -> str:
    return (re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:32]) or "idea"


# ============================================================================
# Idea ledger (Redis)
# ============================================================================

def list_ideas(limit: int = 80) -> List[Dict[str, Any]]:
    c = _r()
    if c is None:
        return []
    try:
        raw = c.lrange(IDEAS_KEY, -limit, -1) or []
    except Exception:  # noqa: BLE001
        return []
    out: List[Dict[str, Any]] = []
    for v in raw:
        try:
            out.append(json.loads(v))
        except (json.JSONDecodeError, TypeError):
            continue
    out.reverse()  # newest first
    return out


def get_idea(idea_id: str) -> Optional[Dict[str, Any]]:
    for it in list_ideas(limit=IDEAS_MAX):
        if it.get("id") == idea_id:
            return it
    return None


def _save_idea(idea: Dict[str, Any]) -> None:
    c = _r()
    if c is None:
        return
    try:
        c.rpush(IDEAS_KEY, json.dumps(idea))
        c.ltrim(IDEAS_KEY, -IDEAS_MAX, -1)
        if idea.get("source_url"):
            c.sadd(SEEN_KEY, idea["source_url"])
    except Exception as e:  # noqa: BLE001
        logger.warning("save idea failed: %s", e)


def _update_idea(idea_id: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Rewrite the ledger with `patch` applied to the matching idea (small list)."""
    c = _r()
    if c is None:
        return None
    try:
        raw = c.lrange(IDEAS_KEY, 0, -1) or []
    except Exception:  # noqa: BLE001
        return None
    updated: Optional[Dict[str, Any]] = None
    new_raw: List[str] = []
    for v in raw:
        try:
            it = json.loads(v)
        except (json.JSONDecodeError, TypeError):
            new_raw.append(v)
            continue
        if it.get("id") == idea_id:
            it.update(patch)
            updated = it
        new_raw.append(json.dumps(it))
    if updated is not None:
        try:
            pipe = c.pipeline()
            pipe.delete(IDEAS_KEY)
            if new_raw:
                pipe.rpush(IDEAS_KEY, *new_raw)
            pipe.execute()
        except Exception as e:  # noqa: BLE001
            logger.warning("update idea failed: %s", e)
            return None
    return updated


def delete_idea(idea_id: str) -> bool:
    c = _r()
    if c is None:
        return False
    try:
        raw = c.lrange(IDEAS_KEY, 0, -1) or []
    except Exception:  # noqa: BLE001
        return False
    kept = [v for v in raw if _id_of(v) != idea_id]
    if len(kept) == len(raw):
        return False
    try:
        pipe = c.pipeline()
        pipe.delete(IDEAS_KEY)
        if kept:
            pipe.rpush(IDEAS_KEY, *kept)
        pipe.execute()
    except Exception:  # noqa: BLE001
        return False
    return True


def _id_of(raw: str) -> Optional[str]:
    try:
        return json.loads(raw).get("id")
    except (json.JSONDecodeError, TypeError):
        return None


def _seen(url: str) -> bool:
    c = _r()
    if c is None or not url:
        return False
    try:
        return bool(c.sismember(SEEN_KEY, url))
    except Exception:  # noqa: BLE001
        return False


# ============================================================================
# AI: idea text -> constrained indicator spec
# ============================================================================

def _ops_catalog_text() -> str:
    """Compact grammar description injected into the prompt."""
    return (
        "SERIES refs: " + ", ".join(_engine.OHLCV_SERIES) + ".\n"
        "OPS:\n"
        "  {id, op:'series', ref:<series>}\n"
        "  {id, op:'const', value:<num>}\n"
        "  {id, op:'sma'|'ema'|'wma'|'rsi'|'stddev'|'max'|'min'|'shift'|'diff', input:<id>, period:<int>}\n"
        "  {id, op:'add'|'sub'|'mul'|'div'|'cross', inputs:[<id|num>, <id|num>]}\n"
        "  {id, op:'abs', input:<id>}\n"
        "  {id, op:'clamp', input:<id>, min?:<num>, max?:<num>}\n"
        "Each step's refs must point to EARLIER step ids. pane is 'overlay' (on price) "
        "or 'separate' (sub-pane). plots pick step ids to draw.\n"
        "EXAMPLE (Bollinger): steps=[{id:'c',op:'series',ref:'close'},"
        "{id:'m',op:'sma',input:'c',period:20},{id:'sd',op:'stddev',input:'c',period:20},"
        "{id:'b',op:'mul',inputs:['sd',2]},{id:'u',op:'add',inputs:['m','b']},"
        "{id:'l',op:'sub',inputs:['m','b']}], plots=[{step:'u'},{step:'m'},{step:'l'}]."
    )


def _build_spec_prompt(title: str, text: str, source_type: str) -> str:
    catalog = _ops_catalog_text()
    body = text[:12000]
    return (
        "You are Tradeskeebot's charting R&D scout. From the source material below, "
        "identify ONE concrete, chartable technical-analysis indicator/technique and express "
        "it as a CONSTRAINED indicator spec using ONLY the grammar provided. Do not invent ops. "
        "If the material has no chartable indicator, return confidence 0 and spec null.\n\n"
        f"GRAMMAR:\n{catalog}\n\n"
        "Return ONLY JSON, no prose, no markdown fences:\n"
        '{"title":"<short indicator name>","technique":"<the method in <=6 words>",'
        '"description":"<2-3 sentences: what it measures + how it is computed>",'
        '"why_useful":"<1 sentence on the trading edge it claims>",'
        '"confidence":<0.0-1.0 how chartable+useful this is>,'
        '"spec":{"name":"<name>","pane":"overlay|separate","precision":2,'
        '"steps":[...],"plots":[{"step":"<id>","label":"<label>","color":"#00ff41"}]} }\n\n'
        f"SOURCE_TYPE: {source_type}\nSOURCE_TITLE: {title}\n\nSOURCE_MATERIAL:\n{body}"
    )


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    s = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    a, b = s.find("{"), s.rfind("}")
    if a == -1 or b == -1:
        return None
    try:
        return json.loads(s[a:b + 1])
    except Exception:  # noqa: BLE001
        return None


async def generate_idea(
    title: str, text: str, source_type: str, source_url: str, timeout: int = 180
) -> Optional[Dict[str, Any]]:
    """Ask the worker to turn source material into an idea card + validated spec.

    Returns a staged idea record (NOT yet saved), or None if the worker is
    unavailable / returned nothing usable.
    """
    try:
        from agent_bridge import run_agent_job  # lazy: avoid import coupling
    except Exception:  # noqa: BLE001
        logger.warning("agent bridge unavailable for charting scout")
        return None

    out = await run_agent_job(_build_spec_prompt(title, text, source_type), kind="data", timeout=timeout)
    parsed = _extract_json(out or "")
    if parsed is None:
        logger.info("scout: non-JSON for %s", title[:60])
        return None

    spec_in = parsed.get("spec")
    spec_norm: Optional[Dict[str, Any]] = None
    spec_valid = False
    spec_errors: List[str] = []
    if isinstance(spec_in, dict):
        try:
            spec_norm = validate_spec(spec_in)
            spec_valid = True
        except SpecError as e:
            spec_errors = e.errors
    else:
        spec_errors = ["model returned no spec"]

    name = str(parsed.get("title") or title)[:60]
    return {
        "id": f"{_slug(name)}-{uuid.uuid4().hex[:6]}",
        "title": name,
        "technique": str(parsed.get("technique") or "")[:80],
        "description": str(parsed.get("description") or "")[:600],
        "why_useful": str(parsed.get("why_useful") or "")[:300],
        "confidence": _clamp01(parsed.get("confidence")),
        "source_type": source_type,
        "source_url": source_url,
        "spec": spec_norm,
        "spec_valid": spec_valid,
        "spec_errors": spec_errors,
        "created_at": _now(),
        "accepted": False,
        "arsenal_id": None,
    }


def _clamp01(x: Any) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return 0.0


# ============================================================================
# Source adapters — each returns [{title, text, url, source_type}]
# ============================================================================

# Charting-tuned discovery queries — the scout's OWN brief, so it surfaces chartable
# techniques directly rather than scavenging FinTube's general (investment-call) feed.
CHARTING_TOPICS = [
    {"query": "custom tradingview indicator pine script tutorial", "category": "charting"},
    {"query": "trading indicator strategy explained backtest", "category": "charting"},
    {"query": "volume profile order flow trading technique", "category": "charting"},
    {"query": "RSI MACD divergence trading strategy", "category": "charting"},
    {"query": "supertrend vwap moving average crossover strategy", "category": "charting"},
    {"query": "bollinger keltner squeeze momentum indicator", "category": "charting"},
]


async def youtube_candidates(limit: int = 8, lookback_days: int = 21) -> List[Dict[str, Any]]:
    """Dedicated charting discovery: run charting-tuned YouTube queries and pull
    transcripts, reusing FinTube's discover + transcript machinery (NOT its feed).
    Returns transcript-bearing candidates for spec generation. Best-effort/async."""
    try:
        from fintube import discover as ft_discover, transcripts as ft_transcripts
    except Exception as e:  # noqa: BLE001
        logger.info("scout youtube: fintube discovery unavailable: %s", e)
        return []
    try:
        cands = await asyncio.to_thread(
            ft_discover.discover, CHARTING_TOPICS, lookback_days=lookback_days, per_query=8
        )
    except Exception as e:  # noqa: BLE001
        logger.info("scout youtube discover failed: %s", e)
        return []
    out: List[Dict[str, Any]] = []
    for c in cands:
        url = c.get("url", "")
        if not url or _seen(url):
            continue
        try:
            transcript = await asyncio.to_thread(ft_transcripts.fetch_transcript, url)
        except Exception:  # noqa: BLE001
            transcript = None
        if not transcript:
            continue
        out.append({
            "title": c.get("title", "Untitled"), "text": transcript,
            "url": url, "source_type": "youtube",
        })
        if len(out) >= limit:
            break
    return out


_ARXIV_API = "http://export.arxiv.org/api/query"
_ATOM = "{http://www.w3.org/2005/Atom}"


def _parse_arxiv(xml_text: str, limit: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for entry in root.findall(f"{_ATOM}entry"):
        title = (entry.findtext(f"{_ATOM}title") or "").strip().replace("\n", " ")
        summary = (entry.findtext(f"{_ATOM}summary") or "").strip().replace("\n", " ")
        url = (entry.findtext(f"{_ATOM}id") or "").strip()
        if not title or not summary:
            continue
        out.append({"title": title, "text": f"{title}. {summary}", "url": url, "source_type": "arxiv"})
        if len(out) >= limit:
            break
    return out


def arxiv_candidates(limit: int = 5, query: str = "technical indicator trading signal") -> List[Dict[str, Any]]:
    """Recent q-fin papers matching `query` (real arXiv Atom API; polite, no key)."""
    params = urllib.parse.urlencode({
        "search_query": f"cat:q-fin.TR AND all:{query}",
        "sortBy": "submittedDate", "sortOrder": "descending",
        "start": 0, "max_results": limit * 2,
    })
    try:
        req = urllib.request.Request(f"{_ARXIV_API}?{params}", headers={"User-Agent": "tradeskeebot-scout/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml_text = resp.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        logger.info("scout arxiv fetch failed: %s", e)
        return []
    return [c for c in _parse_arxiv(xml_text, limit) if not _seen(c["url"])]


def tradingview_candidates(limit: int = 5) -> List[Dict[str, Any]]:
    """STUB: TradingView public scripts/ideas. Needs scraping/an unofficial API we
    won't add without consent (ToS + Schyler's security posture). Wired into SOURCES
    so the seam is visible; returns [] for now."""
    logger.info("scout tradingview: adapter not implemented (returns [])")
    return []


def reddit_candidates(limit: int = 5) -> List[Dict[str, Any]]:
    """STUB: Reddit/X (FinTwit). Needs API creds; returns [] until wired."""
    logger.info("scout reddit: adapter not implemented (returns [])")
    return []


SOURCES = {
    "youtube": {"adapter": youtube_candidates, "implemented": True},
    "arxiv": {"adapter": arxiv_candidates, "implemented": True},
    "tradingview": {"adapter": tradingview_candidates, "implemented": False},
    "reddit": {"adapter": reddit_candidates, "implemented": False},
}


# ============================================================================
# Orchestration + acceptance
# ============================================================================

async def run_scout(sources: Optional[List[str]] = None, max_ideas: int = 12) -> Dict[str, Any]:
    """Gather candidates from `sources`, generate+validate a spec for each, stage them.

    Returns ``{generated, staged, by_source, skipped}``. Best-effort: a failing
    source or AI call is logged and skipped, never raises.
    """
    wanted = [s for s in (sources or list(SOURCES)) if s in SOURCES]
    candidates: List[Dict[str, Any]] = []
    by_source: Dict[str, int] = {}
    for name in wanted:
        try:
            res = SOURCES[name]["adapter"]()  # type: ignore[operator]
            if inspect.isawaitable(res):
                res = await res  # async adapters (e.g. youtube discovery + transcripts)
            got = res or []
        except Exception as e:  # noqa: BLE001
            logger.info("scout source %s failed: %s", name, e)
            got = []
        by_source[name] = len(got)
        candidates.extend(got)

    staged = 0
    generated = 0
    for cand in candidates[: max_ideas * 2]:
        if staged >= max_ideas:
            break
        if _seen(cand.get("url", "")):
            continue
        idea = await generate_idea(cand["title"], cand["text"], cand["source_type"], cand.get("url", ""))
        generated += 1
        if idea is None:
            continue
        _save_idea(idea)
        staged += 1
    return {"generated": generated, "staged": staged, "by_source": by_source,
            "candidates": len(candidates)}


def accept_idea(idea_id: str, tags: Optional[List[str]] = None) -> Dict[str, Any]:
    """Promote a staged idea's validated spec into the arsenal. Raises on bad state."""
    idea = get_idea(idea_id)
    if idea is None:
        raise KeyError("idea not found")
    if not idea.get("spec_valid") or not idea.get("spec"):
        raise ValueError("idea has no valid spec to accept")

    import indicator_arsenal as arsenal
    extra_tags = tags or ([idea["technique"]] if idea.get("technique") else [])
    item = arsenal.save_item(idea["spec"], source=f"scout:{idea.get('source_type', '?')}", tags=extra_tags)
    _update_idea(idea_id, {"accepted": True, "arsenal_id": item["id"]})
    return item
