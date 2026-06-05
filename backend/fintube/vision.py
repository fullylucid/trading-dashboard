"""Vision tier — SmolVLM (or any OpenAI-compatible vision endpoint) as cheap local "eyes".

The Opus worker pool is TEXT-ONLY, so FinTube's vision strategy is HYBRID: a small local VLM
turns pixels into TEXT — read an on-screen title, describe a thumbnail, caption a keyframe,
judge whether a frame is information-rich — and the existing text Opus pool reasons over that
text. A future top tier can escalate the few best frames to Claude vision ("SmolVLM then Claude").

Configure with ``FINTUBE_VLM_URL`` pointing at an OpenAI-compatible base (e.g.
``http://vlm:8080/v1``). If unset/unreachable the whole vision layer degrades to ``None`` and
callers fall back — exactly like distill when the bus is down. This keeps the backend image
lean (no torch); the model runs in a separate sidecar service.
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("fintube.vision")

VLM_URL = os.getenv("FINTUBE_VLM_URL", "").rstrip("/")
VLM_MODEL = os.getenv("FINTUBE_VLM_MODEL", "smolvlm")
VLM_TIMEOUT = float(os.getenv("FINTUBE_VLM_TIMEOUT", "60"))

# task -> instruction. Outputs are kept terse and parse-friendly (plain text, no markdown).
_TASKS = {
    "read_title": (
        "This is a photo or screenshot of a screen showing a YouTube video. Read and return "
        "ONLY the video's title text exactly as shown — no quotes, no commentary. If the "
        "channel name is also visible, append ' - <channel>'. If no title is visible, return "
        "the most prominent on-screen text."
    ),
    "describe_thumbnail": (
        "Describe this YouTube thumbnail in one line: the main subject, any large on-screen "
        "text, and the visual style. Be concrete and brief."
    ),
    "caption_frame": (
        "Caption this video frame in one line: what is shown (UI, chart, code, slide, talking "
        "head, diagram) and any key on-screen text. Be concrete and brief."
    ),
    "is_rich": (
        "Does this video frame show information-rich visual material worth studying — a UI / "
        "dashboard, a data visualization / chart, code, or an explanatory diagram (as opposed "
        "to a plain talking head, intro card, or ad)? Start your answer with strictly 'yes' or "
        "'no', then a short reason."
    ),
}
_DEFAULT_TASK = "caption_frame"


def is_configured() -> bool:
    """True when a VLM endpoint is wired up (otherwise the vision layer is a no-op)."""
    return bool(VLM_URL)


def task_instruction(task: str) -> str:
    return _TASKS.get(task, _TASKS[_DEFAULT_TASK])


def to_b64(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("ascii")


def _payload(image_b64: str, instruction: str, mime: str, max_tokens: int) -> Dict[str, Any]:
    """OpenAI-compatible multimodal chat request (text + inline data-URL image)."""
    return {
        "model": VLM_MODEL,
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": instruction},
                {"type": "image_url",
                 "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
            ],
        }],
    }


def _parse_response(data: Optional[Dict[str, Any]]) -> Optional[str]:
    """Pull the assistant text out of an OpenAI-compatible chat completion."""
    if not isinstance(data, dict):
        return None
    try:
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content")
    except Exception:  # noqa: BLE001
        return None
    text = (text or "").strip()
    return text or None


def parse_yes_no(text: Optional[str]) -> Optional[bool]:
    """Interpret an `is_rich`-style answer. None when indeterminate."""
    if not text:
        return None
    head = text.strip().lower()[:4]
    if head.startswith("yes"):
        return True
    if head.startswith("no"):
        return False
    return None


async def _post_chat(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    import httpx  # lazy: keep the module importable in envs without httpx
    async with httpx.AsyncClient(timeout=VLM_TIMEOUT) as client:
        r = await client.post(f"{VLM_URL}/chat/completions", json=payload)
        r.raise_for_status()
        return r.json()


async def describe_image(image_b64: str, task: str = _DEFAULT_TASK, *,
                         mime: str = "image/jpeg", max_tokens: int = 256,
                         instruction: Optional[str] = None) -> Optional[str]:
    """Send one image to the local VLM and return its text answer, or None if the vision
    layer is unconfigured / unreachable / empty."""
    if not VLM_URL:
        return None
    instr = instruction or task_instruction(task)
    try:
        data = await _post_chat(_payload(image_b64, instr, mime, max_tokens))
    except Exception as e:  # noqa: BLE001
        logger.warning("VLM describe_image failed (%s): %s", task, e)
        return None
    return _parse_response(data)
