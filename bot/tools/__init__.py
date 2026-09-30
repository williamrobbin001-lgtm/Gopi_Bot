"""Tool registry: TOOLS holds JSON schemas sent to the model, HANDLERS maps names to functions.

Importing a tool module registers its @tool functions. Add new modules here.
"""
from collections.abc import Callable
from typing import Any

from bot.tools import (  # noqa: F401  (registers tools on import)
    computer, files, handoff, jobs_tools, memory_tools, permissions, reasoning, research, screen,
)
from bot.tools.base import REGISTRY

TOOLS: list[dict[str, Any]] = [schema for schema, _ in REGISTRY.values()]
HANDLERS: dict[str, Callable[..., str]] = {name: fn for name, (_, fn) in REGISTRY.items()}
