"""
2Chainz — Telegram listener. Long-polls @Siiigggbot for Schyler's messages,
runs the strategist, replies in-channel. Always-on (systemd, Restart=always).

    python -m twochainz.listen

Allowlisted to Schyler's chat only. The bot is otherwise outbound (Crack-a-Dawn
briefs) — getUpdates + sendMessage coexist fine as long as no webhook is set.
"""
from __future__ import annotations

import logging
import os
import time

import requests

from . import agent, conversation

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("twochainz.listen")

TG = "https://api.telegram.org"
TOKEN = os.getenv("SIGNAL_BOT_TOKEN", "")
ALLOW_CHAT = str(os.getenv("SIGNAL_BOT_CHAT_ID", "")).strip()
OFFSET_FILE = os.path.expanduser("~/.config/trading-dashboard/twochainz/offset.txt")


def _read_offset() -> int:
    try:
        return int(open(OFFSET_FILE).read().strip())
    except Exception:  # noqa: BLE001
        return 0


def _write_offset(o: int) -> None:
    os.makedirs(os.path.dirname(OFFSET_FILE), exist_ok=True)
    with open(OFFSET_FILE, "w") as f:
        f.write(str(o))


def _send(text: str) -> None:
    try:
        requests.post(f"{TG}/bot{TOKEN}/sendMessage",
                      json={"chat_id": ALLOW_CHAT, "text": text, "parse_mode": "Markdown",
                            "disable_web_page_preview": True}, timeout=20)
    except Exception as e:  # noqa: BLE001
        logger.error("send failed: %s", e)


def _typing() -> None:
    try:
        requests.post(f"{TG}/bot{TOKEN}/sendChatAction",
                      json={"chat_id": ALLOW_CHAT, "action": "typing"}, timeout=10)
    except Exception:  # noqa: BLE001
        pass


def handle(text: str) -> None:
    logger.info("strategist turn: %r", text[:80])
    conversation.append("user", text)
    _typing()
    reply = agent.respond(text)
    if not reply:
        reply = "⚠️ 2Chainz hit a snag generating that — try again in a moment."
    else:
        conversation.append("assistant", reply)
    _send(reply)


def main() -> int:
    if not TOKEN or not ALLOW_CHAT:
        logger.error("SIGNAL_BOT_TOKEN / SIGNAL_BOT_CHAT_ID not set")
        return 1
    # Ensure no webhook is hijacking updates (idempotent).
    try:
        requests.get(f"{TG}/bot{TOKEN}/deleteWebhook", timeout=10)
    except Exception:  # noqa: BLE001
        pass
    offset = _read_offset()
    logger.info("2Chainz listening (offset=%s, chat=%s)", offset, ALLOW_CHAT)
    while True:
        try:
            r = requests.get(f"{TG}/bot{TOKEN}/getUpdates",
                             params={"offset": offset, "timeout": 30}, timeout=40)
            updates = r.json().get("result", []) if r.status_code == 200 else []
        except Exception as e:  # noqa: BLE001
            logger.warning("getUpdates error: %s", e)
            time.sleep(5)
            continue
        for u in updates:
            offset = u["update_id"] + 1
            _write_offset(offset)
            msg = u.get("message") or u.get("edited_message") or {}
            chat_id = str((msg.get("chat") or {}).get("id", ""))
            text = (msg.get("text") or "").strip()
            if chat_id != ALLOW_CHAT or not text:
                continue
            if text.startswith("/"):           # ignore bot commands for now
                continue
            try:
                handle(text)
            except Exception as e:  # noqa: BLE001
                logger.error("handle failed: %s", e)
                _send("⚠️ 2Chainz error handling that message.")


if __name__ == "__main__":
    raise SystemExit(main())
