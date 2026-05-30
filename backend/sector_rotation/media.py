"""Media / narrative intelligence — news volume + sentiment BY SECTOR.

Phase 2.5 sector-rotation "media/narrative" leg. This module measures, for each
of the 11 SPDR sectors, **how loud** the news flow is (volume) and **how the
tone leans** (sentiment), so the rotation model can tag a sector as having a
narrative *tailwind*, *headwind*, or *neutral* backdrop.

Layering (mirrors ``backend/analytics/`` and ``sector_rotation.sectors``)
-------------------------------------------------------------------------
- **PURE helpers** (stdlib/numpy only, no network, no disk, deterministic,
  fully unit-tested with crafted headline dicts):
  :func:`classify_headline`, :func:`classify_headlines`,
  :func:`aggregate_sector_sentiment`, :func:`sentiment_trend`,
  :func:`bucket_sector_narrative`, :func:`narrative_signal`,
  :func:`score_sectors`. These take already-fetched *headline dicts* IN and
  return numbers / dicts OUT.
- **IO function**: :func:`fetch_sector_news` is the **only** network-touching
  function. It hits the Finnhub ``company-news`` endpoint (``FINNHUB_API_KEY``),
  sends a UA, respects a small rate-limit gap, times out, and returns ``[]`` on
  *any* failure (it never raises). The dicts it yields are exactly the shape the
  PURE helpers consume.

Headline-dict schema (the contract between IO and PURE layers)::

    {
        "headline":  "Chip stocks rally as demand outlook strengthens",
        "summary":   "...",          # optional, used as a tone fallback
        "datetime":  1748505600,     # unix epoch seconds (UTC), best-effort
        "source":    "Reuters",      # optional
        "url":       "https://...",  # optional
        "symbol":    "XLK",          # the sector ETF the news was fetched for
    }

Sentiment method
----------------
The research spec recommends **FinBERT** (a BERT fine-tuned on financial text)
and offers a **simple positive/negative keyword rule** as the Phase-1 fallback.
FinBERT needs ``torch``+``transformers`` (heavy; GPU-ish; not always installed),
so the **PURE, default, always-available** classifier here is a curated
financial **lexicon**: each headline is scored by net (positive - negative)
keyword hits and bucketed POSITIVE / NEGATIVE / NEUTRAL. An *optional* FinBERT
classifier (:func:`make_finbert_classifier`) can be passed into the aggregation
functions; if ``transformers`` is missing or the model fails to load it degrades
to ``None`` and callers fall back to the lexicon. The aggregation math is
identical regardless of which per-headline classifier produced the labels.

Aggregation (per the research spec, section 3.1)
------------------------------------------------
For each sector::

    Sentiment_Score = (Count_Positive - Count_Negative) / Total_Headlines   in [-1, 1]
    News_Volume     = Count(headlines in the window)
    Sentiment_Trend = Sentiment_Score[today] - Sentiment_Score[yesterday]

Bucketing::

    High Volume + Positive  -> "Tailwind"   (narrative tail wind)
    High Volume + Negative  -> "Headwind"   (narrative head wind)
    otherwise / Low Volume  -> "Neutral"

"High Volume" is **relative**: a sector is high-volume if its headline count is
at/above the cross-sector volume threshold (default: the median count). This
keeps the bucket meaningful regardless of the absolute news pace on a given day.

Narrative signal (research weighting, lines ~726-731 of the spec)::

    sentiment_signal    = Sentiment_Score * 50           # -50 .. +50
    news_volume_signal  = (volume_rank - 0.5) * 30       # -15 .. +15
    narrative_signal    = sentiment_signal * 0.7 + news_volume_signal * 0.3

Caveats (carried from the spec, surfaced so callers don't over-trust this leg)
------------------------------------------------------------------------------
- News sentiment is frequently a **lagging** indicator (headlines follow price).
- Headlines are often **stock-specific**, not sector-wide (XLK news is mostly
  about its mega-cap holdings); treat as *narrative confirmation*, not primary.
- The lexicon is shallow vs. FinBERT — it cannot read sarcasm/negation well.

Sources / references
--------------------
- Finnhub company-news:  https://finnhub.io/docs/api/company-news
- Finnhub news-sentiment: https://finnhub.io/docs/api/news-sentiment
- FinBERT (ProsusAI):    https://github.com/ProsusAI/finBERT
- Sector-rotation research spec, section 3 (Media / Narrative).
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from sector_rotation.sectors import SECTOR_ETF_SYMBOLS, etf_to_sector

logger = logging.getLogger(__name__)

# A per-headline classifier maps headline text -> one of these labels.
POSITIVE = "positive"
NEGATIVE = "negative"
NEUTRAL = "neutral"

#: Type of a pluggable per-headline sentiment classifier: text -> label.
Classifier = Callable[[str], str]


# ---------------------------------------------------------------------------
# PURE: lexicon sentiment classifier
# ---------------------------------------------------------------------------

# Curated financial-tone lexicon. Tokens are matched as whole words (lowercased,
# punctuation-stripped). Multi-word phrases are matched as substrings. Kept
# deliberately finance-flavoured (the spec's seed list, broadened) rather than a
# general-purpose affect lexicon, since the domain is market headlines.
_POSITIVE_TERMS: frozenset = frozenset(
    {
        "beat", "beats", "strong", "strength", "growth", "grow", "grows",
        "outperform", "outperforms", "gain", "gains", "rally", "rallies",
        "surge", "surges", "soar", "soars", "jump", "jumps", "rise", "rises",
        "upgrade", "upgrades", "upgraded", "bullish", "record", "boost",
        "boosts", "boosted", "profit", "profits", "rebound", "rebounds",
        "tailwind", "tailwinds", "expand", "expands", "expansion", "optimism",
        "optimistic", "win", "wins", "approval", "approved", "raise", "raises",
        "raised", "top", "tops", "topped", "demand", "momentum", "accelerate",
        "accelerates", "breakout", "high", "highs", "robust", "upside",
    }
)

_NEGATIVE_TERMS: frozenset = frozenset(
    {
        "miss", "misses", "missed", "weak", "weakness", "decline", "declines",
        "declined", "underperform", "underperforms", "loss", "losses", "drop",
        "drops", "dropped", "plunge", "plunges", "slump", "slumps", "fall",
        "falls", "fell", "downgrade", "downgrades", "downgraded", "bearish",
        "warn", "warns", "warning", "cut", "cuts", "slash", "slashes",
        "layoff", "layoffs", "lawsuit", "probe", "recall", "recalls", "fraud",
        "headwind", "headwinds", "fears", "fear", "concern", "concerns",
        "slowdown", "slow", "slows", "tumble", "tumbles", "sink", "sinks",
        "crash", "crashes", "selloff", "sell-off", "downturn", "risk", "risks",
        "pressure", "pressures", "low", "lows", "default", "bankruptcy",
        "investigation", "shortfall", "disappoint", "disappoints",
        "disappointing", "delay", "delays", "delayed", "downside", "crisis",
    }
)

# Multi-word phrases worth catching even though their tokens may be neutral.
_POSITIVE_PHRASES: tuple = ("better than expected", "raises guidance", "all-time high")
_NEGATIVE_PHRASES: tuple = (
    "worse than expected",
    "cuts guidance",
    "profit warning",
    "below expectations",
)

# Punctuation stripped from token edges before lexicon lookup.
_PUNCT = ".,;:!?\"'()[]{}<>«»…“”‘’`-—–/\\|*"


def _tokenize(text: str) -> List[str]:
    """PURE: lowercase, split on whitespace, strip edge punctuation. Never raises."""
    if not text:
        return []
    out: List[str] = []
    for raw in str(text).lower().split():
        tok = raw.strip(_PUNCT)
        if tok:
            out.append(tok)
    return out


def score_text(text: Optional[str]) -> int:
    """PURE: net tone of ``text`` = (#positive hits) - (#negative hits).

    Whole-word matches against the lexicon plus a few multi-word phrase matches.
    Positive return = net-positive tone, negative = net-negative, 0 = neutral.

    >>> score_text("Chip demand strong, shares surge to record high") > 0
    True
    >>> score_text("Bank misses estimates, shares plunge on weak guidance") < 0
    True
    >>> score_text("Sector holds flat in quiet trading")
    0
    """
    if not text:
        return 0
    low = str(text).lower()
    score = 0
    for phrase in _POSITIVE_PHRASES:
        if phrase in low:
            score += 1
    for phrase in _NEGATIVE_PHRASES:
        if phrase in low:
            score -= 1
    for tok in _tokenize(low):
        if tok in _POSITIVE_TERMS:
            score += 1
        elif tok in _NEGATIVE_TERMS:
            score -= 1
    return score


def lexicon_classifier(text: str) -> str:
    """PURE: classify one headline as POSITIVE / NEGATIVE / NEUTRAL via the lexicon.

    This is the default per-headline :data:`Classifier`. Ties (net score 0) and
    empty text map to NEUTRAL.

    >>> lexicon_classifier("Nvidia beats, raises guidance")
    'positive'
    >>> lexicon_classifier("Banks tumble on default fears")
    'negative'
    >>> lexicon_classifier("Utilities trade sideways")
    'neutral'
    """
    s = score_text(text)
    if s > 0:
        return POSITIVE
    if s < 0:
        return NEGATIVE
    return NEUTRAL


def _headline_text(headline: Dict[str, Any]) -> str:
    """PURE: pull the classifiable text from a headline dict (headline + summary)."""
    if not isinstance(headline, dict):
        return ""
    parts = [str(headline.get("headline") or ""), str(headline.get("summary") or "")]
    return " ".join(p for p in parts if p).strip()


def classify_headline(headline: Dict[str, Any], classifier: Optional[Classifier] = None) -> str:
    """PURE: label a single headline dict. Uses ``classifier`` or the lexicon.

    ``classifier`` is any text->label callable (e.g. a FinBERT closure). If it
    raises or returns an unrecognized label, this degrades to NEUTRAL so a flaky
    model can never break aggregation.
    """
    text = _headline_text(headline)
    clf = classifier or lexicon_classifier
    try:
        label = clf(text)
    except Exception as e:  # noqa: BLE001 - tolerant by contract
        logger.debug("classify_headline: classifier raised, using neutral: %s", e)
        return NEUTRAL
    if label in (POSITIVE, NEGATIVE, NEUTRAL):
        return label
    return NEUTRAL


def classify_headlines(
    headlines: Iterable[Dict[str, Any]], classifier: Optional[Classifier] = None
) -> List[str]:
    """PURE: classify a batch of headline dicts, preserving order."""
    return [classify_headline(h, classifier) for h in (headlines or [])]


# ---------------------------------------------------------------------------
# PURE: per-sector aggregation
# ---------------------------------------------------------------------------


def aggregate_sector_sentiment(
    headlines: Sequence[Dict[str, Any]], classifier: Optional[Classifier] = None
) -> Dict[str, Any]:
    """PURE: aggregate one sector's headlines into volume + sentiment stats.

    Implements the spec's per-sector aggregation::

        Sentiment_Score = (Count_Positive - Count_Negative) / Total_Headlines

    Parameters
    ----------
    headlines : sequence of headline dict
        Already-fetched headlines for ONE sector (see module schema).
    classifier : callable, optional
        Per-headline text->label classifier; defaults to the lexicon.

    Returns
    -------
    dict
        ``{"news_volume", "positive", "negative", "neutral", "sentiment_score"}``.
        With no headlines: volume 0 and ``sentiment_score`` 0.0 (neutral),
        never a division-by-zero.

    Examples
    --------
    >>> hs = [{"headline": "chips surge to record high"},
    ...       {"headline": "demand strong, sales beat"},
    ...       {"headline": "regulatory probe weighs on outlook"}]
    >>> a = aggregate_sector_sentiment(hs)
    >>> a["news_volume"], a["positive"], a["negative"]
    (3, 2, 1)
    >>> round(a["sentiment_score"], 4)
    0.3333
    """
    pos = neg = neu = 0
    for label in classify_headlines(headlines, classifier):
        if label == POSITIVE:
            pos += 1
        elif label == NEGATIVE:
            neg += 1
        else:
            neu += 1
    total = pos + neg + neu
    score = (pos - neg) / total if total else 0.0
    return {
        "news_volume": total,
        "positive": pos,
        "negative": neg,
        "neutral": neu,
        "sentiment_score": float(score),
    }


def sentiment_trend(today_score: float, yesterday_score: Optional[float]) -> Optional[float]:
    """PURE: Sentiment_Trend = today - yesterday, or ``None`` if no prior reading.

    >>> round(sentiment_trend(0.4, 0.1), 4)
    0.3
    >>> sentiment_trend(0.4, None) is None
    True
    """
    if yesterday_score is None:
        return None
    return float(today_score) - float(yesterday_score)


# ---------------------------------------------------------------------------
# PURE: cross-sector bucketing + signal
# ---------------------------------------------------------------------------


def _median(values: Sequence[float]) -> float:
    """PURE: median of a non-empty sequence (stdlib; numpy not required here)."""
    s = sorted(values)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2:
        return float(s[mid])
    return (float(s[mid - 1]) + float(s[mid])) / 2.0


def bucket_sector_narrative(
    sentiment_score: float,
    news_volume: int,
    volume_threshold: float,
    *,
    sentiment_band: float = 0.1,
) -> str:
    """PURE: bucket one sector into ``"Tailwind"`` / ``"Headwind"`` / ``"Neutral"``.

    Per the spec: a sector needs **high (relative) volume** AND a non-flat tone
    to earn a directional narrative label; otherwise it is Neutral.

    Parameters
    ----------
    sentiment_score : float
        The sector's Sentiment_Score in ``[-1, 1]``.
    news_volume : int
        The sector's headline count in the window.
    volume_threshold : float
        Cross-sector "high volume" cutoff (e.g. the median of all sectors'
        volumes from :func:`score_sectors`). High volume == ``>= threshold``.
    sentiment_band : float, default 0.1
        Dead-zone around zero treated as flat tone (so weak signals stay
        Neutral rather than flipping on a single headline).

    >>> bucket_sector_narrative(0.5, 20, 10.0)
    'Tailwind'
    >>> bucket_sector_narrative(-0.5, 20, 10.0)
    'Headwind'
    >>> bucket_sector_narrative(0.5, 3, 10.0)   # loud tone but thin volume
    'Neutral'
    >>> bucket_sector_narrative(0.02, 20, 10.0) # high volume but flat tone
    'Neutral'
    """
    high_volume = news_volume >= max(1.0, float(volume_threshold))
    if not high_volume:
        return "Neutral"
    if sentiment_score > sentiment_band:
        return "Tailwind"
    if sentiment_score < -sentiment_band:
        return "Headwind"
    return "Neutral"


def narrative_signal(sentiment_score: float, volume_rank: float) -> float:
    """PURE: normalized narrative signal in roughly ``[-50, 50]`` (spec weighting).

    ::

        sentiment_signal   = sentiment_score * 50          # -50 .. +50
        news_volume_signal = (volume_rank - 0.5) * 30      # -15 .. +15
        narrative_signal   = sentiment_signal*0.7 + news_volume_signal*0.3

    Parameters
    ----------
    sentiment_score : float
        Sector Sentiment_Score in ``[-1, 1]``.
    volume_rank : float
        Sector's relative news-volume rank in ``[0, 1]`` (1 == loudest sector).

    >>> round(narrative_signal(1.0, 1.0), 2)
    39.5
    >>> round(narrative_signal(0.0, 0.5), 2)
    0.0
    >>> narrative_signal(-1.0, 0.0) < 0
    True
    """
    sentiment_part = float(sentiment_score) * 50.0
    volume_part = (float(volume_rank) - 0.5) * 30.0
    return sentiment_part * 0.7 + volume_part * 0.3


def _volume_ranks(volumes: Dict[str, int]) -> Dict[str, float]:
    """PURE: map each sector's volume to a [0,1] rank (1 == loudest).

    Uses average-rank for ties so the spread stays symmetric. With a single
    sector (or all-equal volumes) everything ranks 0.5 (neutral)."""
    items = list(volumes.items())
    n = len(items)
    if n == 0:
        return {}
    if n == 1:
        return {items[0][0]: 0.5}
    # average-rank: sort by volume, assign positions, average over ties.
    order = sorted(items, key=lambda kv: kv[1])
    ranks: Dict[str, float] = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and order[j + 1][1] == order[i][1]:
            j += 1
        # positions i..j (0-based) share this volume; average them.
        avg_pos = (i + j) / 2.0
        norm = avg_pos / (n - 1)  # 0..1
        for k in range(i, j + 1):
            ranks[order[k][0]] = norm
        i = j + 1
    return ranks


def score_sectors(
    news_by_sector: Dict[str, Sequence[Dict[str, Any]]],
    *,
    prior_scores: Optional[Dict[str, float]] = None,
    classifier: Optional[Classifier] = None,
    sentiment_band: float = 0.1,
) -> Dict[str, Dict[str, Any]]:
    """PURE: full media/narrative read across sectors from fetched headlines.

    This is the top-level pure entry point. Pass in a ``{sector_or_etf: [headline
    dicts]}`` map (e.g. straight from :func:`fetch_all_sector_news`) and get back
    a per-sector dict of volume, sentiment, trend (if ``prior_scores`` given),
    a relative volume rank, the normalized :func:`narrative_signal`, and the
    :func:`bucket_sector_narrative` label. The "high volume" threshold is the
    cross-sector **median** volume, so buckets are relative to the day's pace.

    Keys of the result are exactly the keys of ``news_by_sector`` (whatever the
    caller used — sector ETF symbols like ``"XLK"`` typically).

    Parameters
    ----------
    news_by_sector : dict
        ``{sector_key: sequence of headline dicts}``.
    prior_scores : dict, optional
        ``{sector_key: yesterday_sentiment_score}`` for trend computation.
    classifier : callable, optional
        Per-headline classifier (defaults to lexicon).
    sentiment_band : float, default 0.1
        Flat-tone dead-zone passed to :func:`bucket_sector_narrative`.

    Returns
    -------
    dict
        ``{sector_key: {sector, news_volume, positive, negative, neutral,
        sentiment_score, sentiment_trend, volume_rank, narrative_signal,
        bucket}}``. Empty input -> ``{}``.
    """
    if not news_by_sector:
        return {}

    prior_scores = prior_scores or {}

    base: Dict[str, Dict[str, Any]] = {}
    for key, headlines in news_by_sector.items():
        base[key] = aggregate_sector_sentiment(headlines, classifier)

    volumes = {k: v["news_volume"] for k, v in base.items()}
    threshold = _median(list(volumes.values()))
    ranks = _volume_ranks(volumes)

    out: Dict[str, Dict[str, Any]] = {}
    for key, agg in base.items():
        sector_name = etf_to_sector(key) or key
        score = agg["sentiment_score"]
        rank = ranks.get(key, 0.5)
        out[key] = {
            "sector": sector_name,
            "news_volume": agg["news_volume"],
            "positive": agg["positive"],
            "negative": agg["negative"],
            "neutral": agg["neutral"],
            "sentiment_score": score,
            "sentiment_trend": sentiment_trend(score, prior_scores.get(key)),
            "volume_rank": rank,
            "narrative_signal": narrative_signal(score, rank),
            "bucket": bucket_sector_narrative(
                score, agg["news_volume"], threshold, sentiment_band=sentiment_band
            ),
        }
    return out


# ---------------------------------------------------------------------------
# OPTIONAL: FinBERT classifier factory (degrades to None if unavailable)
# ---------------------------------------------------------------------------


def make_finbert_classifier(model_name: str = "ProsusAI/finbert") -> Optional[Classifier]:
    """Best-effort: build a FinBERT per-headline :data:`Classifier`, or ``None``.

    The spec recommends FinBERT for higher-quality sentiment. ``torch`` and
    ``transformers`` are heavy/optional, so this loads them locally and returns
    ``None`` if anything is missing or the model fails to load — callers then
    fall back to :func:`lexicon_classifier`. The returned closure itself never
    raises (per-headline errors map to NEUTRAL inside :func:`classify_headline`).

    Not a network IO function in the rate-limited sense, but it *may* download
    model weights on first use; it is intentionally opt-in and never invoked by
    the default pure path.
    """
    try:
        import torch  # noqa: F401  - heavy optional dep
        from transformers import (  # type: ignore
            AutoModelForSequenceClassification,
            AutoTokenizer,
        )
    except Exception as e:  # pragma: no cover - optional dep usually absent
        logger.info("make_finbert_classifier: transformers/torch unavailable: %s", e)
        return None

    try:
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForSequenceClassification.from_pretrained(model_name)
        model.eval()
    except Exception as e:  # pragma: no cover - download/load failure
        logger.warning("make_finbert_classifier: failed to load %s: %s", model_name, e)
        return None

    # ProsusAI/finbert label order is positive/negative/neutral via id2label.
    id2label = {int(k): str(v).lower() for k, v in model.config.id2label.items()}

    def _classify(text: str) -> str:
        if not text:
            return NEUTRAL
        import torch as _torch  # local: keep module import-light

        with _torch.no_grad():
            inputs = tokenizer(
                text, return_tensors="pt", truncation=True, max_length=128
            )
            logits = model(**inputs).logits
            idx = int(_torch.argmax(logits, dim=-1).item())
        label = id2label.get(idx, NEUTRAL)
        if label.startswith("pos"):
            return POSITIVE
        if label.startswith("neg"):
            return NEGATIVE
        return NEUTRAL

    return _classify


# ---------------------------------------------------------------------------
# IO: the ONLY network-touching code in this module
# ---------------------------------------------------------------------------

_FINNHUB_NEWS_URL = "https://finnhub.io/api/v1/company-news"
_REQUEST_TIMEOUT = 8.0
_USER_AGENT = "tradeskeebot-sector-rotation/1.0 (+media sentiment)"
# Conservative spacing between calls to stay well under Finnhub's 60 req/min.
_MIN_REQUEST_GAP_S = 1.1


def fetch_sector_news(symbol: str, lookback_days: int = 1) -> List[Dict[str, Any]]:
    """IO: fetch recent Finnhub company-news for one sector ETF. Never raises.

    The **only** network-touching function here. It queries Finnhub
    ``company-news`` for ``symbol`` over the last ``lookback_days`` days using
    ``FINNHUB_API_KEY`` from the environment, sends a UA, times out, and returns
    a list of *headline dicts* (see module schema) — the exact shape the PURE
    helpers consume.

    Robustness contract: **never raises**. Missing key, missing ``requests``,
    network error, non-200, or malformed payload all degrade to ``[]``.

    Parameters
    ----------
    symbol : str
        Sector ETF symbol (e.g. ``"XLK"``).
    lookback_days : int, default 1
        How many days back to fetch (Finnhub uses ``from``/``to`` dates).

    Returns
    -------
    list of headline dict
        Possibly empty.
    """
    sym = (symbol or "").strip().upper()
    if not sym:
        return []

    api_key = os.environ.get("FINNHUB_API_KEY", "").strip()
    if not api_key:
        logger.debug("fetch_sector_news: FINNHUB_API_KEY not set; returning []")
        return []

    try:
        import requests  # local import: keep pure surface import-light
    except Exception as e:  # pragma: no cover - requests usually present
        logger.debug("fetch_sector_news: requests unavailable: %s", e)
        return []

    try:
        lookback_days = max(1, int(lookback_days))
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=lookback_days)
        resp = requests.get(
            _FINNHUB_NEWS_URL,
            params={
                "symbol": sym,
                "from": start.isoformat(),
                "to": end.isoformat(),
                "token": api_key,
            },
            headers={"User-Agent": _USER_AGENT},
            timeout=_REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.debug("fetch_sector_news: finnhub HTTP %s for %s", resp.status_code, sym)
            return []
        payload = resp.json()
        if not isinstance(payload, list):
            return []
        out: List[Dict[str, Any]] = []
        for art in payload:
            if not isinstance(art, dict):
                continue
            headline = str(art.get("headline") or "").strip()
            if not headline:
                continue
            out.append(
                {
                    "headline": headline,
                    "summary": str(art.get("summary") or "").strip(),
                    "datetime": art.get("datetime"),
                    "source": str(art.get("source") or "").strip(),
                    "url": str(art.get("url") or "").strip(),
                    "symbol": sym,
                }
            )
        return out
    except Exception as e:  # noqa: BLE001 - tolerant by contract
        logger.debug("fetch_sector_news: lookup failed for %s: %s", sym, e)
        return []


def fetch_all_sector_news(
    symbols: Sequence[str] = SECTOR_ETF_SYMBOLS, lookback_days: int = 1
) -> Dict[str, List[Dict[str, Any]]]:
    """IO: fetch news for every sector ETF, throttled. Never raises.

    Loops :func:`fetch_sector_news` over ``symbols`` with a small inter-request
    sleep to stay under Finnhub's free-tier rate limit. Each sector degrades to
    ``[]`` independently, so a single bad symbol never poisons the batch. The
    returned map is the exact input shape for :func:`score_sectors`.

    Returns
    -------
    dict
        ``{symbol: [headline dicts]}`` for every requested symbol.
    """
    out: Dict[str, List[Dict[str, Any]]] = {}
    syms = list(symbols or ())
    for i, sym in enumerate(syms):
        out[str(sym).strip().upper()] = fetch_sector_news(sym, lookback_days=lookback_days)
        if i < len(syms) - 1:
            try:
                time.sleep(_MIN_REQUEST_GAP_S)
            except Exception:  # pragma: no cover - sleep should not fail
                pass
    return out
