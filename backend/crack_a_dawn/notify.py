"""Crack-a-Dawn — Telegram delivery to @Siiigggbot (the signals bot). Lean push."""
from __future__ import annotations

import logging
import os
from typing import Optional

import requests

logger = logging.getLogger("crack_a_dawn.notify")
TG = "https://api.telegram.org"
_LIMIT = 3800  # under Telegram's 4096 to leave room


def send(text: str) -> bool:
    token = os.getenv("SIGNAL_BOT_TOKEN")
    chat = os.getenv("SIGNAL_BOT_CHAT_ID")
    if not token or not chat:
        logger.warning("SIGNAL_BOT_TOKEN/CHAT_ID not set — skipping Telegram")
        return False
    body = text if len(text) <= _LIMIT else text[:_LIMIT] + "\n…(full brief on the dashboard)"
    try:
        r = requests.post(
            f"{TG}/bot{token}/sendMessage",
            json={"chat_id": chat, "text": body, "parse_mode": "Markdown",
                  "disable_web_page_preview": True},
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
