"""Ingest helpers — resolve channel/video URLs, list a channel's recent PUBLIC videos.

Channel listing uses the RSS feed (public-only: no members/premieres, no API key,
no quota). yt-dlp is only used to resolve a handle->channel_id and to fetch single
video metadata.
"""
from __future__ import annotations

import logging
import re
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("fintube.ingest")

RSS = "https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
_NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
       "media": "http://search.yahoo.com/mrss/"}


def parse_target(url: str) -> Tuple[str, str]:
    """Classify a pasted string -> ('video', id) | ('channel', handle_or_id) | ('unknown', raw)."""
    u = url.strip()
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})", u)
    if m:
        return "video", m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", u):
        return "video", u
    m = re.search(r"/channel/(UC[A-Za-z0-9_-]+)", u)
    if m:
        return "channel", m.group(1)
    m = re.search(r"@([A-Za-z0-9_.-]+)", u)
    if m:
        return "channel", "@" + m.group(1)
    if u.startswith("UC") and len(u) > 20:
        return "channel", u
    return "unknown", u


def _ytdlp_print(target: str, fmt: str, items: Optional[str] = None, timeout: int = 60) -> List[str]:
    cmd = [sys.executable, "-m", "yt_dlp", "--no-warnings", "--quiet", "--print", fmt]
    if items:
        cmd += ["--playlist-items", items]
    cmd.append(target)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return [ln for ln in (p.stdout or "").splitlines() if ln.strip()]
    except Exception as e:  # noqa: BLE001
        logger.warning("yt-dlp print failed for %s: %s", target, e)
        return []


def resolve_channel(handle_or_id: str) -> Optional[Dict[str, str]]:
    """Resolve @handle or /channel/UC... -> {id, name, handle}. Tries items 1..6 to dodge
    members-only/premiere first videos."""
    if handle_or_id.startswith("UC") and len(handle_or_id) > 20:
        url = f"https://www.youtube.com/channel/{handle_or_id}/videos"
        handle = ""
    else:
        h = handle_or_id.lstrip("@")
        url = f"https://www.youtube.com/@{h}/videos"
        handle = h
    for items in ("1", "2:6"):
        rows = _ytdlp_print(url, "%(channel_id)s|%(channel)s|%(uploader_id)s", items=items)
        for row in rows:
            parts = row.split("|")
            if parts and parts[0].startswith("UC"):
                return {"id": parts[0], "name": parts[1] if len(parts) > 1 else handle,
                        "handle": (handle or (parts[2].lstrip("@") if len(parts) > 2 else ""))}
    return None


def video_meta(video_id: str) -> Optional[Dict[str, Any]]:
    url = f"https://www.youtube.com/watch?v={video_id}"
    rows = _ytdlp_print(url, "%(id)s|%(title)s|%(channel)s|%(channel_id)s|%(upload_date)s")
    if not rows:
        return None
    p = rows[0].split("|")
    if len(p) < 5:
        return None
    ud = p[4]
    iso = f"{ud[:4]}-{ud[4:6]}-{ud[6:8]}" if len(ud) == 8 and ud.isdigit() else ud
    return {"video_id": p[0], "title": p[1], "channel": p[2], "channel_id": p[3],
            "published": iso, "url": url}


def channel_recent_public(channel_id: str, n: int = 8) -> List[Dict[str, str]]:
    """Recent PUBLIC uploads via RSS (skips members-only & unaired premieres entirely)."""
    try:
        req = urllib.request.Request(RSS.format(cid=channel_id), headers={"User-Agent": "Mozilla/5.0"})
        xml = urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:  # noqa: BLE001
        logger.warning("RSS fetch failed for %s: %s", channel_id, e)
        return []
    try:
        root = ET.fromstring(xml)
    except Exception:  # noqa: BLE001
        return []
    author = (root.findtext("a:author/a:name", default="", namespaces=_NS) or "")
    out: List[Dict[str, str]] = []
    for e in root.findall("a:entry", _NS):
        vid = e.findtext("yt:videoId", default="", namespaces=_NS)
        title = e.findtext("a:title", default="", namespaces=_NS)
        published = e.findtext("a:published", default="", namespaces=_NS)
        if vid:
            out.append({"video_id": vid, "title": title, "channel": author,
                        "channel_id": channel_id, "published": published[:10],
                        "url": f"https://www.youtube.com/watch?v={vid}"})
        if len(out) >= n:
            break
    return out
