"""Persistent facts in memory/facts.json, grouped by category."""
import json
import re
import threading
from pathlib import Path

from bot import config

CATEGORIES = ("preference", "project", "decision", "person")
_lock = threading.Lock()


def facts_path() -> Path:
    return config.MEMORY_DIR / "facts.json"


def _norm(text: str) -> str:
    return re.sub(r"[\s.!]+$", "", re.sub(r"\s+", " ", text.strip().lower()))


def load_facts() -> dict[str, list[str]]:
    path = facts_path()
    data: dict = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    return {c: [str(f) for f in data.get(c, []) if str(f).strip()] for c in CATEGORIES}


def _save(facts: dict[str, list[str]]) -> None:
    path = facts_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(facts, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def add_fact(fact: str, category: str) -> bool:
    """Append a fact; False if it's already known (case/punctuation-insensitive)."""
    fact = fact.strip()
    if not fact:
        raise ValueError("empty fact")
    if category not in CATEGORIES:
        raise ValueError(f"category must be one of {CATEGORIES}")
    with _lock:
        facts = load_facts()
        if any(_norm(f) == _norm(fact) for items in facts.values() for f in items):
            return False
        facts[category].append(fact)
        _save(facts)
        return True


def remove_fact(fact: str) -> str | None:
    """Remove the matching fact (exact, else a unique partial match). Returns it, or None."""
    target = _norm(fact)
    if not target:
        return None
    with _lock:
        facts = load_facts()
        entries = [(c, f) for c, items in facts.items() for f in items]
        matches = [e for e in entries if _norm(e[1]) == target] or [
            e for e in entries if target in _norm(e[1])
        ]
        if len(matches) != 1:
            return None
        category, removed = matches[0]
        facts[category].remove(removed)
        _save(facts)
        return removed


def facts_section() -> str:
    facts = load_facts()
    if not any(facts.values()):
        return ""
    lines = ["## Known facts"]
    for category in CATEGORIES:
        for f in facts[category]:
            lines.append(f"- ({category}) {f}")
    return "\n".join(lines)
