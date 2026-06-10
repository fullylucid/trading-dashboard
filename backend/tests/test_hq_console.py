"""Tests for the HQ Console transcript renderer (CONSOLE.md Slice 1) — slug rule, event
parsing into chat blocks, secret scrubbing, and incremental tail."""

import json

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
