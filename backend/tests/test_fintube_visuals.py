"""Unit tests for fintube.visuals — command construction, gating, paths, doc shape.

The async run_visuals orchestration needs ffmpeg/yt-dlp/the pool (and pytest-asyncio,
absent here); we pin the sync seams it's built from.
"""

from fintube import visuals
from fintube.visuals import (_download_cmd, _sample_cmd, _interval_for, keep_caption,
                             frame_path, _doc)


# --------------------------------------------------------------------------- #
# command builders + interval math
# --------------------------------------------------------------------------- #
def test_download_cmd_caps_resolution_and_duration():
    cmd = _download_cmd("https://youtu.be/abc", "/tmp/video.%(ext)s")
    joined = " ".join(cmd)
    assert "yt_dlp" in joined
    assert f"height<={visuals.MAX_HEIGHT}" in joined
    assert f"*0-{visuals.MAX_DURATION_S}" in joined           # only the first chunk
    assert "--download-sections" in cmd
    assert cmd[-1] == "https://youtu.be/abc"


def test_sample_cmd_uses_interval_and_extract_cap():
    cmd = _sample_cmd("/tmp/v.mp4", "/tmp/f_%04d.jpg", 60)
    joined = " ".join(cmd)
    assert cmd[0] == "ffmpeg"
    assert "fps=1/60" in joined
    assert cmd[cmd.index("-frames:v") + 1] == str(visuals.EXTRACT_CAP)


def test_interval_adapts_to_duration_and_clamps():
    # long video -> spread ~EXTRACT_CAP frames; clamped to MAX
    assert _interval_for(3600) == visuals.MAX_INTERVAL_S
    # short video -> clamped to MIN (never spammier than MIN_INTERVAL)
    assert _interval_for(60) == visuals.MIN_INTERVAL_S
    # mid video -> duration / EXTRACT_CAP, within bounds
    mid = _interval_for(visuals.EXTRACT_CAP * 50)   # -> 50s, within [MIN, MAX]
    assert mid == 50
    # unknown duration -> default
    assert _interval_for(None) == visuals.DEFAULT_INTERVAL_S
    assert _interval_for(0) == visuals.DEFAULT_INTERVAL_S


# --------------------------------------------------------------------------- #
# keep_caption gate
# --------------------------------------------------------------------------- #
def test_keep_caption_drops_skip_and_empty():
    assert keep_caption("SKIP") is None
    assert keep_caption("skip") is None
    assert keep_caption("SKIP - just a talking head") is None
    assert keep_caption("") is None
    assert keep_caption("   ") is None
    assert keep_caption(None) is None


def test_keep_caption_keeps_real_description():
    cap = "A candlestick chart with RSI subpanel; clean dark theme, labeled axes."
    assert keep_caption(f"  {cap}  ") == cap


# --------------------------------------------------------------------------- #
# paths + doc
# --------------------------------------------------------------------------- #
def test_frame_path(monkeypatch):
    monkeypatch.setattr(visuals, "VISUALS_DIR", "/data/fintube_visuals")
    assert frame_path("vid123", 4) == "/data/fintube_visuals/vid123/4.jpg"


def test_doc_shape_and_extra():
    d = _doc("vid", "http://u", "Title", status="done",
             frames=[{"idx": 0, "file": "0.jpg", "caption": "x"}], kept=1, extracted=10)
    assert d["video_id"] == "vid"
    assert d["status"] == "done"
    assert d["kept"] == 1 and d["extracted"] == 10
    assert d["frames"][0]["file"] == "0.jpg"
    assert "updated" in d


def test_get_result_none_without_redis(monkeypatch):
    monkeypatch.setattr(visuals.store, "r", lambda: None)
    assert visuals.get_result("whatever") is None


def test_is_running_tracks_set(monkeypatch):
    monkeypatch.setattr(visuals, "_running", {"vidA"})
    assert visuals.is_running("vidA") is True
    assert visuals.is_running("vidB") is False
