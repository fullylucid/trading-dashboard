"""Unit tests for fintube.vision — the OpenAI-compatible VLM client seams.

The async POST itself needs a live endpoint (and pytest-asyncio, absent here), so we pin the
pure logic: request shape, response parsing, task-prompt selection, yes/no interpretation,
config gating, and base64 helper.
"""

from fintube import vision


def test_is_configured_and_backend_selection(monkeypatch):
    # nothing configured -> off
    monkeypatch.setattr(vision, "VLM_URL", "")
    monkeypatch.setattr(vision, "POOL_VISION", False)
    monkeypatch.setattr(vision, "VISION_DIR_HOST", "")
    assert vision.is_configured() is False
    assert vision.active_backend() is None

    # pool available (shared host dir set) -> pool backend
    monkeypatch.setattr(vision, "POOL_VISION", True)
    monkeypatch.setattr(vision, "VISION_DIR_HOST", "/home/user/vision")
    assert vision.pool_available() is True
    assert vision.is_configured() is True
    assert vision.active_backend() == "pool"

    # explicit VLM endpoint takes precedence over the pool
    monkeypatch.setattr(vision, "VLM_URL", "http://vlm:8080/v1")
    assert vision.active_backend() == "vlm"


def test_pool_unavailable_without_host_dir(monkeypatch):
    monkeypatch.setattr(vision, "POOL_VISION", True)
    monkeypatch.setattr(vision, "VISION_DIR_HOST", "")  # no shared path -> worker can't read
    assert vision.pool_available() is False


def test_pool_prompt_includes_worker_path_and_read_instruction(monkeypatch):
    monkeypatch.setattr(vision, "VISION_DIR_HOST", "/host/vision")
    assert vision._worker_path("abc.jpg") == "/host/vision/abc.jpg"
    p = vision._pool_prompt("Read the title.", "/host/vision/abc.jpg")
    assert "/host/vision/abc.jpg" in p
    assert "Read tool" in p
    assert "Read the title." in p


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
