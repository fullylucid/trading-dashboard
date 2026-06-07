"""Tests for the cyborganic MJPEG stream (B2) — the pure framing/control helpers and the
offline placeholder asset. The async controller + generator are exercised by the manual
interop test against a dropped live.jpg (see the PR), not here."""

import json

import hq_stream


def test_mjpeg_part_framing():
    part = hq_stream.mjpeg_part(b"\xff\xd8jpeg\xff\xd9", boundary="b")
    assert part.startswith(b"--b\r\n")
    assert b"Content-Type: image/jpeg\r\n" in part
    assert b"Content-Length: 8\r\n\r\n" in part   # len of the fake jpeg
    assert part.endswith(b"\r\n")
    assert b"\xff\xd8jpeg\xff\xd9" in part


def test_control_payload_shape():
    p = hq_stream.control_payload(True, 1780800000.9)
    assert p == {
        "streaming": True,
        "fps": hq_stream.FPS,
        "max_width": hq_stream.MAX_WIDTH,
        "quality": hq_stream.QUALITY,
        "updated_at": 1780800000,   # epoch truncated to int
    }
    # round-trips as the JSON the app polls
    assert json.loads(json.dumps(p))["streaming"] is True
    assert hq_stream.control_payload(False, 0)["streaming"] is False


def test_offline_placeholder_asset_present():
    # shipped as a static asset so the container needs no Pillow at runtime
    assert _is_jpeg(hq_stream._OFFLINE_BYTES)


def _is_jpeg(b: bytes) -> bool:
    return len(b) > 100 and b[:2] == b"\xff\xd8" and b[-2:] == b"\xff\xd9"
