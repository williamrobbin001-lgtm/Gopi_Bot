"""Mic capture and speaker playback (24 kHz mono PCM16).

sounddevice callbacks run on PortAudio threads, so they never touch the
asyncio loop directly: the mic hands bytes over with call_soon_threadsafe,
and playback reads from a lock-protected byte buffer.
"""
import asyncio
import logging
import threading
from collections import deque

import numpy as np
import sounddevice as sd

from bot.config import BLOCK_SAMPLES, CHANNELS, SAMPLE_RATE

log = logging.getLogger(__name__)


class Microphone:
    """Pushes raw PCM16 blocks into an asyncio.Queue."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self.queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=200)
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=BLOCK_SAMPLES,
            callback=self._callback,
        )

    def _callback(self, indata: np.ndarray, frames: int, time, status) -> None:
        if status:
            log.debug("mic status: %s", status)
        self._loop.call_soon_threadsafe(self._put, bytes(indata))

    def _put(self, chunk: bytes) -> None:
        if self.queue.full():  # drop the oldest block rather than grow unbounded
            self.queue.get_nowait()
        self.queue.put_nowait(chunk)

    def start(self) -> None:
        self._stream.start()

    def close(self) -> None:
        self._stream.stop()
        self._stream.close()


BYTES_PER_MS = SAMPLE_RATE * 2 // 1000  # PCM16 mono


class PlaybackBuffer:
    """Queued PCM16 audio tagged by assistant item, with played-ms tracking.

    Pure logic (no audio device) so barge-in behaviour is unit-testable.
    "Played" means handed to the sound card, which is what Gopi actually heard.
    """

    def __init__(self) -> None:
        self._segments: deque[list] = deque()  # [item_id, bytearray]
        self._played: dict[str | None, int] = {}  # item_id -> bytes played
        self._lock = threading.Lock()

    def push(self, pcm: bytes, item_id: str | None = None) -> None:
        with self._lock:
            if self._segments and self._segments[-1][0] == item_id:
                self._segments[-1][1].extend(pcm)
            else:
                self._segments.append([item_id, bytearray(pcm)])

    def pull(self, nbytes: int) -> bytes:
        """Take up to nbytes for the sound card, crediting each item's played time."""
        out = bytearray()
        with self._lock:
            while self._segments and len(out) < nbytes:
                item_id, data = self._segments[0]
                take = data[: nbytes - len(out)]
                del data[: len(take)]
                out += take
                self._played[item_id] = self._played.get(item_id, 0) + len(take)
                if not data:
                    self._segments.popleft()
        return bytes(out)

    def clear(self) -> tuple[str | None, int] | None:
        """Drop all queued audio. Returns (item_id, played_ms) of the item that was
        cut off mid-playback, or None if nothing unplayed was dropped."""
        with self._lock:
            if not self._segments:
                return None
            item_id = self._segments[0][0]
            self._segments.clear()
            return item_id, self._played.get(item_id, 0) // BYTES_PER_MS

    def played_ms(self, item_id: str | None) -> int:
        with self._lock:
            return self._played.get(item_id, 0) // BYTES_PER_MS

    @property
    def pending(self) -> bool:
        with self._lock:
            return bool(self._segments)


class Speaker:
    """Plays queued PCM16 audio; clear() stops playback instantly (barge-in)."""

    def __init__(self) -> None:
        self.buffer = PlaybackBuffer()
        self._stream = sd.RawOutputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=BLOCK_SAMPLES,
            callback=self._callback,
        )

    def _callback(self, outdata, frames: int, time, status) -> None:
        if status:
            log.debug("speaker status: %s", status)
        needed = len(outdata)
        chunk = self.buffer.pull(needed)
        outdata[: len(chunk)] = chunk
        if len(chunk) < needed:
            outdata[len(chunk):] = b"\x00" * (needed - len(chunk))

    def play(self, pcm: bytes, item_id: str | None = None) -> None:
        self.buffer.push(pcm, item_id)

    def clear(self) -> tuple[str | None, int] | None:
        return self.buffer.clear()

    @property
    def is_playing(self) -> bool:
        return self.buffer.pending

    def start(self) -> None:
        self._stream.start()

    def close(self) -> None:
        self._stream.stop()
        self._stream.close()
