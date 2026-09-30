"""Entry point: python main.py. Just start talking; Ctrl+C to quit."""
import asyncio
import logging

from bot import config
from bot.audio_io import Microphone, Speaker
from bot.memory import Transcript, memory_section, save_session
from bot.prompts import build_instructions
from bot.realtime_client import RealtimeClient

log = logging.getLogger("main")


async def run(transcript: Transcript) -> None:
    mic = Microphone(asyncio.get_running_loop())
    speaker = Speaker()
    mic.start()
    speaker.start()
    try:
        instructions = build_instructions(memory_section())
        await RealtimeClient(mic, speaker, instructions, transcript).run()
    finally:
        mic.close()
        speaker.close()


def main() -> None:
    config.require_openai_key()
    config.setup_logging()
    transcript = Transcript()
    try:
        asyncio.run(run(transcript))
    except KeyboardInterrupt:
        log.info("Bye.")
    finally:
        # Also runs on Ctrl+C: turn this call into memory for the next one.
        try:
            save_session(transcript)
        except Exception:
            log.exception("could not save session memory")


if __name__ == "__main__":
    main()
