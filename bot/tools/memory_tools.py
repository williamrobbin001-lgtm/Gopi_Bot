"""remember / forget: the model's handle on the persistent fact store."""
from bot.memory import store
from bot.tools.base import err, ok, tool


@tool(
    "remember",
    "Save a fact about Gopi for future calls. Call it when he states a preference, a "
    "project detail, a decision worth keeping, or something about a person. Write the fact "
    "as a short standalone sentence, e.g. 'Gopi prefers reports as Word documents.'",
    {
        "type": "object",
        "properties": {
            "fact": {"type": "string", "description": "Short standalone sentence."},
            "category": {"type": "string", "enum": list(store.CATEGORIES)},
        },
        "required": ["fact", "category"],
    },
)
def remember(fact: str, category: str) -> str:
    try:
        added = store.add_fact(fact, category)
        return ok(saved=added, fact=fact.strip(), note=None if added else "already known")
    except ValueError as e:
        return err(str(e))
    except Exception as e:
        return err(f"{type(e).__name__}: {e}")


@tool(
    "forget",
    "Remove a saved fact when Gopi asks you to forget it or says it's no longer true.",
    {
        "type": "object",
        "properties": {"fact": {"type": "string", "description": "The fact, or a distinctive part of it."}},
        "required": ["fact"],
    },
)
def forget(fact: str) -> str:
    try:
        removed = store.remove_fact(fact)
        if removed is None:
            return err("no single saved fact matches that; ask Gopi which one he means")
        return ok(forgot=removed)
    except Exception as e:
        return err(f"{type(e).__name__}: {e}")
