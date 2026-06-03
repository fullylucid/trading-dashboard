"""Category-aware distillation. Finance videos -> tickers/calls/conviction/targets;
ai-coding / science / engineering / general -> insights/tools/claims/takeaways.
Runs on the free Opus worker pool via agent_bridge.run_agent_job."""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger("fintube.distill")

MAX_CHARS = 48000  # keep the transcript well within context; trim very long videos

_FINANCE = (
    "You are extracting structured investment signal from a financial YouTuber's video. "
    "Return ONLY JSON, no prose, no markdown fences:\n"
    '{"category":"finance","summary":"<2-sentence gist>",'
    '"creator_view":"bullish|bearish|neutral|mixed",'
    '"philosophy":"<1 sentence on their style/worldview shown here>",'
    '"macro_thesis":"<1 sentence, or empty>",'
    '"calls":[{"ticker":"<SYMBOL or null>","action":"buy|sell|hold|watch",'
    '"conviction":"low|medium|high","price_target":<number or null>,'
    '"horizon":"<e.g. days|weeks|1-3yr>","thesis":"<short why>"}]}\n'
    "Only include calls actually argued in the video. If none, calls:[]. Use real tickers; "
    "never invent a target that wasn't stated (use null)."
)

_GENERAL = (
    "You are distilling a {cat} YouTube video into structured, reusable knowledge. "
    "Return ONLY JSON, no prose, no markdown fences:\n"
    '{{"category":"{cat}","summary":"<2-3 sentence gist>",'
    '"key_insights":["<the non-obvious takeaways, 3-6 bullets>"],'
    '"tools_mentioned":["<libraries/products/papers/techniques named>"],'
    '"claims":[{{"claim":"<a specific claim made>","stance":"asserted|speculative|cited"}}],'
    '"recommendations":["<concrete advice/actions the creator gives>"]}}'
)

# Discovery mode: the scout surfaced this video from an open YouTube search, so it has NOT
# been vetted by a human. On top of the normal distillation we ask the model to (a) score
# how relevant + worth-the-time it is for Schyler specifically, and (b) write a one-line
# pitch. The relevance score gates what gets pushed to Telegram, so be a tough grader —
# clickbait, rehashed news, beginner fluff, and thinly-veiled ads should score low.
_DISCOVERY = (
    "You are Tradeskeebot's research scout. This {cat} YouTube video was found by an "
    "automated search and is UNVETTED. Schyler is a swing/day trader and AI/agent builder; "
    "he values, in order: novel trading strategies (indicator algorithms, trading-bot "
    "architectures, quant methods), concrete AI-agent engineering enhancements, and new "
    "open-source repos/tools/feature ideas worth adopting. He does NOT want clickbait, "
    "rehashed market news, get-rich-quick pitches, beginner 101 content, or ads.\n"
    "Return ONLY JSON, no prose, no markdown fences:\n"
    '{{"category":"{cat}","summary":"<2-3 sentence gist>",'
    '"pitch":"<ONE punchy line on why this is worth Schyler\'s time — name the specific '
    'idea/tool/technique, not generic praise>",'
    '"key_insights":["<3-5 concrete, non-obvious takeaways or steps>"],'
    '"tools_mentioned":["<libraries/repos/products/papers/techniques named>"],'
    '"relevance":<float 0.0-1.0, how well it fits Schyler\'s interests above>,'
    '"worth_sharing":<true|false — true ONLY if genuinely novel/actionable for him>}}\n'
    "Score honestly: most search results are mediocre. Reserve relevance>0.8 for content "
    "that teaches a specific, actionable strategy/architecture/tool he'd plausibly use."
)


def build_prompt(transcript: str, title: str, channel: str, category: str,
                 mode: str = "default") -> str:
    t = transcript[:MAX_CHARS]
    if mode == "discovery":
        head = _DISCOVERY.format(cat=category)
    elif category == "finance":
        head = _FINANCE
    else:
        head = _GENERAL.format(cat=category)
    return (f"{head}\n\nVIDEO: {title}\nCHANNEL: {channel}\nCATEGORY: {category}\n\n"
            f"TRANSCRIPT:\n{t}")


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    s = text.strip()
    s = re.sub(r"^```(?:json)?|```$", "", s, flags=re.MULTILINE).strip()
    a, b = s.find("{"), s.rfind("}")
    if a == -1 or b == -1:
        return None
    try:
        return json.loads(s[a:b + 1])
    except Exception:  # noqa: BLE001
        return None


async def distill(transcript: str, title: str, channel: str, category: str,
                  timeout: int = 180, mode: str = "default") -> Optional[Dict[str, Any]]:
    try:
        from agent_bridge import run_agent_job  # lazy: avoid import coupling
    except Exception:  # noqa: BLE001
        logger.warning("agent bridge unavailable for distill")
        return None
    prompt = build_prompt(transcript, title, channel, category, mode=mode)
    text = await run_agent_job(prompt, kind="data", timeout=timeout)
    if not text:
        return None
    parsed = _extract_json(text)
    if parsed is None:
        logger.warning("distill returned non-JSON for %s", title[:60])
    return parsed
