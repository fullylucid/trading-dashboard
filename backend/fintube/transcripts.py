"""Transcript extraction via yt-dlp auto-captions (no ffmpeg / no JS runtime needed).

We let yt-dlp write the VTT auto-subs and parse them ourselves, deduping YouTube's
rolling-caption repetition. This is more robust than youtube-transcript-api, which
YouTube now gates ("VideoUnplayable"). Whisper fallback is intentionally deferred.
"""
from __future__ import annotations

import glob
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Optional

logger = logging.getLogger("fintube.transcripts")

_TAG = re.compile(r"<[^>]+>")
_TS = re.compile(r"\d{2}:\d{2}:\d{2}\.\d{3}\s*-->")
_CUE_START = re.compile(r"(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s*-->")


def _hms_to_s(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def _parse_vtt_timed(path: str) -> list[tuple[float, str]]:
    """Like _parse_vtt but keeps each cue's start time: [(start_seconds, text), ...]."""
    out: list[tuple[float, str]] = []
    cur_t = 0.0
    prev = ""
    for raw in open(path, encoding="utf-8", errors="ignore"):
        ln = raw.strip()
        if "-->" in ln:
            m = _CUE_START.search(ln)
            if m:
                cur_t = _hms_to_s(*m.groups())
            continue
        if not ln or ln == "WEBVTT" or ln.startswith(("Kind:", "Language:", "NOTE")):
            continue
        ln = _TAG.sub("", ln).strip()
        if not ln or ln.startswith("align:") or ln.startswith("position:"):
            continue
        if ln != prev:
            out.append((cur_t, ln))
            prev = ln
    return out


def timed_text(segments: list[tuple[float, str]], every: int = 30) -> str:
    """Flatten timed segments into prose with periodic [mm:ss] markers, so a distiller can
    cite approximate timestamps for key moments."""
    out: list[str] = []
    next_mark = 0.0
    for t, text in segments:
        while t >= next_mark:
            out.append(f"[{int(next_mark // 60):02d}:{int(next_mark % 60):02d}]")
            next_mark += every
        out.append(text)
    return " ".join(out)


def _parse_vtt(path: str) -> str:
    out: list[str] = []
    prev = ""
    for raw in open(path, encoding="utf-8", errors="ignore"):
        ln = raw.strip()
        if not ln or ln == "WEBVTT" or "-->" in ln or ln.startswith(("Kind:", "Language:", "NOTE")):
            continue
        ln = _TAG.sub("", ln).strip()
        # cue-position artifacts like "align:start position:0%"
        if not ln or ln.startswith("align:") or ln.startswith("position:"):
            continue
        if ln != prev:
            out.append(ln)
            prev = ln
    return " ".join(out)


def fetch_transcript(video_url: str, timeout: int = 90, timed: bool = False) -> Optional[str]:
    """Pull English auto/manual captions for a video. Returns cleaned text or None.
    timed=True interleaves [mm:ss] markers so the distiller can cite key-moment timestamps."""
    tmp = tempfile.mkdtemp(prefix="fintube_")
    try:
        cmd = [
            sys.executable, "-m", "yt_dlp",
            "--skip-download", "--write-auto-subs", "--write-subs",
            "--sub-langs", "en.*", "--sub-format", "vtt",
            "--no-warnings", "--quiet",
            "-o", os.path.join(tmp, "%(id)s.%(ext)s"),
            video_url,
        ]
        subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        vtts = sorted(glob.glob(os.path.join(tmp, "*.vtt")))
        # prefer manual en over en-orig (auto) if both present
        manual = [v for v in vtts if ".en.vtt" in v and "-orig" not in v]
        chosen = manual[0] if manual else (vtts[0] if vtts else None)
        if not chosen:
            logger.info("no captions for %s", video_url)
            return None
        text = timed_text(_parse_vtt_timed(chosen)) if timed else _parse_vtt(chosen)
        return text or None
    except subprocess.TimeoutExpired:
        logger.warning("transcript timeout for %s", video_url)
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning("transcript error for %s: %s", video_url, e)
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
