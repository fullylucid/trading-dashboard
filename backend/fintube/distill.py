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


def build_prompt(transcript: str, title: str, channel: str, category: str) -> str:
    t = transcript[:MAX_CHARS]
    head = _FINANCE if category == "finance" else _GENERAL.format(cat=category)
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
                  timeout: int = 180) -> Optional[Dict[str, Any]]:
    try:
        from agent_bridge import run_agent_job  # lazy: avoid import coupling
    except Exception:  # noqa: BLE001
        logger.warning("agent bridge unavailable for distill")
        return None
    prompt = build_prompt(transcript, title, channel, category)
    text = await run_agent_job(prompt, kind="data", timeout=timeout)
    if not text:
        return None
    parsed = _extract_json(text)
    if parsed is None:
        logger.warning("distill returned non-JSON for %s", title[:60])
    return parsed
