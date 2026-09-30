"""Runs a tool call safely: validate, confirm, execute off the loop, cap, log.

dispatch() is the single entry point for the voice loop and tools_cli.py,
so anything that works from the CLI works by voice.
"""
import asyncio
import inspect
import json
import logging
import re
import threading
import time
from datetime import datetime
from typing import Any

from bot import config, safety
from bot.tools import HANDLERS, web_utils
from bot.tools.base import err

# Actions worth tying to the last web page read, in case a page tried prompt injection.
_AUDITED_AFTER_WEB = {"run_shell", "write_file", "create_document", "open_app"}

log = logging.getLogger(__name__)
_log_lock = threading.Lock()

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"tvly-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]+"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password|passwd)(\s*[=:]\s*)(\S+)"),
]


def redact(text: str) -> str:
    for key in (config.OPENAI_API_KEY, config.TAVILY_API_KEY, config.BRAVE_API_KEY):
        if key:
            text = text.replace(key, "[REDACTED]")
    for pattern in _SECRET_PATTERNS:
        if pattern.groups == 3:
            text = pattern.sub(r"\1\2[REDACTED]", text)
        else:
            text = pattern.sub("[REDACTED]", text)
    return text


def truncate(text: str, limit: int | None = None) -> str:
    limit = limit or config.MAX_TOOL_OUTPUT_CHARS
    if len(text) <= limit:
        return text
    return text[:limit] + f"...[truncated {len(text) - limit} chars]"


def _needs_confirmation(action: str) -> str:
    return json.dumps(
        {
            "ok": False,
            "needs_confirmation": True,
            "action": action,
            "how_to_proceed": "Ask Gopi aloud. If he clearly says yes, call the same "
            "tool again with confirmed=true.",
        },
        ensure_ascii=False,
    )


def _write_log(entry: dict[str, Any]) -> None:
    """Append one JSON line per tool call to bot.log (works without logging setup)."""
    line = redact(json.dumps(entry, ensure_ascii=False, default=str))
    try:
        with _log_lock, open(config.LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as e:
        log.warning("could not write tool log: %s", e)


def _is_ok(result: str) -> bool:
    try:
        return bool(json.loads(result).get("ok"))
    except (ValueError, AttributeError):
        return False


async def _run(name: str, args: dict[str, Any]) -> str:
    handler = HANDLERS.get(name)
    if handler is None:
        return err(f"unknown tool {name!r}", available=sorted(HANDLERS))

    params = inspect.signature(handler).parameters
    # `confirmed` is the guardrail's flag; pass it on only to handlers that take it.
    call_args = {k: v for k, v in args.items() if k != "confirmed" or "confirmed" in params}
    try:
        inspect.signature(handler).bind(**call_args)
    except TypeError as e:
        return err(f"bad arguments for {name}: {e}", expected=list(params))

    action = safety.confirmation_needed(name, args)
    if action:
        return _needs_confirmation(action)

    # A little longer than the tool's own limit so run_shell reports its timeout itself.
    timeout = config.TOOL_TIMEOUT_SECONDS + 5
    try:
        return await asyncio.wait_for(asyncio.to_thread(handler, **call_args), timeout)
    except asyncio.TimeoutError:
        return err(f"{name} timed out after {timeout} s")
    except Exception as e:  # tools shouldn't raise, but never crash the session
        return err(f"{type(e).__name__}: {e}")


async def dispatch(name: str, arguments_json: str) -> str:
    start = time.monotonic()
    args: dict[str, Any] = {}
    try:
        parsed = json.loads(arguments_json) if arguments_json and arguments_json.strip() else {}
        if not isinstance(parsed, dict):
            raise ValueError("arguments must be a JSON object")
        args = parsed
        result = await _run(name, args)
    except ValueError as e:
        result = err(f"invalid arguments JSON: {e}")

    if not isinstance(result, str):
        result = json.dumps(result, default=str)
    result = truncate(result)

    duration_ms = int((time.monotonic() - start) * 1000)
    success = _is_ok(result)
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "tool": name,
        "args": args,
        "ok": success,
        "needs_confirmation": '"needs_confirmation": true' in result,
        "duration_ms": duration_ms,
        "output_chars": len(result),
    }
    if name in _AUDITED_AFTER_WEB and web_utils.last_web_url:
        entry["after_web_url"] = web_utils.last_web_url
    _write_log(entry)
    summary = redact(json.dumps(args, ensure_ascii=False))[:120]
    log.info("[tool] %s(%s) -> %s in %d ms", name, summary, "ok" if success else "not ok", duration_ms)
    return result
