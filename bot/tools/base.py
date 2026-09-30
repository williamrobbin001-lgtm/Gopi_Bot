"""Tool registry, result helpers, and path resolution shared by all tools.

Adding a tool = one function decorated with @tool. Nothing else changes.
"""
import json
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

# name -> (schema sent to the model, python handler)
REGISTRY: dict[str, tuple[dict[str, Any], Callable[..., str]]] = {}


def tool(name: str, description: str, parameters: dict[str, Any]) -> Callable:
    """Register a handler and its JSON schema under `name`."""

    def decorator(fn: Callable[..., str]) -> Callable[..., str]:
        schema = {
            "type": "function",
            "name": name,
            "description": description,
            "parameters": parameters,
        }
        REGISTRY[name] = (schema, fn)
        return fn

    return decorator


# Conversation items a tool wants added after its result (e.g. a screenshot as an
# input_image). Tool results can only be text, so the client sends these separately.
_pending_items: list[dict[str, Any]] = []
_pending_lock = threading.Lock()


def queue_conversation_item(item: dict[str, Any]) -> None:
    with _pending_lock:
        _pending_items.append(item)


def drain_conversation_items() -> list[dict[str, Any]]:
    with _pending_lock:
        items = list(_pending_items)
        _pending_items.clear()
        return items


# Schema property for tools the permission guardrail may pause (see bot/safety.py).
CONFIRMED_PARAM = {
    "type": "boolean",
    "description": "Set true ONLY after Gopi clearly said yes to a needs_confirmation prompt.",
}


def ok(**data: Any) -> str:
    return json.dumps({"ok": True, **data}, default=str, ensure_ascii=False)


def err(msg: str, **data: Any) -> str:
    return json.dumps({"ok": False, "error": msg, **data}, default=str, ensure_ascii=False)


_HOME_ALIASES = {"desktop": "Desktop", "downloads": "Downloads", "documents": "Documents"}


def known_folder(name: str) -> Path:
    """~/Desktop etc., falling back to OneDrive's redirected copy on Windows."""
    home = Path.home()
    local = home / name
    onedrive = home / "OneDrive" / name
    if not local.exists() and onedrive.exists():
        return onedrive
    return local


def resolve_path(raw: str) -> Path:
    """Expand env vars and ~, map "desktop"/"my downloads"/etc. to home folders.

    Relative paths are resolved against the home folder, which is what a
    spoken request ("the notes folder") almost always means.
    """
    text = os.path.expandvars(raw.strip().strip('"').strip("'"))
    parts = Path(text).parts
    if parts:
        first = parts[0].lower().removeprefix("my ").strip()
        if first in _HOME_ALIASES:
            return known_folder(_HOME_ALIASES[first]).joinpath(*parts[1:])
        if first == "~" and len(parts) > 1 and parts[1].lower() in _HOME_ALIASES:
            return known_folder(_HOME_ALIASES[parts[1].lower()]).joinpath(*parts[2:])
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = Path.home() / path
    return path
