"""Screen awareness: capture on request, downscale, send as input_image."""
import asyncio
import base64
import io
import json

import pytest
from PIL import Image

from bot import config
from bot.realtime_client import RealtimeClient
from bot.tools import screen
from bot.tools.base import drain_conversation_items


@pytest.fixture(autouse=True)
def fake_screen(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_FILE", tmp_path / "test-bot.log")
    drain_conversation_items()

    class FakeGrab:
        @staticmethod
        def grab():
            return Image.new("RGB", (2560, 1440), "navy")

    import PIL
    monkeypatch.setattr(PIL, "ImageGrab", FakeGrab, raising=False)
    import sys
    monkeypatch.setitem(sys.modules, "PIL.ImageGrab", FakeGrab)
    yield
    drain_conversation_items()


def test_capture_downscales_to_1280_jpeg():
    jpeg, w, h = screen.capture_jpeg()
    assert (w, h) == (1280, 720) and jpeg[:2] == b"\xff\xd8"


def test_look_at_screen_queues_input_image():
    r = json.loads(screen.look_at_screen("what app is open?"))
    assert r["ok"] and r["width"] == 1280
    [item] = drain_conversation_items()
    image, text = item["content"]
    assert item["role"] == "user" and image["type"] == "input_image"
    assert image["image_url"].startswith("data:image/jpeg;base64,")
    decoded = Image.open(io.BytesIO(base64.b64decode(image["image_url"].split(",", 1)[1])))
    assert max(decoded.size) == 1280
    assert "what app is open?" in text["text"]


def test_capture_failure_is_calm(monkeypatch):
    def broken():
        raise OSError("no display")

    monkeypatch.setattr(screen, "capture_jpeg", broken)
    r = json.loads(screen.look_at_screen())
    assert r["ok"] is False and "no display" in r["error"] and drain_conversation_items() == []


def test_client_sends_screenshot_before_reply():
    class Quiet:
        def play(self, *a): pass
        def clear(self): return None

    client = RealtimeClient(mic=None, speaker=Quiet())
    client.sent = []

    async def fake_send(event):
        client.sent.append(event)

    client.send = fake_send

    async def scenario():
        await client._handle({"type": "response.done", "response": {"status": "completed", "output": [
            {"type": "function_call", "call_id": "c1", "name": "look_at_screen", "arguments": "{}"}]}})
        while client._tasks:
            await asyncio.gather(*list(client._tasks))

    asyncio.run(scenario())
    kinds = [(e["type"], e.get("item", {}).get("type")) for e in client.sent]
    assert kinds == [
        ("conversation.item.create", "function_call_output"),
        ("conversation.item.create", "message"),
        ("response.create", None),
    ]
    assert client.sent[1]["item"]["content"][0]["type"] == "input_image"


def test_no_continuous_capture():
    import inspect
    import bot.realtime_client as rc
    assert "capture_jpeg" not in inspect.getsource(rc) and "look_at_screen" not in inspect.getsource(rc)
