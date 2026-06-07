"""Tests for the cyborganic MJPEG stream (B2) — the pure framing/control helpers and the
offline placeholder asset. The async controller + generator are exercised by the manual
interop test against a dropped live.jpg (see the PR), not here."""

import json

import pytest

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


# --------------------------------------------------------------------------- app control (B3)
def test_app_control_payload_is_state_enum_only():
    p = hq_stream.app_control_payload("running", 1780808000.9)
    # CONTROL.md security rule: a state enum + metadata, NEVER a command/path/args
    assert p == {"desired": "running", "requested_at": 1780808000, "requested_by": "hq"}
    assert set(p) == {"desired", "requested_at", "requested_by"}


def test_write_app_control_rejects_unknown_action(tmp_path, monkeypatch):
    monkeypatch.setattr(hq_stream, "STREAM_DIR", str(tmp_path))
    monkeypatch.setattr(hq_stream, "APP_CONTROL_JSON", str(tmp_path / "app-control.json"))
    with pytest.raises(ValueError):
        hq_stream.write_app_control("delete-everything", 1.0)  # not run/stop -> rejected


def test_write_app_control_run_stop(tmp_path, monkeypatch):
    monkeypatch.setattr(hq_stream, "STREAM_DIR", str(tmp_path))
    monkeypatch.setattr(hq_stream, "APP_CONTROL_JSON", str(tmp_path / "app-control.json"))
    hq_stream.write_app_control("run", 100.0)
    assert json.loads((tmp_path / "app-control.json").read_text())["desired"] == "running"
    hq_stream.write_app_control("stop", 200.0)
    assert json.loads((tmp_path / "app-control.json").read_text())["desired"] == "stopped"


def test_app_status_view_fresh_running():
    v = hq_stream.app_status_view(
        {"state": "running", "pid": 4242, "since": 1000, "updated_at": 1010, "detail": ""}, now=1015
    )
    assert v["controller_offline"] is False
    assert v["state"] == "running" and v["pid"] == 4242


def test_app_status_view_stale_is_controller_offline():
    v = hq_stream.app_status_view({"state": "running", "updated_at": 1000}, now=1000 + 60)
    assert v["controller_offline"] is True   # heartbeat stale -> launcher not running


def test_app_status_view_missing_file():
    v = hq_stream.app_status_view(None, now=123)
    assert v == {"controller_offline": True, "state": "offline", "pid": None,
                 "since": None, "updated_at": None, "detail": ""}


@pytest.mark.parametrize("samples,expected", [
    ([], None),
    ([(100.0, 5)], None),                       # one sample -> can't measure
    ([(100.0, 0), (110.0, 120)], 12.0),         # 120 frames / 10s = 12 fps
    ([(100.0, 0), (100.2, 5)], None),           # span too short
    ([(100.0, 10), (110.0, 10)], None),         # no new frames
])
def test_measure_fps(samples, expected):
    assert hq_stream.measure_fps(samples) == expected
