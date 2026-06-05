"""Visual keyframe pipeline — "watch" a video for its visuals, not just its words.

Flagship of the multimodal arc. For a given video:
  download (capped res + duration) -> ffmpeg scene-detect keyframes -> for each frame ask
  the vision tier to gate+caption it (study_frame: SKIP a talking head / keep & describe a
  UI / chart / code / diagram) -> persist the kept frames + captions -> serve them back.

So a builder can mine a tutorial for dashboard / visualization / UI ideas without watching it.

HEAVY and GATED: on-demand only (never auto), capped frames, capped duration, low res, temp
video deleted after extraction. Each kept frame costs one vision call (Claude turn on the
pool); frames are analyzed concurrently across the worker pool. Kept frames live under
FINTUBE_VISUALS_DIR (the persistent /data volume); metadata in Redis.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import glob
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional

from . import store, vision

logger = logging.getLogger("fintube.visuals")

VISUALS_DIR = os.getenv("FINTUBE_VISUALS_DIR", "/data/fintube_visuals")
KEY = "fintube:visuals:{vid}"
CACHE_TTL = 7 * 24 * 3600

MAX_HEIGHT = int(os.getenv("FINTUBE_VISUALS_MAX_HEIGHT", "720"))
MAX_DURATION_S = int(os.getenv("FINTUBE_VISUALS_MAX_DURATION", "1800"))   # only first 30 min
EXTRACT_CAP = int(os.getenv("FINTUBE_VISUALS_EXTRACT_CAP", "24"))         # frames pulled from ffmpeg
# duration-adaptive uniform sampling: ~EXTRACT_CAP evenly-spaced frames, interval clamped.
# (Scene-threshold selection was tried and dropped — ffmpeg's scene score is too content-
# dependent to be reliable; uniform coverage + the study_frame gate is predictable.)
MIN_INTERVAL_S = int(os.getenv("FINTUBE_VISUALS_MIN_INTERVAL", "20"))
MAX_INTERVAL_S = int(os.getenv("FINTUBE_VISUALS_MAX_INTERVAL", "120"))
DEFAULT_INTERVAL_S = 45                                                   # used when duration unknown
ANALYZE_CAP = int(os.getenv("FINTUBE_VISUALS_ANALYZE_CAP", "16"))         # frames sent to the VLM
KEEP_CAP = int(os.getenv("FINTUBE_VISUALS_KEEP_CAP", "12"))               # rich frames retained
ANALYZE_CONCURRENCY = int(os.getenv("FINTUBE_VISUALS_CONCURRENCY", "5"))  # ~= worker count
DL_TIMEOUT = int(os.getenv("FINTUBE_VISUALS_DL_TIMEOUT", "300"))
FF_TIMEOUT = int(os.getenv("FINTUBE_VISUALS_FF_TIMEOUT", "180"))

_running: set[str] = set()


# ---------------------------------------------------------------- redis store
def get_result(video_id: str) -> Optional[Dict[str, Any]]:
    c = store.r()
    if c is None:
        return None
    raw = c.get(KEY.format(vid=video_id))
    return json.loads(raw) if raw else None


def _save_result(doc: Dict[str, Any]) -> None:
    c = store.r()
    if c is not None:
        c.set(KEY.format(vid=doc["video_id"]), json.dumps(doc), ex=CACHE_TTL)


def is_running(video_id: str) -> bool:
    return video_id in _running


# ---------------------------------------------------------------- download + extract
def _download_cmd(url: str, out_tmpl: str) -> List[str]:
    """yt-dlp: a single capped-resolution file, only the first MAX_DURATION_S (needs ffmpeg)."""
    return [
        sys.executable, "-m", "yt_dlp", "--no-warnings", "--quiet", "--no-playlist",
        "-f", f"best[height<={MAX_HEIGHT}][ext=mp4]/best[height<={MAX_HEIGHT}]/best",
        "--download-sections", f"*0-{MAX_DURATION_S}", "--force-keyframes-at-cuts",
        "-o", out_tmpl, url,
    ]


def _probe_cmd(video_path: str) -> List[str]:
    return ["ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nk=1:nw=1", video_path]


def _interval_for(duration_s: Optional[float]) -> int:
    """Pick a sampling interval so ~EXTRACT_CAP frames span the video, clamped to a sane range."""
    if not duration_s or duration_s <= 0:
        return DEFAULT_INTERVAL_S
    return int(max(MIN_INTERVAL_S, min(MAX_INTERVAL_S, duration_s / EXTRACT_CAP)))


def _sample_cmd(video_path: str, pattern: str, interval_s: int) -> List[str]:
    """ffmpeg: one JPEG every `interval_s` seconds, capped to EXTRACT_CAP."""
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", video_path,
        "-vf", f"fps=1/{interval_s}", "-vsync", "vfr",
        "-frames:v", str(EXTRACT_CAP), "-q:v", "3", pattern,
    ]


def _download_video(url: str, work_dir: str) -> Optional[str]:
    out = os.path.join(work_dir, "video.%(ext)s")
    try:
        subprocess.run(_download_cmd(url, out), capture_output=True, text=True, timeout=DL_TIMEOUT)
    except Exception as e:  # noqa: BLE001
        logger.warning("visuals: download failed for %s: %s", url, e)
        return None
    files = [f for f in glob.glob(os.path.join(work_dir, "video.*")) if not f.endswith(".part")]
    return files[0] if files else None


def _probe_duration(video_path: str) -> Optional[float]:
    try:
        out = subprocess.run(_probe_cmd(video_path), capture_output=True, text=True, timeout=30)
        return float(out.stdout.strip())
    except Exception:  # noqa: BLE001
        return None


def _extract_frames(video_path: str, frames_dir: str) -> List[str]:
    """Duration-adaptive uniform sampling — even coverage regardless of content. Sorted paths."""
    interval = _interval_for(_probe_duration(video_path))
    pattern = os.path.join(frames_dir, "f_%04d.jpg")
    try:
        subprocess.run(_sample_cmd(video_path, pattern, interval),
                       capture_output=True, text=True, timeout=FF_TIMEOUT)
    except Exception as e:  # noqa: BLE001
        logger.warning("visuals: ffmpeg sample failed: %s", e)
    return sorted(glob.glob(os.path.join(frames_dir, "f_*.jpg")))


def _safe_unlink(path: str) -> None:
    try:
        os.remove(path)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- analysis
def keep_caption(text: Optional[str]) -> Optional[str]:
    """Decide whether a study_frame answer means keep (returns the caption) or drop (None)."""
    if not text:
        return None
    t = text.strip()
    if not t or t.upper().startswith(vision.SKIP_TOKEN):
        return None
    return t


async def _analyze_frame(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as f:
            data = f.read()
    except Exception:  # noqa: BLE001
        return None
    answer = await vision.analyze(image_bytes=data, task="study_frame", max_tokens=160)
    return keep_caption(answer)


# ---------------------------------------------------------------- orchestration
async def run_visuals(video_id: str, url: str, title: str = "") -> Dict[str, Any]:
    """Full pipeline for one video. Persists + returns the result doc."""
    if not vision.is_configured():
        doc = _doc(video_id, url, title, status="error", error="vision not configured")
        _save_result(doc)
        return doc
    _running.add(video_id)
    _save_result(_doc(video_id, url, title, status="running"))
    tmp = tempfile.mkdtemp(prefix="fintube_vis_")
    frames_tmp = os.path.join(tmp, "frames")
    os.makedirs(frames_tmp, exist_ok=True)
    try:
        video_path = await asyncio.to_thread(_download_video, url, tmp)
        if not video_path:
            doc = _doc(video_id, url, title, status="error", error="could not download video")
            _save_result(doc)
            return doc

        frames = await asyncio.to_thread(_extract_frames, video_path, frames_tmp)
        _safe_unlink(video_path)  # video no longer needed once frames are out
        if not frames:
            doc = _doc(video_id, url, title, status="error", error="no frames extracted")
            _save_result(doc)
            return doc

        to_analyze = frames[:ANALYZE_CAP]
        dropped_unanalyzed = len(frames) - len(to_analyze)

        sem = asyncio.Semaphore(ANALYZE_CONCURRENCY)

        async def _gated(p: str):
            async with sem:
                return p, await _analyze_frame(p)

        results = await asyncio.gather(*[_gated(p) for p in to_analyze])
        kept = [(p, cap) for p, cap in results if cap][:KEEP_CAP]

        dest = os.path.join(VISUALS_DIR, video_id)
        shutil.rmtree(dest, ignore_errors=True)
        os.makedirs(dest, exist_ok=True)
        out_frames: List[Dict[str, Any]] = []
        for idx, (src, caption) in enumerate(kept):
            fname = f"{idx}.jpg"
            try:
                shutil.copyfile(src, os.path.join(dest, fname))
            except Exception:  # noqa: BLE001
                continue
            out_frames.append({"idx": idx, "file": fname, "caption": caption})

        doc = _doc(video_id, url, title, status="done", frames=out_frames,
                   extracted=len(frames), analyzed=len(to_analyze), kept=len(out_frames),
                   dropped_unanalyzed=dropped_unanalyzed)
        _save_result(doc)
        logger.info("visuals %s: extracted %d, analyzed %d, kept %d (dropped %d unanalyzed)",
                    video_id, len(frames), len(to_analyze), len(out_frames), dropped_unanalyzed)
        return doc
    except Exception as e:  # noqa: BLE001
        logger.exception("visuals %s failed", video_id)
        doc = _doc(video_id, url, title, status="error", error=str(e)[:200])
        _save_result(doc)
        return doc
    finally:
        _running.discard(video_id)
        shutil.rmtree(tmp, ignore_errors=True)


def _doc(video_id: str, url: str, title: str, *, status: str,
         frames: Optional[List[Dict[str, Any]]] = None, error: str = "",
         **extra: Any) -> Dict[str, Any]:
    doc = {
        "video_id": video_id, "url": url, "title": title, "status": status,
        "frames": frames or [], "error": error,
        "updated": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    doc.update(extra)
    return doc


def frame_path(video_id: str, idx: int) -> str:
    return os.path.join(VISUALS_DIR, video_id, f"{idx}.jpg")
