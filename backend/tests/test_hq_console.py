"""Tests for the HQ Console — transcript renderer (Slice 1) and the input layer (Slice 2):
slug rule, event parsing, scrubbing, incremental tail, input validation, and the host relay's
pane/job guards."""

import importlib.util
import json
from pathlib import Path

import pytest

import hq_console


def test_transcript_dir_name_archive_rule():
    # every non [A-Za-z0-9-] char -> '-' (so '__' -> '--')
    assert hq_console.transcript_dir_name("/home/user/hydra-worktrees/trading-dashboard__hq") == \
        "-home-user-hydra-worktrees-trading-dashboard--hq"
    assert hq_console.transcript_dir_name("/home/user/cribdar") == "-home-user-cribdar"


def test_parse_event_string_user():
    t = hq_console.parse_event({"type": "user", "uuid": "u1", "timestamp": "t",
                                "message": {"role": "user", "content": "hello there"}})
    assert t["type"] == "user"
    assert t["blocks"] == [{"kind": "text", "text": "hello there"}]


def test_parse_event_assistant_blocks():
    t = hq_console.parse_event({"type": "assistant", "uuid": "a1", "message": {"content": [
        {"type": "thinking", "thinking": "hmm", "signature": "x"},
        {"type": "text", "text": "doing it"},
        {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
    ]}})
    kinds = [b["kind"] for b in t["blocks"]]
    assert kinds == ["thinking", "text", "tool_use"]
    assert t["blocks"][2]["name"] == "Bash" and '"command": "ls"' in t["blocks"][2]["input"]


def test_parse_event_tool_result_string_and_list_and_error():
    t1 = hq_console.parse_event({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "x", "content": "plain output"}]}})
    assert t1["blocks"][0] == {"kind": "tool_result", "text": "plain output", "is_error": False}
    t2 = hq_console.parse_event({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "x", "is_error": True,
         "content": [{"type": "text", "text": "boom"}]}]}})
    assert t2["blocks"][0]["is_error"] is True and t2["blocks"][0]["text"] == "boom"


def test_parse_event_skips_empty_and_nonchat():
    assert hq_console.parse_event({"type": "assistant", "message": {"content": []}}) is None
    assert hq_console.parse_event({"type": "pr-link"}) is None
    assert hq_console.parse_event({"type": "assistant", "message": {"content": [
        {"type": "text", "text": "   "}]}}) is None


def test_scrub_secrets_in_blocks():
    t = hq_console.parse_event({"type": "assistant", "message": {"content": [
        {"type": "text", "text": "key is ghp_ABCDEFGHIJKLMNOP1234567890 ok"}]}})
    assert "ghp_ABCDEF" not in t["blocks"][0]["text"]
    assert "[REDACTED]" in t["blocks"][0]["text"]


def test_read_turns_last_n_and_incremental(tmp_path):
    p = tmp_path / "t.jsonl"
    lines = [json.dumps({"type": "user", "uuid": f"u{i}", "message": {"content": f"msg {i}"}}) for i in range(5)]
    p.write_text("\n".join(lines) + "\n")
    turns, cursor = hq_console.read_turns(str(p), limit=3)
    assert [b["text"] for t in turns for b in t["blocks"]] == ["msg 2", "msg 3", "msg 4"]  # last 3
    assert cursor == p.stat().st_size
    # append two more; incremental tail from the cursor returns only the new ones
    with open(p, "a") as f:
        f.write(json.dumps({"type": "user", "uuid": "u5", "message": {"content": "msg 5"}}) + "\n")
    new_turns, new_cursor = hq_console.read_turns(str(p), after=cursor)
    assert [b["text"] for t in new_turns for b in t["blocks"]] == ["msg 5"]
    assert new_cursor > cursor


# --------------------------------------------------------------------------- input (Slice 2)
def test_clean_input_text_strips_trailing_newline_and_validates():
    assert hq_console.clean_input_text("hello\n") == "hello"      # trailing \n stripped (relay sends Enter)
    assert hq_console.clean_input_text("a\nb") == "a\nb"          # internal newlines kept
    for bad in ["", "   ", "\n\n", 123, None]:
        with pytest.raises(ValueError):
            hq_console.clean_input_text(bad)
    with pytest.raises(ValueError):
        hq_console.clean_input_text("x" * (hq_console.INPUT_TEXT_MAX + 1))


@pytest.mark.parametrize("pane,ok", [
    ("%12", True), ("%0", True),
    ("12", False), ("%", False), ("%1a", False), ("$1", False),
    ("; rm -rf /", False), (None, False), (12, False),
])
def test_valid_pane(pane, ok):
    assert hq_console.valid_pane(pane) is ok


def test_input_job_shape():
    j = hq_console.input_job("charts", "%4", "do the thing", "me@x.com", 1780000000.7, "abc123")
    assert j == {"id": "abc123", "head": "charts", "pane": "%4", "text": "do the thing",
                 "by": "me@x.com", "ts": 1780000000}


# --------------------------------------------------------------------------- host relay guards
def _load_relay():
    path = Path(__file__).resolve().parents[2] / "scripts" / "hq_input_relay.py"
    spec = importlib.util.spec_from_file_location("hq_input_relay", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


relay = _load_relay()


def test_relay_parse_job():
    assert relay.parse_job('{"pane":"%4","text":"hi"}') == {"pane": "%4", "text": "hi"}
    assert relay.parse_job("not json") is None
    assert relay.parse_job("[1,2,3]") is None   # not a dict


def test_relay_valid_pane_matches_backend():
    assert relay.valid_pane("%9") is True
    assert relay.valid_pane("9") is False
    assert relay.valid_pane("%9; tmux kill-server") is False


def test_relay_handle_rejects_dead_or_bad_pane(monkeypatch):
    sent, results = [], []
    monkeypatch.setattr(relay, "send_to_pane", lambda pane, text: sent.append((pane, text)) or True)
    monkeypatch.setattr(relay, "write_result", lambda jid, ok: results.append((jid, ok)))
    live = {"%4"}
    relay.handle({"id": "j1", "pane": "%4", "text": "ok"}, live)     # valid + live -> sent + ok
    relay.handle({"id": "j2", "pane": "%9", "text": "x"}, live)      # not in live -> dropped + failed
    relay.handle({"id": "j3", "pane": "bad", "text": "x"}, live)     # bad form -> dropped + failed
    relay.handle({"id": "j4", "pane": "%4", "text": ""}, live)       # empty -> dropped + failed
    assert sent == [("%4", "ok")]
    assert results == [("j1", True), ("j2", False), ("j3", False), ("j4", False)]


# --------------------------------------------------------------------------- upload (F4)
@pytest.mark.parametrize("fn,expected", [
    ("a.png", True), ("b.JPG", True), ("c.heic", True), ("d.pdf", False), ("e.txt", False), ("f", False),
])
def test_is_image(fn, expected):
    assert hq_console.is_image(fn) == expected


def test_safe_upload_name_sanitizes_and_prefixes():
    n = hq_console.safe_upload_name("../../etc/pa ss wд.png", "abcdef123456")
    assert n.startswith("abcdef12-") and "/" not in n and ".." not in n
    assert n.endswith(".png")
    assert hq_console.safe_upload_name("", "xyz") == "xyz-file"


def test_upload_message_format():
    p = "/home/user/hydra-worktrees/.hq-uploads/x.png"
    assert hq_console.upload_message("why is this red?", p, True) == f"why is this red?\n[image attached] {p}"
    assert hq_console.upload_message("", p, True) == f"[image attached] {p}"           # no caption -> just the signal
    assert hq_console.upload_message("", "/d/doc.pdf", False) == "[file attached] /d/doc.pdf"


def test_build_message_multiple_attachments():
    msg = hq_console.build_message("look", [{"path": "/u/a.png", "image": True}, {"path": "/u/b.pdf", "image": False}])
    assert msg == "look\n[image attached] /u/a.png\n[file attached] /u/b.pdf"
    assert hq_console.build_message("", [{"path": "/u/a.png", "image": True}]) == "[image attached] /u/a.png"
    for bad in [("", []), ("", [{"image": True}])]:   # no caption + no usable attachment -> reject
        with pytest.raises(ValueError):
            hq_console.build_message(*bad)


@pytest.mark.parametrize("name,code", [
    ("../etc/passwd", 400), ("a/b.png", 400), (".secret", 400), ("missing.png", 404),
])
def test_serve_upload_path_safety(name, code, tmp_path, monkeypatch):
    import hq_routes
    monkeypatch.setattr(hq_console, "UPLOADS_DIR", str(tmp_path))
    with pytest.raises(Exception) as e:   # fastapi.HTTPException
        hq_routes.serve_upload(name)
    assert getattr(e.value, "status_code", None) == code


def test_serve_upload_valid(tmp_path, monkeypatch):
    import hq_routes
    monkeypatch.setattr(hq_console, "UPLOADS_DIR", str(tmp_path))
    (tmp_path / "ok.png").write_bytes(b"x" * 200)
    resp = hq_routes.serve_upload("ok.png")
    assert resp.__class__.__name__ == "FileResponse"
