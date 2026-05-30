"""
Deep Dive Routes - Enhanced ticker analysis with AI thesis generation
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import yfinance as yf
from fastapi import APIRouter, HTTPException

# Import Charlotte modules with fallback
try:
    from hermes.charlotte.signal_enhancer import EnhancedSignalEngine
    from hermes.charlotte.projections import DCFProjector
    from hermes.charlotte.narrative_projector import NarrativeProjector
except ImportError:
    from charlotte.signal_enhancer import EnhancedSignalEngine
    from charlotte.projections import DCFProjector
    from charlotte.narrative_projector import NarrativeProjector

try:
    from hermes.charlotte.ollama_deep_analyzer import OllamaPrimaryClient
except ImportError:
    from charlotte.ollama_deep_analyzer import OllamaPrimaryClient

# Wiring/IO layer for the additive analytics (signals, insider, regime) blocks.
# Optional: if it cannot be imported the deep-dive simply omits those blocks.
try:
    import scan_analytics as _scan_analytics  # type: ignore
except Exception:  # noqa: BLE001
    try:
        from backend import scan_analytics as _scan_analytics  # type: ignore
    except Exception:  # noqa: BLE001
        _scan_analytics = None

# Cache for deep dive results
_deep_dive_cache: Dict[str, tuple] = {}  # {symbol: (timestamp, result)}

# Singleton client for Ollama
_ollama_client: Optional[OllamaPrimaryClient] = None

logger = logging.getLogger(__name__)

# Create router
deep_dive_router = APIRouter(prefix="/api/research/deep", tags=["deep-dive"])

THESIS_MODEL = "qwen3-coder:480b-cloud"


def _get_ollama_client() -> OllamaPrimaryClient:
    """Get or create singleton Ollama client."""
    global _ollama_client
    if _ollama_client is None:
        try:
            import os
            api_key = (
                os.environ.get("OLLAMA_API_KEY")
                or os.environ.get("OLLAMA_CLOUD_API_KEY")
                or ""
            )
            base_url = os.environ.get("OLLAMA_BASE_URL", "https://ollama.com/v1")
            _ollama_client = OllamaPrimaryClient(
                api_key=api_key,
                base_url=base_url,
            )
        except Exception as e:
            logger.warning(f"Failed to initialize Ollama client: {e}")
            _ollama_client = None
    return _ollama_client


def _get_news(symbol: str) -> List[Dict[str, Any]]:
    """Get recent news for symbol (best-effort)."""
    try:
        from hermes.charlotte.news_fetcher import fetch_symbol_news
        return fetch_symbol_news(symbol, limit=5)
    except Exception:
        return []  # News is optional


def _generate_thesis_fallback(scores: Dict[str, float], projection: Dict[str, Any]) -> str:
    """Generate fallback thesis when LLM fails."""
    tech_score = scores.get('technical', 0)
    proj_score = scores.get('projection', 0)
    narr_score = scores.get('narrative', 0)

    # Determine verdict based on scores
    if tech_score >= 8.0 and proj_score >= 7.0:
        verdict = "Strong Buy"
    elif tech_score >= 6.5 and proj_score >= 5.5:
        verdict = "Buy"
    elif tech_score >= 4.5:
        verdict = "Hold"
    elif tech_score >= 3.0:
        verdict = "Trim"
    else:
        verdict = "Avoid"

    # Create markdown thesis
    return f"""## Verdict
{verdict} with moderate confidence

## What the data says
- Technical indicators show {'strong' if tech_score >= 7 else 'moderate' if tech_score >= 5 else 'weak'} momentum
- DCF projections {'favorable' if proj_score >= 7 else 'neutral' if proj_score >= 5 else 'concerning'}
- Narrative potential rated as {'high' if narr_score >= 7 else 'moderate' if narr_score >= 5 else 'low'}

## Bull case
Price could reach ${projection.get('bull', 'N/A')} if fundamentals accelerate.

## Bear case
Downside risk to ${projection.get('bear', 'N/A')} if conditions deteriorate.

## What would change my mind
A significant change in technical momentum or fundamental outlook.
"""


def _verdict_from_score(combined_score: float) -> str:
    if combined_score >= 8.0:
        return "Strong Buy"
    elif combined_score >= 6.5:
        return "Buy"
    elif combined_score >= 4.5:
        return "Hold"
    elif combined_score >= 3.0:
        return "Trim"
    else:
        return "Avoid"


def _generate_thesis(symbol: str, quote: Optional[Dict[str, Any]],
                     scores: Dict[str, float], breakdown: Dict[str, Any],
                     projection: Dict[str, Any], narrative: Dict[str, Any],
                     news: List[Dict[str, Any]]) -> tuple:
    """Run LLM thesis call; returns (markdown, warnings_list)."""
    warnings: List[str] = []
    try:
        structured_data = {
            "symbol": symbol,
            "current_price": quote.get("price") if quote else "N/A",
            "scores": scores,
            "dcf": {
                "bear": projection.get("bear"),
                "base": projection.get("base"),
                "bull": projection.get("bull"),
            },
            "narrative": {
                "x_bagger_base": narrative.get("x_bagger_base"),
                "x_bagger_bull": narrative.get("x_bagger_bull"),
                "tam_billions": narrative.get("tam_billions_future"),
            },
            "technical_reasons": [breakdown.get("technical", {}).get("reason", "N/A")],
            "news_headlines": [item.get("headline", "N/A") for item in news[:3]],
        }
        prompt = f"""You are a sober quantitative analyst. Write a 250-400 word investment thesis in
markdown for {symbol} based ONLY on the data below. Structure:

## Verdict
one-line call (Strong Buy / Buy / Hold / Trim / Avoid) with confidence number.

## What the data says
3-5 bullet points integrating technical, DCF, narrative signals.

## Bull case
2-3 sentences.

## Bear case
2-3 sentences.

## What would change my mind
1 sentence on the invalidation trigger.

Be specific. Cite numbers. No hedging filler like "investors should consider...".
No disclaimers. No price predictions outside the bear/base/bull range provided.

DATA:
{structured_data}"""
        client = _get_ollama_client()
        if client:
            response = client.call_model(THESIS_MODEL, prompt, timeout=60)
            if response and response.strip():
                return response.strip(), warnings
            logger.warning(f"LLM returned empty response for {symbol}")
            warnings.append("LLM returned empty response, using fallback thesis")
        else:
            logger.warning("Ollama client not available")
            warnings.append("LLM unavailable, using fallback thesis")
    except Exception as e:
        logger.error(f"Failed to generate thesis for {symbol}: {e}")
        warnings.append("Failed to generate AI thesis, using fallback")
    return _generate_thesis_fallback(scores, projection), warnings


async def _run_deep_dive(
    symbol: str, *, include_thesis: bool = True, include_analytics: bool = True
) -> Dict[str, Any]:
    """
    Run the deep-dive analyzer for a single symbol.

    Composes signal engine, DCF projection, narrative projection, news, and
    (optionally) the qwen3-coder LLM thesis. Safe to call from bulk scans by
    setting include_thesis=False.
    """
    symbol = symbol.upper()
    now = datetime.now()
    warnings: List[str] = []
    result: Dict[str, Any] = {
        "symbol": symbol,
        "timestamp": now.isoformat(),
    }

    # Quote
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        quote = {
            "price": info.last_price,
            "change_pct": ((info.last_price - info.previous_close) / info.previous_close) * 100,
            "volume": info.last_volume,
        }
    except Exception as e:
        logger.warning(f"Failed to get quote for {symbol}: {e}")
        quote = None
        warnings.append("Failed to fetch current quote")
    result["quote"] = quote

    # Signal analysis
    try:
        engine = EnhancedSignalEngine(symbol)
        signal_analysis = engine.combine_signals()
        breakdown = signal_analysis.get("breakdown", {})
        scores = {
            "technical": breakdown.get("technical", {}).get("score", 0),
            "projection": breakdown.get("projection", {}).get("score", 0),
            "narrative": breakdown.get("narrative", {}).get("score", 0),
            "combined": signal_analysis.get("confidence", 0),
        }
        combined_score = scores["combined"]
        verdict = _verdict_from_score(combined_score)
        result.update({
            "composite_score": combined_score,
            "verdict": verdict,
            "scores": scores,
            "breakdown": breakdown,
        })
    except Exception as e:
        logger.error(f"Failed to get signal analysis for {symbol}: {e}")
        warnings.append("Failed to generate signal analysis")
        breakdown = {}
        scores = {"technical": 0, "projection": 0, "narrative": 0, "combined": 0}
        result.update({
            "composite_score": 0,
            "verdict": "N/A",
            "scores": scores,
            "breakdown": breakdown,
        })

    # DCF projection
    try:
        projector = DCFProjector(symbol)
        projection = projector.calculate_price_targets()
        result["projection"] = projection
    except Exception as e:
        logger.error(f"Failed to get DCF projections for {symbol}: {e}")
        warnings.append("Failed to generate DCF projections")
        result["projection"] = {}

    # Narrative
    try:
        narrative_proj = NarrativeProjector(symbol)
        narrative = narrative_proj.get_summary()
        result["narrative"] = narrative
    except Exception as e:
        logger.error(f"Failed to get narrative projection for {symbol}: {e}")
        warnings.append("Failed to generate narrative projection")
        result["narrative"] = {}

    # News
    try:
        result["news"] = _get_news(symbol)
    except Exception as e:
        logger.error(f"Failed to get news for {symbol}: {e}")
        result["news"] = []

    # Thesis (optional)
    if include_thesis:
        thesis_markdown, thesis_warnings = _generate_thesis(
            symbol, quote, scores, breakdown,
            result.get("projection", {}) or {},
            result.get("narrative", {}) or {},
            result.get("news", []) or [],
        )
        warnings.extend(thesis_warnings)
        result.update({
            "thesis_markdown": thesis_markdown,
            "thesis_model": THESIS_MODEL,
        })

    # Additive analytics blocks (signals / insider / regime). The single-symbol
    # deep-dive fetches its own SPY series for relative-strength + regime (the
    # per-process cache makes this cheap). Fully wrapped — never breaks the dive.
    if include_analytics and _scan_analytics is not None:
        try:
            _spy_close = None
            _spy_returns = None
            try:
                _spy_df = _scan_analytics._completed(
                    _scan_analytics._fetch_ohlcv(_scan_analytics._BENCHMARK)
                )
                if _spy_df is not None:
                    _spy_adj = _scan_analytics._adj_close(_spy_df)
                    if _spy_adj is not None:
                        _spy_close = _spy_adj
                        _spy_returns = _scan_analytics._daily_returns(_spy_adj)
            except Exception as se:  # noqa: BLE001
                logger.debug(f"deep_dive[{symbol}]: SPY series fetch failed: {se}")

            cur_price = (quote or {}).get("price") if quote else None
            an = _scan_analytics.per_ticker_analytics(
                symbol,
                avg_cost=None,          # deep-dive has no position context
                current_price=cur_price,
                account_value=None,
                entry_date=None,
                spy_returns=_spy_returns,
                spy_close=_spy_close,
            )
            if an:
                result["analytics"] = an

            reg = await _scan_analytics.regime_block(_spy_close)
            if reg is not None:
                result["regime"] = reg
        except Exception as ae:  # noqa: BLE001
            logger.warning(f"deep_dive[{symbol}]: additive analytics failed: {ae}")

    result["warnings"] = warnings
    return result


@deep_dive_router.get("/{symbol}")
async def get_deep_dive(symbol: str) -> Dict[str, Any]:
    """Get deep dive analysis for a symbol."""
    symbol = symbol.upper()
    now = datetime.now()

    # Check cache
    if symbol in _deep_dive_cache:
        timestamp, cached_result = _deep_dive_cache[symbol]
        if now - timestamp < timedelta(seconds=60):
            logger.info(f"Cache hit for {symbol}")
            return cached_result

    try:
        result = await _run_deep_dive(symbol, include_thesis=True)
        _deep_dive_cache[symbol] = (now, result)
        return result
    except Exception as e:
        logger.error(f"Deep dive failed for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
