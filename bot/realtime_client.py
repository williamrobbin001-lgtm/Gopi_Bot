"""Realtime API session: streams mic audio up, plays model audio back, handles barge-in.

Event names follow the GA Realtime API (checked against developers.openai.com):
session.update / input_audio_buffer.append / response.cancel /
conversation.item.create / response.create (client) and
response.output_audio.delta / input_audio_buffer.speech_started / response.done /
error (server). Unknown server events are logged at DEBUG.

Tool calls are collected from response.done only (not from
response.function_call_arguments.done), so each call runs exactly once.
"""
import asyncio
import base64
import json
import logging
import time
from typing import Any

from websockets.asyncio.client import ClientConnection, connect

from bot import config, jobs
from bot.audio_io import Microphone, Speaker
from bot.dispatcher import dispatch
from bot.memory import Transcript
from bot.prompts import GREETING_PROMPT, build_instructions
from bot.tools import TOOLS
from bot.tools.base import drain_conversation_items

log = logging.getLogger(__name__)

REALTIME_URL = "wss://api.openai.com/v1/realtime?model={model}"
# After Gopi stops talking, the model usually starts replying within ~1 s; wait that out
# before speaking a background update so it never cuts in on his turn.
QUIET_BEFORE_UPDATE_SECONDS = 1.5

# Server events we receive but don't need to act on.
IGNORED_EVENTS = {
    "session.created",
    "input_audio_buffer.committed",
    "conversation.item.added",
    "conversation.item.done",
    "conversation.item.created",
    "response.output_item.added",
    "response.output_item.done",
    "response.content_part.added",
    "response.content_part.done",
    "response.output_audio.done",
    "conversation.item.truncated",
    "response.output_audio_transcript.delta",
    "conversation.item.input_audio_transcription.delta",
    "response.function_call_arguments.delta",
    "response.function_call_arguments.done",  # calls are taken from response.done
    "rate_limits.updated",
}


def session_config(instructions: str | None = None) -> dict[str, Any]:
    pcm = {"type": "audio/pcm", "rate": config.SAMPLE_RATE}
    return {
        "type": "realtime",
        "instructions": instructions or build_instructions(),
        "output_modalities": ["audio"],
        "audio": {
            "input": {
                "format": pcm,
                "noise_reduction": {"type": "near_field"},
                # Text of what Gopi says, for the end-of-call memory summary.
                "transcription": {"model": config.TRANSCRIBE_MODEL},
                "turn_detection": {
                    "type": "semantic_vad",
                    "eagerness": config.TURN_EAGERNESS,
                    "create_response": True,
                    "interrupt_response": True,
                },
            },
            "output": {"format": pcm, "voice": config.VOICE},
        },
        "tools": TOOLS,
        "tool_choice": "auto",
    }


class RealtimeClient:
    def __init__(
        self,
        mic: Microphone,
        speaker: Speaker,
        instructions: str | None = None,
        transcript: Transcript | None = None,
    ) -> None:
        self.mic = mic
        self.speaker = speaker
        self.instructions = instructions or build_instructions()
        self.transcript = transcript if transcript is not None else Transcript()
        self.ws: ClientConnection | None = None
        self.response_active = False
        self.active_response_id: str | None = None
        self._cancelled: set[str] = set()  # responses whose late audio must be dropped
        self._greeted = False
        # Background-job updates wait here until Gopi isn't talking and no reply is active.
        self._updates: asyncio.Queue[str] = asyncio.Queue()
        self._user_speaking = False
        self._last_speech_end = 0.0
        self._idle = asyncio.Event()  # set when no response is in progress (or reserved)
        self._idle.set()
        self._response_lock = asyncio.Lock()
        self._awaiting_created = False  # we sent response.create; response.created not seen yet
        self._tasks: set[asyncio.Task] = set()

    async def send(self, event: dict[str, Any]) -> None:
        assert self.ws is not None
        await self.ws.send(json.dumps(event))

    async def run(self) -> None:
        url = REALTIME_URL.format(model=config.REALTIME_MODEL)
        headers = {"Authorization": f"Bearer {config.OPENAI_API_KEY}"}
        async with connect(url, additional_headers=headers, max_size=None) as ws:
            self.ws = ws
            log.info("Connected to Realtime API (model=%s)", config.REALTIME_MODEL)
            await self.send({"type": "session.update", "session": session_config(self.instructions)})
            jobs.manager.attach(asyncio.get_running_loop(), self.notify)
            await asyncio.gather(self._pump_mic(), self._receive(), self._deliver_updates())

    async def notify(self, note: str) -> None:
        """Queue something for the bot to say unprompted (job progress / completion)."""
        await self._updates.put(note)

    async def _deliver_updates(self) -> None:
        """Speak queued updates one at a time, never over Gopi or another reply."""
        while True:
            note = await self._updates.get()
            await self._wait_for_quiet()
            await self.say(note)

    async def _wait_for_quiet(self) -> None:
        while True:
            await self._idle.wait()
            quiet_for = time.monotonic() - self._last_speech_end
            if not self._user_speaking and quiet_for >= QUIET_BEFORE_UPDATE_SECONDS:
                return
            await asyncio.sleep(0.2)

    async def _pump_mic(self) -> None:
        """Task A: mic queue -> input_audio_buffer.append."""
        while True:
            chunk = await self.mic.queue.get()
            await self.send(
                {
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(chunk).decode("ascii"),
                }
            )

    async def _receive(self) -> None:
        """Task B: handle server events."""
        assert self.ws is not None
        async for raw in self.ws:
            event = json.loads(raw)
            await self._handle(event)

    async def _handle(self, event: dict[str, Any]) -> None:
        etype = event.get("type", "")

        if etype in ("response.output_audio.delta", "response.audio.delta"):
            if event.get("response_id") in self._cancelled:
                return  # late audio from an interrupted reply: never replay it
            self.speaker.play(base64.b64decode(event["delta"]), event.get("item_id"))
        elif etype == "input_audio_buffer.speech_started":
            self._user_speaking = True
            await self._barge_in()
        elif etype == "input_audio_buffer.speech_stopped":
            self._user_speaking = False
            self._last_speech_end = time.monotonic()
        elif etype == "response.created":
            self.response_active = True
            self._awaiting_created = False
            self.active_response_id = event.get("response", {}).get("id")
            self._idle.clear()
        elif etype == "response.done":
            self.response_active = False
            self._idle.set()
            self._on_response_done(event.get("response", {}))
        elif etype == "response.output_audio_transcript.done":
            log.info("Bot: %s", event.get("transcript", ""))
            self.transcript.add("assistant", event.get("transcript", ""))
        elif etype == "conversation.item.input_audio_transcription.completed":
            log.info("Gopi: %s", event.get("transcript", ""))
            self.transcript.add("user", event.get("transcript", ""))
        elif etype == "session.updated":
            if not self._greeted:
                self._greeted = True
                log.info("Session ready. Just start talking (Ctrl+C to quit).")
                self._spawn(self._greet())
        elif etype == "error":
            err = event.get("error", {})
            # Cancelling when nothing is playing is harmless; keep it quiet.
            if err.get("code") in ("response_cancel_not_active", "cancellation_failed"):
                log.debug("cancel ignored: %s", err.get("message"))
            else:
                log.error("Realtime error: %s", err)
            if self._awaiting_created and not self.response_active:
                # Our response.create was rejected, so no response.done will come for it:
                # release the reservation or every later reply would wait forever.
                self._awaiting_created = False
                self._idle.set()
        elif etype not in IGNORED_EVENTS:
            log.debug("Unhandled event: %s", etype)

    async def _greet(self) -> None:
        """Hands-free start: say hello once, in persona, without waiting for a key press."""
        await self.say(GREETING_PROMPT)

    async def say(self, note: str) -> None:
        """Have the bot speak about `note` (a system message), without overlapping a reply."""
        item = {
            "type": "message",
            "role": "system",
            "content": [{"type": "input_text", "text": note}],
        }
        await self._create_response(before=[item])

    async def _create_response(self, before: list[dict[str, Any]] = ()) -> None:
        """The only place that sends response.create.

        Waits until no response is active, adds `before` items, then reserves the
        slot (clears _idle) *before* sending, so a second caller can't slip in during
        the gap until the server's response.created arrives. That gap is what caused
        conversation_already_has_active_response.
        """
        async with self._response_lock:
            await self._idle.wait()
            for item in before:
                await self.send({"type": "conversation.item.create", "item": item})
            self._idle.clear()
            self._awaiting_created = True
            await self.send({"type": "response.create"})

    async def _barge_in(self) -> None:
        """Gopi started talking: silence now, cancel the reply, and trim the model's
        memory of it to what he actually heard (so "go on" resumes from there)."""
        cut = self.speaker.clear()  # first: stop sound immediately
        if self.response_active:
            if self.active_response_id:
                self._cancelled.add(self.active_response_id)
            await self.send({"type": "response.cancel"})
        if cut and cut[0]:
            item_id, played_ms = cut
            await self.send(
                {
                    "type": "conversation.item.truncate",
                    "item_id": item_id,
                    "content_index": 0,
                    "audio_end_ms": played_ms,
                }
            )
            log.debug("Barge-in: truncated %s at %d ms", item_id, played_ms)

    def _on_response_done(self, response: dict[str, Any]) -> None:
        status = response.get("status")
        log.debug("response.done status=%s", status)
        if status != "completed":
            return  # cancelled by barge-in or failed: don't act on partial calls
        calls = [
            item
            for item in response.get("output", [])
            if item.get("type") == "function_call"
        ]
        if calls:
            # Run as a background task so audio keeps flowing while tools work.
            self._spawn(self._handle_calls(calls))

    def _spawn(self, coro) -> asyncio.Task:
        """Run coro in the background (never inside the receive loop, which it may wait on)."""
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _handle_calls(self, calls: list[dict[str, Any]]) -> None:
        """Run every call, return each output, then ask for one new response."""
        try:
            # Sequential, in the model's order: later calls may depend on earlier ones.
            for call in calls:
                output = await dispatch(call.get("name", ""), call.get("arguments", ""))
                await self.send(
                    {
                        "type": "conversation.item.create",
                        "item": {
                            "type": "function_call_output",
                            "call_id": call["call_id"],
                            "output": output,
                        },
                    }
                )
            # Extra items tools asked for (e.g. a screenshot) go in before the reply.
            for item in drain_conversation_items():
                await self.send({"type": "conversation.item.create", "item": item})
            # Never overlap responses: the gate waits out anything already in progress.
            await self._create_response()
        except Exception:
            log.exception("tool-call handling failed")
