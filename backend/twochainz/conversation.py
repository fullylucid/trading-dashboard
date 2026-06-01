"""2Chainz — rolling conversation memory (host file; capped)."""
from __future__ import annotations

import json
import os
from typing import Dict, List

STORE = os.getenv(
    "TWOCHAINZ_THREAD", os.path.expanduser("~/.config/trading-dashboard/twochainz/thread.json")
)
MAX_TURNS = int(os.getenv("TWOCHAINZ_MAX_TURNS", "30"))


def load() -> List[Dict[str, str]]:
    try:
        with open(STORE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def append(role: str, content: str) -> None:
    turns = load()
    turns.append({"role": role, "content": content})
    turns = turns[-MAX_TURNS:]
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    tmp = STORE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(turns, f, indent=2)
    os.replace(tmp, STORE)


def as_transcript() -> str:
    turns = load()
    if not turns:
        return "(new conversation)"
    names = {"user": "Schyler", "assistant": "2Chainz"}
    return "\n".join(f"{names.get(t['role'], t['role'])}: {t['content']}" for t in turns)
