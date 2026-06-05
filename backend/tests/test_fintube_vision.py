"""Unit tests for fintube.vision — the OpenAI-compatible VLM client seams.

The async POST itself needs a live endpoint (and pytest-asyncio, absent here), so we pin the
pure logic: request shape, response parsing, task-prompt selection, yes/no interpretation,
config gating, and base64 helper.
"""

from fintube import vision


def test_is_configured_reflects_url(monkeypatch):
    monkeypatch.setattr(vision, "VLM_URL", "")
    assert vision.is_configured() is False
    monkeypatch.setattr(vision, "VLM_URL", "http://vlm:8080/v1")
    assert vision.is_configured() is True


def test_to_b64_roundtrips():
    import base64
    b = b"\x00\x01hello"
    assert base64.b64decode(vision.to_b64(b)) == b


def test_task_instruction_known_and_fallback():
    assert "title" in vision.task_instruction("read_title").lower()
    # unknown task falls back to the default caption prompt
    assert vision.task_instruction("nope") == vision._TASKS[vision._DEFAULT_TASK]


def test_payload_is_openai_multimodal_shape(monkeypatch):
    monkeypatch.setattr(vision, "VLM_MODEL", "smolvlm")
    p = vision._payload("QUJD", "read the title", "image/png", 64)
    assert p["model"] == "smolvlm"
    assert p["max_tokens"] == 64
    content = p["messages"][0]["content"]
    kinds = {part["type"] for part in content}
    assert kinds == {"text", "image_url"}
    img = next(part for part in content if part["type"] == "image_url")
    assert img["image_url"]["url"] == "data:image/png;base64,QUJD"


def test_parse_response_extracts_content():
    data = {"choices": [{"message": {"content": "  NVDA breakout — ZipTrader \n"}}]}
    assert vision._parse_response(data) == "NVDA breakout — ZipTrader"


def test_parse_response_handles_garbage():
    assert vision._parse_response(None) is None
    assert vision._parse_response({}) is None
    assert vision._parse_response({"choices": []}) is None
    assert vision._parse_response({"choices": [{"message": {"content": "   "}}]}) is None


def test_parse_yes_no():
    assert vision.parse_yes_no("yes — it's a dashboard") is True
    assert vision.parse_yes_no("No, just a talking head") is False
    assert vision.parse_yes_no("maybe?") is None
    assert vision.parse_yes_no("") is None
    assert vision.parse_yes_no(None) is None
