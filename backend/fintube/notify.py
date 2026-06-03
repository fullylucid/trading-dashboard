"""FinTube scout — Telegram delivery to the signals bot (@Siiigggbot).

Same bot/creds as crack_a_dawn (SIGNAL_BOT_TOKEN / SIGNAL_BOT_CHAT_ID). The scout pushes
one card per qualifying video: a link + a why-it-matters pitch + a couple of key insights,
so a find is actionable straight from the phone.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

import requests

logger = logging.getLogger("fintube.notify")
TG = "https://api.telegram.org"
_LIMIT = 3800  # under Telegram's 4096

_CAT_EMOJI = {
    "finance": "📈", "ai-coding": "🤖", "engineering": "🛠️",
    "science": "🔬", "general": "📺",
}


def _send_text(text: str) -> bool:
    token = os.getenv("SIGNAL_BOT_TOKEN")
    chat = os.getenv("SIGNAL_BOT_CHAT_ID")
    if not token or not chat:
        logger.warning("SIGNAL_BOT_TOKEN/CHAT_ID not set — skipping Telegram")
        return False
    body = text if len(text) <= _LIMIT else text[:_LIMIT] + "\n…"
    try:
        r = requests.post(
            f"{TG}/bot{token}/sendMessage",
            json={"chat_id": chat, "text": body, "parse_mode": "Markdown",
                  "disable_web_page_preview": False},
            timeout=20,
        )
        if r.status_code != 200:  # Markdown can 400 on stray chars — retry as plain text
            r = requests.post(f"{TG}/bot{token}/sendMessage",
                              json={"chat_id": chat, "text": body}, timeout=20)
        r.raise_for_status()
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("telegram send failed: %s", e)
        return False


def _md_escape(s: str) -> str:
    # Telegram legacy Markdown only specials: _ * ` [
    for ch in ("_", "*", "`", "["):
        s = s.replace(ch, "\\" + ch)
    return s


def format_card(doc: Dict[str, Any]) -> str:
    d = doc.get("distill") or {}
    cat = doc.get("category", "general")
    emoji = _CAT_EMOJI.get(cat, "📺")
    rel = d.get("relevance")
    rel_str = f" · {round(float(rel) * 100)}% match" if isinstance(rel, (int, float)) else ""
    title = _md_escape((doc.get("title") or "")[:160])
    channel = _md_escape((doc.get("channel") or "")[:60])

    lines = [f"{emoji} *New find* ({cat}{rel_str})",
             f"*{title}*",
             f"_{channel}_"]
    pitch = (d.get("pitch") or "").strip()
    if pitch:
        lines.append(f"\n💡 {_md_escape(pitch[:300])}")
    insights = [i for i in (d.get("key_insights") or []) if i][:3]
    for i in insights:
        lines.append(f"• {_md_escape(str(i)[:220])}")
    tools = [t for t in (d.get("tools_mentioned") or []) if t][:6]
    if tools:
        lines.append("\n🔧 " + ", ".join(_md_escape(str(t)) for t in tools))
    lines.append(f"\n{doc.get('url', '')}")
    return "\n".join(lines)


def push_videos(docs: List[Dict[str, Any]]) -> int:
    """Send one card per video. Returns the number successfully delivered."""
    sent = 0
    for doc in docs:
        if _send_text(format_card(doc)):
            sent += 1
    return sent


def push_summary(found: int, pushed: int, scanned: int) -> bool:
    """Optional run footer so a quiet run still confirms the scout ran (silence == failure)."""
    if pushed:
        return True  # cards already speak for the run
    msg = (f"🕷️ FinTube scout: scanned {scanned} fresh video(s), "
           f"{found} cleared relevance — nothing new worth pushing this run.")
    return _send_text(msg)
