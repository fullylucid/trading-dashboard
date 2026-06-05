"""Vision tier — two interchangeable backends, both turning pixels into TEXT for the
text-only Opus pool to reason over ("cheap screen, then Claude").

  • POOL (default): the Opus worker pool *is* Claude Code, which can ``Read`` image files
    natively. So the backend writes the image to a shared dir and enqueues a normal text
    job — "Read the image at <path> and …". Free under the Max subscription, no extra
    service, reuses ``agent_bridge.run_agent_job``. Requires a dir shared between the
    backend container and the host where the workers run (``FINTUBE_VISION_DIR`` /
    ``FINTUBE_VISION_DIR_HOST``).
  • VLM endpoint (optional override): any OpenAI-compatible vision ``/chat/completions``
    (SmolVLM via llama.cpp, moondream via Ollama, …) set with ``FINTUBE_VLM_URL`` — cheaper/
    faster per call. When set it takes precedence over the pool.

If neither is available the layer degrades to ``None`` and callers fall back, exactly like
distill when the bus is down. No torch in the backend image either way.
"""
from __future__ import annotations

import base64
import logging
import os
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger("fintube.vision")

# --- optional external VLM endpoint ---------------------------------------------------
VLM_URL = os.getenv("FINTUBE_VLM_URL", "").rstrip("/")
VLM_MODEL = os.getenv("FINTUBE_VLM_MODEL", "smolvlm")
VLM_TIMEOUT = float(os.getenv("FINTUBE_VLM_TIMEOUT", "60"))

# --- Claude worker-pool backend (default) ---------------------------------------------
POOL_VISION = os.getenv("FINTUBE_VISION_POOL", "1").lower() not in ("0", "false", "no", "")
VISION_DIR = os.getenv("FINTUBE_VISION_DIR", "/vision")          # path the BACKEND writes to
VISION_DIR_HOST = os.getenv("FINTUBE_VISION_DIR_HOST", "")        # same dir as the WORKER sees it
POOL_TIMEOUT = int(os.getenv("FINTUBE_VISION_POOL_TIMEOUT", "180"))

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


# ---------------------------------------------------------------- config / availability
def pool_available() -> bool:
    """Pool vision needs a dir the worker can read (the shared host path)."""
    return POOL_VISION and bool(VISION_DIR_HOST)


def is_configured() -> bool:
    """True when *some* vision backend can run (otherwise the layer is a no-op)."""
    return bool(VLM_URL) or pool_available()


def active_backend() -> Optional[str]:
    if VLM_URL:
        return "vlm"
    if pool_available():
        return "pool"
    return None


def task_instruction(task: str) -> str:
    return _TASKS.get(task, _TASKS[_DEFAULT_TASK])


def to_b64(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("ascii")


def _b64_to_bytes(image_b64: str) -> Optional[bytes]:
    try:
        return base64.b64decode(image_b64)
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- VLM (HTTP) backend
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
    if not isinstance(data, dict):
        return None
    try:
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content")
    except Exception:  # noqa: BLE001
        return None
    text = (text or "").strip()
    return text or None


async def _post_chat(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    import httpx  # lazy: keep the module importable in envs without httpx
    async with httpx.AsyncClient(timeout=VLM_TIMEOUT) as client:
        r = await client.post(f"{VLM_URL}/chat/completions", json=payload)
        r.raise_for_status()
        return r.json()


async def describe_image(image_b64: str, task: str = _DEFAULT_TASK, *,
                         mime: str = "image/jpeg", max_tokens: int = 256,
                         instruction: Optional[str] = None) -> Optional[str]:
    """VLM-endpoint path: send one image to the external VLM, return its text answer."""
    if not VLM_URL:
        return None
    instr = instruction or task_instruction(task)
    try:
        data = await _post_chat(_payload(image_b64, instr, mime, max_tokens))
    except Exception as e:  # noqa: BLE001
        logger.warning("VLM describe_image failed (%s): %s", task, e)
        return None
    return _parse_response(data)


# ---------------------------------------------------------------- Claude pool backend
def _worker_path(name: str) -> str:
    """Path to the image as the Claude worker (on the host) sees it."""
    return os.path.join(VISION_DIR_HOST or VISION_DIR, name)


def _pool_prompt(instruction: str, worker_path: str) -> str:
    return (f"{instruction}\n\nThe image is a local file at this path:\n{worker_path}\n"
            f"Use your Read tool to open that image, then answer. "
            f"Reply with ONLY the answer text — no preamble, no markdown.")


async def describe_via_pool(image_bytes: bytes, task: str = _DEFAULT_TASK, *,
                            instruction: Optional[str] = None, ext: str = "jpg",
                            timeout: Optional[int] = None) -> Optional[str]:
    """Pool path: drop the image in the shared dir, ask a Claude worker to Read it."""
    if not pool_available() or not image_bytes:
        return None
    instr = instruction or task_instruction(task)
    name = f"{uuid.uuid4().hex}.{ext}"
    container_path = os.path.join(VISION_DIR, name)
    try:
        os.makedirs(VISION_DIR, exist_ok=True)
        with open(container_path, "wb") as f:
            f.write(image_bytes)
    except Exception as e:  # noqa: BLE001
        logger.warning("pool vision: could not stage image: %s", e)
        return None
    try:
        from agent_bridge import run_agent_job  # lazy: avoid import coupling
    except Exception:  # noqa: BLE001
        logger.warning("pool vision: agent bridge unavailable")
        _safe_unlink(container_path)
        return None
    try:
        text = await run_agent_job(_pool_prompt(instr, _worker_path(name)),
                                   kind="data", timeout=timeout or POOL_TIMEOUT)
    finally:
        _safe_unlink(container_path)
    return (text or "").strip() or None


def _safe_unlink(path: str) -> None:
    try:
        os.remove(path)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- unified entry
async def analyze(*, image_bytes: Optional[bytes] = None, image_b64: Optional[str] = None,
                  task: str = _DEFAULT_TASK, mime: str = "image/jpeg",
                  instruction: Optional[str] = None, max_tokens: int = 256) -> Optional[str]:
    """Route an image to the active vision backend (VLM endpoint if set, else Claude pool)."""
    if VLM_URL:
        b64 = image_b64 if image_b64 is not None else (to_b64(image_bytes) if image_bytes else None)
        if not b64:
            return None
        return await describe_image(b64, task, mime=mime, max_tokens=max_tokens, instruction=instruction)
    raw = image_bytes if image_bytes is not None else (_b64_to_bytes(image_b64) if image_b64 else None)
    if raw is None:
        return None
    return await describe_via_pool(raw, task, instruction=instruction)


# ---------------------------------------------------------------- shared parsers
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
