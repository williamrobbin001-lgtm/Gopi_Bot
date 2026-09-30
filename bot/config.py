"""Settings loaded from .env, exposed as typed constants."""
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "").strip()
REALTIME_MODEL: str = os.getenv("REALTIME_MODEL", "gpt-realtime-2.1-mini").strip()
REALTIME_VOICE: str = os.getenv("REALTIME_VOICE", "marin").strip()
# Persona: one name and one voice for every reply. VOICE overrides REALTIME_VOICE (alt: cedar).
PERSONA_NAME: str = os.getenv("PERSONA_NAME", "Gopi Bot").strip() or "Gopi Bot"
VOICE: str = os.getenv("VOICE", REALTIME_VOICE).strip() or "marin"
TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "").strip()
BRAVE_API_KEY: str = os.getenv("BRAVE_API_KEY", "").strip()
OUTPUT_DIR: Path = (PROJECT_ROOT / os.getenv("OUTPUT_DIR", "./output")).resolve()
CONFIRM_DESTRUCTIVE: bool = _bool("CONFIRM_DESTRUCTIVE", True)
# Permission mode at startup: true = "ask" before risky actions, false = "auto".
# Toggled at runtime by voice via set_permission_mode.
CONFIRM_ACTIONS: bool = _bool("CONFIRM_ACTIONS", True)
TOOL_TIMEOUT_SECONDS: int = _int("TOOL_TIMEOUT_SECONDS", 60)
MAX_TOOL_OUTPUT_CHARS: int = _int("MAX_TOOL_OUTPUT_CHARS", 8000)
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").strip().upper()
SEARCH_TIMEOUT_SECONDS: int = _int("SEARCH_TIMEOUT_SECONDS", 15)
SCRAPE_MAX_CHARS: int = _int("SCRAPE_MAX_CHARS", 6000)

# Long-term memory (memory/ folder, git-ignored).
MEMORY_DIR: Path = (PROJECT_ROOT / os.getenv("MEMORY_DIR", "./memory")).resolve()
MEMORY_SESSIONS_TO_LOAD: int = max(1, min(_int("MEMORY_SESSIONS_TO_LOAD", 3), 3))
MEMORY_MAX_WORDS: int = _int("MEMORY_MAX_WORDS", 300)
SUMMARY_MODEL: str = os.getenv("SUMMARY_MODEL", "gpt-5.6-luna").strip()  # cheap end-of-call summary
TRANSCRIBE_MODEL: str = os.getenv("TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe").strip()  # Gopi's words -> text

# Background jobs.
JOB_TIMEOUT_SECONDS: int = _int("JOB_TIMEOUT_SECONDS", 900)
JOB_PROGRESS_AFTER_SECONDS: int = _int("JOB_PROGRESS_AFTER_SECONDS", 30)

# Deep reasoning (think_deeply, deep research synthesis).
REASONING_MODEL: str = os.getenv("REASONING_MODEL", "gpt-5.6-sol").strip()

# Handoff to a stronger model: HANDOFF_MODEL is the name Gopi says; HANDOFF_MODEL_ID is the API id.
HANDOFF_MODEL: str = os.getenv("HANDOFF_MODEL", "GPT 6 Luna").strip()
HANDOFF_MODEL_ID: str = os.getenv("HANDOFF_MODEL_ID", "gpt-6-luna").strip()
HANDOFF_ENABLED: bool = _bool("HANDOFF_ENABLED", True)

# Turn detection: semantic_vad waits through mid-sentence pauses. low = most patient.
TURN_EAGERNESS: str = os.getenv("TURN_EAGERNESS", "low").strip().lower()
if TURN_EAGERNESS not in ("low", "medium", "high", "auto"):
    TURN_EAGERNESS = "low"

LOG_FILE: Path = PROJECT_ROOT / os.getenv("LOG_FILE", "bot.log")

# Audio format required by the Realtime API: 24 kHz, mono, PCM16.
SAMPLE_RATE = 24_000
CHANNELS = 1
BLOCK_MS = 40
BLOCK_SAMPLES = SAMPLE_RATE * BLOCK_MS // 1000


def require_openai_key() -> None:
    """Exit with a clear message if the OpenAI key is missing."""
    if not OPENAI_API_KEY:
        sys.exit(
            "Add OPENAI_API_KEY to .env to start voice (copy .env.example to .env first)."
        )


def setup_logging() -> None:
    """Log to bot.log (full detail) and the console (LOG_LEVEL)."""
    level = getattr(logging, LOG_LEVEL, logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.DEBUG if level <= logging.DEBUG else logging.INFO)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.setLevel(level)

    root = logging.getLogger()
    root.setLevel(min(level, logging.INFO))
    root.addHandler(file_handler)
    root.addHandler(console)
    # Third-party libraries are noisy at DEBUG.
    for noisy in ("websockets", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
