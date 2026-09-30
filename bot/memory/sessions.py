"""Session memory: record the call's transcript, summarize it at the end, load recent
summaries at the next boot."""
import logging
import re
import threading
from datetime import datetime
from pathlib import Path

from bot import config, llm

log = logging.getLogger(__name__)

RAW_FALLBACK_TURNS = 20
RAW_MARKER = "## Raw transcript (summary unavailable)"

SUMMARY_INSTRUCTIONS = """\
Summarize this voice call between Gopi and his assistant for the assistant's memory.
Write short Markdown with exactly these headings, and only facts from the transcript:
## Caller
## Worked on
## Open tasks
## Decisions
Use "- none" under a heading with nothing to say. Keep it under 150 words."""


class Transcript:
    """User and assistant turns from the current call (thread-safe)."""

    def __init__(self) -> None:
        self.turns: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def add(self, role: str, text: str) -> None:
        text = (text or "").strip()
        if text:
            with self._lock:
                self.turns.append((role, text))

    def render(self, last: int | None = None) -> str:
        with self._lock:
            turns = self.turns[-last:] if last else list(self.turns)
        names = {"user": "Gopi", "assistant": config.PERSONA_NAME}
        return "\n".join(f"{names.get(role, role)}: {text}" for role, text in turns)

    def __len__(self) -> int:
        with self._lock:
            return len(self.turns)


def sessions_dir() -> Path:
    return config.MEMORY_DIR / "sessions"


def save_session(transcript: Transcript, now: datetime | None = None) -> Path | None:
    """Summarize the call into memory/sessions/<timestamp>.md.

    Falls back to the last ~20 raw turns if the summary call fails.
    Returns None for an empty call (nothing worth remembering).
    """
    if not len(transcript):
        return None
    now = now or datetime.now()
    try:
        body = llm.complete(
            transcript.render(),
            model=config.SUMMARY_MODEL,
            instructions=SUMMARY_INSTRUCTIONS,
            timeout=60,
        )
    except Exception as e:  # never lose the call: keep the raw tail instead
        log.warning("session summary failed (%s); saving raw turns", e)
        body = RAW_MARKER + "\n" + transcript.render(last=RAW_FALLBACK_TURNS)
    folder = sessions_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{now:%Y-%m-%d_%H-%M-%S}.md"
    path.write_text(f"# Call on {now:%Y-%m-%d %H:%M}\n\n{body.strip()}\n", encoding="utf-8")
    log.info("Saved session memory to %s", path)
    return path


def _trim_words(text: str, max_words: int) -> str:
    """Cut text after max_words words, keeping its line breaks."""
    for count, match in enumerate(re.finditer(r"\S+", text), start=1):
        if count > max_words:
            return text[: match.start()].rstrip() + " ..."
    return text


def recent_summaries_section(count: int | None = None, max_words: int | None = None) -> str:
    """The most recent 1-3 summaries (newest first), capped to a few hundred words."""
    count = count or config.MEMORY_SESSIONS_TO_LOAD
    max_words = max_words or config.MEMORY_MAX_WORDS
    folder = sessions_dir()
    if not folder.is_dir():
        return ""
    files = sorted(folder.glob("*.md"), reverse=True)[:count]
    if not files:
        return ""
    parts, budget = [], max_words
    for f in files:
        try:
            text = f.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if RAW_MARKER in text:
            text = _condense_raw(text)
        text = text.replace("\n# ", "\n### ").replace("\n## ", "\n#### ")
        text = re.sub(r"^# ", "### ", text)
        text = _trim_words(text, budget)
        parts.append(text)
        budget -= len(re.findall(r"\S+", text))
        if budget <= 20:
            break
    return "### Previous calls (newest first)\n" + "\n\n".join(parts)


RAW_INJECT_TURNS = 6
RAW_INJECT_WORDS_PER_TURN = 25


def _condense_raw(text: str) -> str:
    """A raw-transcript fallback is loaded only as its last few turns, each shortened,
    never verbatim in full."""
    header, _, body = text.partition(RAW_MARKER)
    turns = [line for line in body.splitlines() if line.strip()][-RAW_INJECT_TURNS:]
    short = [_trim_words(t, RAW_INJECT_WORDS_PER_TURN) for t in turns]
    return f"{header}## Last few lines (no summary was saved)\n" + "\n".join(short)
