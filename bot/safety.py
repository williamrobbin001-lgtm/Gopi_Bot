"""Destructive-action detection for the confirmation guardrail.

check(tool_name, args) returns a plain-English description of the risky
action, or None if the call is safe to run without asking Gopi.
"""
import re
from typing import Any

from bot import config
from bot.tools.base import resolve_path
from bot.tools.paths import normalize_format, target_path

# A command word must not be glued to other word characters or hyphens,
# so "format" matches but "Format-Table" and "reformat" don't.
_W = r"(?<![\w-]){}(?![\w-])"

_DESTRUCTIVE_WORDS = [
    "Remove-Item", "rm", "del", "erase", "rd", "rmdir",
    "Format-Volume", "format", "diskpart", "mkfs", "dd",
    "Stop-Process", "taskkill", "kill", "pkill", "killall",
    "Stop-Computer", "Restart-Computer", "shutdown", "reboot",
    "Set-ExecutionPolicy", "Clear-Content", "Set-Content", "Out-File",
    "Move-Item", "mv", "move", "sudo",
]

_DESTRUCTIVE_PATTERNS = [re.compile(_W.format(re.escape(w)), re.I) for w in _DESTRUCTIVE_WORDS] + [
    re.compile(p, re.I)
    for p in (
        r"\breg(\.exe)?\s+delete\b",
        r"\bgit\s+reset\s+--hard\b",
        r"\bgit\s+clean\b",
        r"\bgit\s+push\b.*(\s--force\b|\s-f\b|\s--force-with-lease\b)",
        r"\bchmod\s+-R\b",
    )
]

# "> file" (not ">>", not "2>&1", not "> $null")
_REDIRECT = re.compile(r"(?<![>\d])\d?>(?!>|&)\s*(\"[^\"]+\"|'[^']+'|[^\s|;&]+)")


def _redirect_overwrites(command: str, cwd: str | None) -> str | None:
    for match in _REDIRECT.finditer(command):
        target = match.group(1).strip("\"'")
        if target.lower() in ("$null", "nul", "/dev/null"):
            continue
        path = resolve_path(target) if cwd is None or _is_abs(target) else resolve_path(cwd) / target
        if path.exists():
            return str(path)
    return None


def _is_abs(target: str) -> bool:
    return target.startswith(("~", "/", "\\", "$")) or re.match(r"^[a-zA-Z]:", target) is not None


def shell_command_risk(command: str, cwd: str | None = None) -> str | None:
    for pattern in _DESTRUCTIVE_PATTERNS:
        if pattern.search(command):
            return f"Run a destructive command: {command}"
    overwritten = _redirect_overwrites(command, cwd)
    if overwritten:
        return f"Overwrite {overwritten} with command output: {command}"
    return None


# ---- permission modes -------------------------------------------------------------
# "ask": confirm every risky action before it runs. "auto": run risky actions directly.
# Destructive actions (check() below) confirm in both modes unless CONFIRM_DESTRUCTIVE=false.
MODES = ("ask", "auto")
_mode = "ask" if config.CONFIRM_ACTIONS else "auto"


def get_mode() -> str:
    return _mode


def set_mode(mode: str) -> str:
    global _mode
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    _mode = mode
    return _mode


def _risky_action(tool_name: str, args: dict[str, Any]) -> str | None:
    """Plain description of a risky (not necessarily destructive) action, else None."""
    if tool_name == "run_shell":
        return f"Run this command: {args.get('command', '')}"
    if tool_name == "write_file":
        return f"Write to the file {args.get('path', '')}"
    if tool_name == "open_app":
        return f"Open {args.get('target', '')}"
    if tool_name == "open_url":
        return f"Open {args.get('url', '')} in the browser"
    if tool_name == "handoff_to_stronger_model":
        return f"Send this task and our conversation context to {config.HANDOFF_MODEL}"
    if tool_name == "start_background_job":
        inner = str(args.get("kind", ""))
        inner_args = args.get("args") if isinstance(args.get("args"), dict) else {}
        return _risky_action(inner, inner_args)
    return None


def confirmation_needed(tool_name: str, args: dict[str, Any]) -> str | None:
    """The action to describe to Gopi before running this call, or None to run it now."""
    if args.get("confirmed"):
        return None
    if tool_name == "set_permission_mode" and args.get("mode") == "auto":
        # Turning confirmations off always takes a spoken yes (a web page can't do it).
        return "Turn off confirmations, so I act without asking first"
    inner = (tool_name, args)
    if tool_name == "start_background_job" and isinstance(args.get("args"), dict):
        inner = (str(args.get("kind", "")), args["args"])
    if config.CONFIRM_DESTRUCTIVE:
        destructive = check(*inner)
        if destructive:
            return destructive
    if _mode == "ask":
        return _risky_action(tool_name, args)
    return None


def check(tool_name: str, args: dict[str, Any]) -> str | None:
    """Return a description of the destructive action, or None if safe."""
    try:
        if tool_name == "run_shell":
            return shell_command_risk(str(args.get("command", "")), args.get("cwd"))
        if tool_name == "write_file" and args.get("mode") == "overwrite":
            path = resolve_path(str(args.get("path", "")))
            if path.exists():
                return f"Overwrite the existing file {path}"
        if tool_name == "create_document" and args.get("overwrite"):
            fmt = normalize_format(str(args.get("format", "")))
            if fmt:
                path = target_path(fmt, str(args.get("filename", "")), args.get("folder"))
                if path.exists():
                    return f"Overwrite the existing file {path}"
    except Exception:  # fail closed: if we can't tell, ask
        return f"{tool_name} with {args} (safety check could not verify it)"
    return None
