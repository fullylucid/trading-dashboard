"""
Hermes TUI Portal Screenshot Handler
=====================================

CLI/TUI command for fetching dashboard screenshots from the running
backend's `/api/portal/screenshot` endpoint and rendering them inline
in the terminal where possible.

Usage
-----
As a module (slash command target):
    python -m hermes.portal.screenshot_handler [--url URL] [--target URL]
                                                [--out PATH] [--no-render]

As a library:
    from hermes.portal.screenshot_handler import fetch_screenshot, render
    path = fetch_screenshot("http://localhost:8000")
    render(path)

Rendering strategy (best-available wins):
    1. Kitty graphics protocol (TERM contains "kitty" or KITTY_WINDOW_ID set)
    2. iTerm2 inline images protocol (TERM_PROGRAM == "iTerm.app")
    3. Textual + rich-pixels (if installed) — colored unicode-block render
    4. Fallback: save to disk and print the absolute path

The backend endpoint returns:
    {
      "image_base64": "<base64 PNG>",
      "captured_at": "<iso ts>",
      "url": "<target>",
      "width": 1920,
      "height": 1080
    }
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Optional


DEFAULT_BACKEND = os.getenv("HERMES_BACKEND_URL", "http://localhost:8000")
DEFAULT_OUTPUT_DIR = Path(os.getenv("HERMES_PORTAL_CACHE", "/tmp/hermes-portal"))


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_screenshot(
    backend_url: str = DEFAULT_BACKEND,
    target_url: Optional[str] = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    timeout: float = 45.0,
) -> Path:
    """Call /api/portal/screenshot, decode base64 PNG, write to disk.

    Returns the absolute Path to the saved PNG.
    Raises RuntimeError with a useful message on HTTP / decode failure.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    endpoint = f"{backend_url.rstrip('/')}/api/portal/screenshot"
    if target_url:
        from urllib.parse import urlencode
        endpoint = f"{endpoint}?{urlencode({'url': target_url})}"

    req = urllib.request.Request(endpoint, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HTTP {e.code} from {endpoint}: {body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Could not reach {endpoint}: {e.reason}. "
            f"Is the backend running? (cd backend && python main.py)"
        ) from e

    b64 = (
        payload.get("screenshot")
        or payload.get("image_base64")
        or payload.get("image")
        or payload.get("data")
    )
    if not b64:
        raise RuntimeError(
            f"Endpoint returned no image data. Keys: {list(payload)}"
        )

    # Strip optional data-URI prefix ("data:image/png;base64,...")
    if isinstance(b64, str) and b64.startswith("data:"):
        b64 = b64.split(",", 1)[1] if "," in b64 else b64

    try:
        png_bytes = base64.b64decode(b64)
    except Exception as e:
        raise RuntimeError(f"Failed to decode base64 PNG: {e}") from e

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = output_dir / f"portal_{ts}.png"
    out_path.write_bytes(png_bytes)
    return out_path


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def _is_kitty() -> bool:
    return (
        "kitty" in os.environ.get("TERM", "").lower()
        or "KITTY_WINDOW_ID" in os.environ
    )


def _is_iterm() -> bool:
    return os.environ.get("TERM_PROGRAM", "") == "iTerm.app"


def _render_kitty(path: Path) -> bool:
    """Render PNG via the Kitty graphics protocol (no external deps).

    https://sw.kovidgoyal.net/kitty/graphics-protocol/
    """
    try:
        data = path.read_bytes()
        b64 = base64.standard_b64encode(data).decode("ascii")
        # a=T : transmit + display; f=100 : PNG; chunked at 4096 bytes
        chunk_size = 4096
        chunks = [b64[i : i + chunk_size] for i in range(0, len(b64), chunk_size)]
        for idx, chunk in enumerate(chunks):
            last = idx == len(chunks) - 1
            payload = (
                f"\033_Ga=T,f=100,m={0 if last else 1};{chunk}\033\\"
            )
            sys.stdout.write(payload)
        sys.stdout.write("\n")
        sys.stdout.flush()
        return True
    except Exception:
        return False


def _render_iterm(path: Path) -> bool:
    """Render PNG via iTerm2 inline images protocol."""
    try:
        data = path.read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        sys.stdout.write(
            f"\033]1337;File=inline=1;size={len(data)}:{b64}\a\n"
        )
        sys.stdout.flush()
        return True
    except Exception:
        return False


def _render_rich_pixels(path: Path) -> bool:
    """Try rich-pixels + textual for an inline blocky preview."""
    try:
        from rich.console import Console  # type: ignore
        from rich_pixels import Pixels  # type: ignore
    except ImportError:
        return False
    try:
        console = Console()
        pixels = Pixels.from_image_path(str(path))
        console.print(pixels)
        return True
    except Exception:
        return False


def render(path: Path) -> str:
    """Try the best terminal renderer for the current environment.

    Returns the name of the renderer used. Always succeeds — falls back
    to printing the absolute path if no inline renderer works.
    """
    if _is_kitty() and _render_kitty(path):
        return "kitty"
    if _is_iterm() and _render_iterm(path):
        return "iterm2"
    if _render_rich_pixels(path):
        return "rich-pixels"
    print(f"[portal] saved screenshot to {path}")
    print(f"[portal] (no inline image renderer available — open the file directly)")
    return "fallback-path"


# ---------------------------------------------------------------------------
# CLI / slash-command entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hermes-portal",
        description="Fetch and render a Hermes dashboard screenshot in the terminal.",
    )
    parser.add_argument(
        "--url", default=DEFAULT_BACKEND,
        help=f"Backend URL (default: {DEFAULT_BACKEND})",
    )
    parser.add_argument(
        "--target", default=None,
        help="Override the dashboard URL the backend screenshots "
             "(default: backend's PORTAL_TARGET_URL).",
    )
    parser.add_argument(
        "--out", default=None,
        help="Directory to save the PNG (default: $HERMES_PORTAL_CACHE or /tmp/hermes-portal)",
    )
    parser.add_argument(
        "--no-render", action="store_true",
        help="Just save and print the path; skip inline rendering.",
    )
    args = parser.parse_args(argv)

    out_dir = Path(args.out) if args.out else DEFAULT_OUTPUT_DIR
    try:
        path = fetch_screenshot(
            backend_url=args.url,
            target_url=args.target,
            output_dir=out_dir,
        )
    except RuntimeError as e:
        print(f"[portal] ERROR: {e}", file=sys.stderr)
        return 1

    print(f"[portal] captured: {path}  ({path.stat().st_size:,} bytes)")
    if not args.no_render:
        renderer = render(path)
        print(f"[portal] renderer: {renderer}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
