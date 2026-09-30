"""Agent loop in realtime_client, driven with fake server events (no network, no audio)."""
import asyncio
import json

import pytest

from bot import config
from bot.audio_io import BYTES_PER_MS, PlaybackBuffer
from bot.realtime_client import RealtimeClient, session_config


class FakeSpeaker:
    """The real PlaybackBuffer, without a sound card."""

    def __init__(self) -> None:
        self.buffer = PlaybackBuffer()
        self.cleared = 0

    def play(self, pcm: bytes, item_id: str | None = None) -> None:
        self.buffer.push(pcm, item_id)

    def clear(self):
        self.cleared += 1
        return self.buffer.clear()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_FILE", tmp_path / "test-bot.log")
    c = RealtimeClient(mic=None, speaker=FakeSpeaker())
    c.sent = []

    async def fake_send(event):
        c.sent.append(event)

    c.send = fake_send
    return c


def done_event(status: str, *calls: dict) -> dict:
    return {"type": "response.done", "response": {"status": status, "output": list(calls)}}


def fn_call(call_id: str, name: str, args: dict) -> dict:
    return {"type": "function_call", "call_id": call_id, "name": name, "arguments": json.dumps(args)}


async def settle(c: RealtimeClient) -> None:
    while c._tasks:
        await asyncio.gather(*list(c._tasks))


def test_session_registers_tools():
    cfg = session_config()
    assert cfg["tool_choice"] == "auto"
    assert "run_shell" in {t["name"] for t in cfg["tools"]}


def test_calls_run_then_one_response_create(client, tmp_path):
    async def scenario():
        await client._handle({"type": "response.created"})
        await client._handle(
            done_event(
                "completed",
                fn_call("c1", "list_dir", {"path": str(tmp_path)}),
                fn_call("c2", "read_file", {"path": str(tmp_path / "missing.txt")}),
            )
        )
        await settle(client)

    asyncio.run(scenario())
    types = [e["type"] for e in client.sent]
    assert types == ["conversation.item.create", "conversation.item.create", "response.create"]
    outputs = {e["item"]["call_id"]: json.loads(e["item"]["output"]) for e in client.sent[:2]}
    assert outputs["c1"]["ok"] is True and outputs["c2"]["ok"] is False


def test_cancelled_response_runs_no_tools(client, tmp_path):
    async def scenario():
        await client._handle(done_event("cancelled", fn_call("c1", "list_dir", {"path": str(tmp_path)})))
        await settle(client)

    asyncio.run(scenario())
    assert client.sent == []


def test_response_create_waits_for_active_response(client, tmp_path):
    async def scenario():
        await client._handle(done_event("completed", fn_call("c1", "list_dir", {"path": str(tmp_path)})))
        # Gopi starts talking and a new response begins before the tool returns.
        await client._handle({"type": "response.created"})
        await asyncio.sleep(0.3)
        assert [e["type"] for e in client.sent] == ["conversation.item.create"]
        await client._handle(done_event("completed"))
        await settle(client)

    asyncio.run(scenario())
    assert client.sent[-1] == {"type": "response.create"}


def audio_delta(response_id: str, item_id: str, ms: int) -> dict:
    import base64

    pcm = b"\x01\x00" * (BYTES_PER_MS // 2 * ms)
    return {"type": "response.output_audio.delta", "response_id": response_id,
            "item_id": item_id, "delta": base64.b64encode(pcm).decode()}


def test_barge_in_without_audio_just_cancels(client):
    async def scenario():
        await client._handle({"type": "response.created", "response": {"id": "r1"}})
        await client._handle({"type": "input_audio_buffer.speech_started"})

    asyncio.run(scenario())
    assert client.speaker.cleared == 1
    assert client.sent == [{"type": "response.cancel"}]


def test_barge_in_truncates_to_played_ms_and_drops_stale_audio(client):
    async def scenario():
        await client._handle({"type": "response.created", "response": {"id": "r1"}})
        await client._handle(audio_delta("r1", "item_a", 1000))  # 1 s received
        client.speaker.buffer.pull(BYTES_PER_MS * 300)            # only 300 ms heard
        await client._handle({"type": "input_audio_buffer.speech_started"})
        await client._handle(audio_delta("r1", "item_a", 200))    # late audio after cancel

    asyncio.run(scenario())
    assert client.sent == [
        {"type": "response.cancel"},
        {"type": "conversation.item.truncate", "item_id": "item_a", "content_index": 0, "audio_end_ms": 300},
    ]
    assert client.speaker.buffer.pending is False  # stale audio was not queued


def test_new_response_audio_plays_after_barge_in(client):
    async def scenario():
        await client._handle({"type": "response.created", "response": {"id": "r1"}})
        await client._handle({"type": "input_audio_buffer.speech_started"})
        await client._handle({"type": "response.done", "response": {"id": "r1", "status": "cancelled"}})
        await client._handle({"type": "response.created", "response": {"id": "r2"}})
        await client._handle(audio_delta("r2", "item_b", 100))

    asyncio.run(scenario())
    assert client.speaker.buffer.pending is True


def test_playback_buffer_tracks_played_ms_per_item():
    buf = PlaybackBuffer()
    buf.push(b"\x00" * BYTES_PER_MS * 100, "a")
    buf.push(b"\x00" * BYTES_PER_MS * 100, "b")
    buf.pull(BYTES_PER_MS * 150)
    assert buf.played_ms("a") == 100 and buf.played_ms("b") == 50
    assert buf.clear() == ("b", 50)
    assert buf.clear() is None and buf.pull(10) == b""


def test_semantic_turn_detection_and_noise_reduction():
    audio_in = session_config()["audio"]["input"]
    assert audio_in["turn_detection"] == {
        "type": "semantic_vad", "eagerness": config.TURN_EAGERNESS,
        "create_response": True, "interrupt_response": True,
    }
    assert audio_in["noise_reduction"] == {"type": "near_field"}
    assert "server_vad" not in json.dumps(session_config())


def test_greets_once_on_start(client):
    async def scenario():
        await client._handle({"type": "session.updated"})
        await client._handle({"type": "session.updated"})  # later updates don't re-greet
        await settle(client)

    asyncio.run(scenario())
    types = [e["type"] for e in client.sent]
    assert types == ["conversation.item.create", "response.create"]
    assert client.sent[0]["item"]["role"] == "system"


def test_no_push_to_talk_gating():
    import inspect
    import bot.realtime_client as rc
    import main
    source = inspect.getsource(rc) + inspect.getsource(main)
    for gate in ("keyboard", "push_to_talk", "wake_word", "input("):
        assert gate not in source
