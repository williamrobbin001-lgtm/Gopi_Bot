"""Long-term memory: session summaries (sessions.py) and a persistent fact store (store.py).

Data lives in the project's memory/ folder (git-ignored).
"""
from bot.memory.sessions import Transcript, recent_summaries_section, save_session
from bot.memory.store import add_fact, facts_section, load_facts, remove_fact


MEMORY_RULES = """\
## Private background memory
This is private background memory. Do not recite, list, or summarize it unprompted.
Use it silently to answer questions and personalize replies.
Only talk about past sessions when Gopi asks about them (for example "what were we
working on?" or "do you remember X?"), and then answer only what he asked."""


def memory_section() -> str:
    """Everything remembered, wrapped as private context for the session instructions."""
    body = "\n\n".join(s for s in (recent_summaries_section(), facts_section()) if s)
    if not body:
        return ""
    return f"{MEMORY_RULES}\n<private_memory>\n{body}\n</private_memory>"


__all__ = [
    "Transcript", "save_session", "recent_summaries_section",
    "add_fact", "remove_fact", "load_facts", "facts_section", "memory_section",
]
