"""
Research Agent - free local Opus 4.8 (via the agent-bridge worker) summarizes
earnings reports and SEC filings and identifies trading alpha signals.

Formerly Kimi-K via Ollama Cloud; rerouted to the Max-subscription local worker
so it's free at the margin and no longer depends on a paid hosted endpoint.
Method signatures + return shapes are unchanged so research_routes.py is
untouched. Every method degrades gracefully (returns an {"error": ...} dict)
when the agent-bridge is unavailable.
"""

import re
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any

# Free local Opus via the agent-bridge worker pool.
try:
    import agent_bridge  # type: ignore
except Exception:  # noqa: BLE001
    try:
        from backend import agent_bridge  # type: ignore
    except Exception:  # noqa: BLE001
        agent_bridge = None  # type: ignore

logger = logging.getLogger(__name__)

MODEL_LABEL = "opus-4.8 (agent-bridge)"

_FENCE_RE = re.compile(r"```(?:json)?|```")


def _parse_json(text: str, fallback_key: str) -> Dict[str, Any]:
    """Best-effort parse of a model response into a dict.

    Claude may wrap JSON in ```json fences or add a sentence around it; strip
    fences, then fall back to the first {...} span, then to a raw passthrough.
    """
    if not text:
        return {fallback_key: ""}
    cleaned = _FENCE_RE.sub("", text).strip()
    try:
        return json.loads(cleaned)
    except Exception:  # noqa: BLE001
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except Exception:  # noqa: BLE001
                pass
        return {fallback_key: text.strip()}


async def _opus(prompt: str) -> Optional[str]:
    """Run a prompt on the free local Opus worker; None if the bus is down."""
    if agent_bridge is None:
        logger.warning("research_agent: agent_bridge unavailable")
        return None
    return await agent_bridge.run_agent_job(prompt, kind="data")


_JSON_INSTRUCTION = "\n\nReturn ONLY valid JSON — no prose, no markdown fences."


class ResearchAgent:
    """Opus-powered research summarization for trading alpha generation."""

    def __init__(self, *args, **kwargs):
        # Legacy Ollama config args are accepted and ignored; analysis now runs
        # on free local Opus via the agent-bridge.
        self.model = MODEL_LABEL

    async def initialize(self):
        """No-op — no HTTP session to manage (work runs on the worker)."""
        return

    async def close(self):
        """No-op — nothing to tear down."""
        return

    async def clear_cache(self):
        """No-op — this agent holds no local cache (called from main shutdown)."""
        return

    async def summarize_earnings_report(self, symbol: str, report_text: str,
                                        company_name: str = "") -> Dict[str, Any]:
        """Summarize an earnings report into structured insights."""
        prompt = f"""Analyze this {symbol} earnings report and provide:

1. **Key Metrics**: EPS, Revenue, Margin trends
2. **Growth Drivers**: What's driving revenue/earnings growth
3. **Headwinds**: Key challenges or risks mentioned
4. **Guidance**: Forward guidance and expectations
5. **Competitive Position**: Market share, competitive advantages
6. **Capital Allocation**: Dividends, buybacks, CapEx
7. **Investment Thesis**: Bull case, bear case, valuation

Report:
{report_text[:10000]}{_JSON_INSTRUCTION}"""
        try:
            resp = await _opus(prompt)
            if not resp:
                return {"error": "AI analysis unavailable", "symbol": symbol}
            return {
                "symbol": symbol,
                "timestamp": datetime.now().isoformat(),
                "model": self.model,
                "summary": _parse_json(resp, "raw_summary"),
                "confidence": 0.85,
            }
        except Exception as e:  # noqa: BLE001
            logger.error(f"Research agent error: {e}")
            return {"error": str(e)}

    async def analyze_sec_filing(self, symbol: str, filing_type: str,
                                 filing_text: str) -> Dict[str, Any]:
        """Analyze a SEC filing (10-K, 10-Q, 8-K, Form 4)."""
        prompt = f"""Analyze this {filing_type} filing for {symbol}.

Extract:
1. **Material Changes**: What changed materially since last filing
2. **Risk Factors**: New or escalating risks
3. **Financial Health**: Debt levels, liquidity, working capital
4. **Business Trends**: Revenue mix, segment performance
5. **Insider Actions**: Buying/selling by executives (if Form 4)
6. **Guidance Changes**: Any updates to forward guidance
7. **Industry Headwinds**: External challenges mentioned

Filing:
{filing_text[:15000]}

Use specific numbers/dates where available.{_JSON_INSTRUCTION}"""
        try:
            resp = await _opus(prompt)
            if not resp:
                return {"error": "AI analysis unavailable", "symbol": symbol}
            return {
                "symbol": symbol,
                "filing_type": filing_type,
                "timestamp": datetime.now().isoformat(),
                "analysis": _parse_json(resp, "raw_analysis"),
                "model": self.model,
            }
        except Exception as e:  # noqa: BLE001
            logger.error(f"SEC filing analysis error: {e}")
            return {"error": str(e)}

    async def identify_alpha_signals(self, symbol: str,
                                     research_data: Dict[str, Any]) -> Dict[str, Any]:
        """Identify trading alpha signals from assembled research data."""
        prompt = f"""Given this research data for {symbol}, identify alpha signals.

Data:
{json.dumps(research_data, indent=2)[:8000]}

Identify:
1. **Surprise Signals**: Anything surprising or unexpected?
2. **Catalyst Events**: What could move the stock?
3. **Valuation Signal**: Is stock cheap or expensive relative to growth?
4. **Risk/Reward**: What's the edge here?
5. **Conviction Level**: How confident are you in the signal?
6. **Time Horizon**: Days, weeks, or months to play out?

Provide specific, actionable signals.{_JSON_INSTRUCTION}"""
        try:
            resp = await _opus(prompt)
            if not resp:
                return {"error": "AI analysis unavailable", "symbol": symbol}
            return {
                "symbol": symbol,
                "timestamp": datetime.now().isoformat(),
                "alpha_signals": _parse_json(resp, "raw_signals"),
                "model": self.model,
            }
        except Exception as e:  # noqa: BLE001
            logger.error(f"Alpha signal identification error: {e}")
            return {"error": str(e)}


# Singleton instance
_research_agent: Optional[ResearchAgent] = None


async def get_research_agent() -> ResearchAgent:
    """Get or create research agent instance."""
    global _research_agent
    if not _research_agent:
        _research_agent = ResearchAgent()
        await _research_agent.initialize()
    return _research_agent


async def close_research_agent():
    """Close research agent."""
    global _research_agent
    if _research_agent:
        await _research_agent.close()
        _research_agent = None
