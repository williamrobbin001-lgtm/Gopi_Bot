"""Computer-access tools: shell, files, folders, and launching apps.

Every handler is sync, returns a JSON string, and never raises.
Destructive-action checks happen in the dispatcher (bot/safety.py) before
these run; `confirmed` is accepted here only so the schema can carry it.
"""
import fnmatch
import os
import platform
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from bot import config
from bot.tools.base import CONFIRMED_PARAM, err, ok, resolve_path, tool

IS_WINDOWS = sys.platform == "win32"
# Room for the JSON envelope inside the dispatcher's output cap.
_FIELD_CAP = max(1000, config.MAX_TOOL_OUTPUT_CHARS - 1500)
_MAX_ENTRIES = 200

# Remembered between calls so "now go into that folder" works.
_last_cwd: Path | None = None

_CONFIRMED = CONFIRMED_PARAM


def _cap(text: str, limit: int = _FIELD_CAP) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated {len(text) - limit} chars]"


def _shell_argv(command: str) -> list[str]:
    if IS_WINDOWS:
        # Force UTF-8 so non-ASCII output survives decoding.
        prefix = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        return ["powershell", "-NoProfile", "-NonInteractive", "-Command", prefix + command]
    return ["bash", "-lc", command]


@tool(
    "run_shell",
    "Run a command on Gopi's "
    + ("Windows PC in PowerShell" if IS_WINDOWS else f"{platform.system()} machine in bash")
    + ". Use for system info (disk space, processes, network), installing packages, "
    "running scripts, git, searching for files, or anything a terminal can do. "
    "Example: Get-PSDrive C | Select-Object Used,Free. Commands must be non-interactive: "
    "never start programs that wait for input; use flags like -y or -Force instead. "
    "The working directory persists between calls unless cwd is given.",
    {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The command to run."},
            "cwd": {"type": "string", "description": "Working directory (default: last used, else home)."},
            "timeout_seconds": {"type": "integer", "description": "Max run time in seconds."},
            "confirmed": _CONFIRMED,
        },
        "required": ["command"],
    },
)
def run_shell(
    command: str,
    cwd: str | None = None,
    timeout_seconds: int | None = None,
    confirmed: bool = False,
) -> str:
    global _last_cwd
    try:
        workdir = resolve_path(cwd) if cwd else (_last_cwd or Path.home())
        if not workdir.is_dir():
            return err(f"folder not found: {workdir}")
        limit = config.TOOL_TIMEOUT_SECONDS
        if timeout_seconds:
            limit = max(1, min(int(timeout_seconds), limit))
        start = time.monotonic()
        try:
            proc = subprocess.run(
                _shell_argv(command),
                cwd=workdir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=limit,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:  # subprocess.run kills the process
            return err(f"timed out after {limit} s", command=command)
        _last_cwd = workdir
        result = {
            "exit_code": proc.returncode,
            "stdout": _cap(proc.stdout.strip()),
            "stderr": _cap(proc.stderr.strip(), 2000),
            "cwd": str(workdir),
            "duration_ms": int((time.monotonic() - start) * 1000),
        }
        if proc.returncode != 0:
            return err(f"command exited with code {proc.returncode}", **result)
        return ok(**result)
    except Exception as e:
        return err(f"{type(e).__name__}: {e}")


@tool(
    "read_file",
    "Read a text file on Gopi's computer (code, notes, logs, CSV, config). "
    "Paths can use ~ or names like 'desktop/notes.txt'. Summarize the content aloud; "
    "never read it out verbatim. Example: path='~/Documents/todo.txt'.",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path."},
            "max_chars": {"type": "integer", "description": "Max characters to return (default 8000)."},
            "start_line": {"type": "integer", "description": "1-based line to start from."},
        },
        "required": ["path"],
    },
)
def read_file(path: str, max_chars: int = 8000, start_line: int | None = None) -> str:
    try:
        p = resolve_path(path)
        if not p.is_file():
            return err(f"file not found: {p}")
        with p.open("rb") as f:
            if b"\x00" in f.read(8192):
                return err("binary file, can't read it as text", path=str(p), size=p.stat().st_size)
        text = p.read_text(encoding="utf-8", errors="replace")
        if start_line and start_line > 1:
            text = "".join(text.splitlines(keepends=True)[start_line - 1:])
        limit = max(1, min(int(max_chars), _FIELD_CAP))
        return ok(
            path=str(p),
            total_chars=len(text),
            content=text[:limit],
            truncated=len(text) > limit,
        )
    except Exception as e:
        return err(f"{type(e).__name__}: {e}")


@tool(
    "write_file",
    "Write a plain text file (notes, scripts, config). mode='create' (default) makes a new "
    "file and fails if it exists; 'append' adds to the end; 'overwrite' replaces an existing "
    "file and needs Gopi's confirmation. Parent folders are created. For formatted documents "
    "(Word, PDF, CSV reports) use create_document instead when available.",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path, e.g. 'desktop/hello.txt'."},
            "content": {"type": "string", "description": "Text to write."},
            "mode": {"type": "string", "enum": ["create", "append", "overwrite"]},
            "confirmed": _CONFIRMED,
        },
        "required": ["path", "content"],
    },
)
def write_file(path: str, content: str, mode: str = "create", confirmed: bool = False) -> str:
    try:
        if mode not in ("create", "append", "overwrite"):
            return err(f"invalid mode {mode!r}; use create, append, or overwrite")
        p = resolve_path(path)
        if p.is_dir():
            return err(f"that's a folder, not a file: {p}")
        if mode == "create" and p.exists():
            return err(f"file already exists: {p}. Use mode 'append', or 'overwrite' (needs confirmation).")
        p.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode("utf-8")
        with p.open("ab" if mode == "append" else "wb") as f:
            f.write(data)
        return ok(path=str(p), bytes_written=len(data), mode=mode)
    except Exception as e:
        return err(f"{type(e).__name__}: {e}")


def _is_hidden(entry: os.DirEntry) -> bool:
    if entry.name.startswith("."):
        return True
    attrs = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
    return bool(attrs & 0x2)  # FILE_ATTRIBUTE_HIDDEN on Windows


@tool(
    "list_dir",
    "List what's in a folder on Gopi's computer: names, file/folder, size, modified time. "
    "Understands 'desktop', 'downloads', 'documents', and ~. Use pattern to filter, "
    "e.g. pattern='*.pdf'. Summarize the result aloud; don't read every name.",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Folder path, e.g. 'desktop'."},
            "show_hidden": {"type": "boolean", "description": "Include hidden files (default false)."},
            "pattern": {"type": "string", "description": "Glob filter on names, e.g. '*.docx'."},
        },
        "required": ["path"],
    },
)
def list_dir(path: str, show_hidden: bool = False, pattern: str | None = None) -> str:
    try:
        p = resolve_path(path)
        if not p.is_dir():
            return err(f"folder not found: {p}")
        entries = []
        with os.scandir(p) as it:
            for entry in it:
                try:
                    if not show_hidden and _is_hidden(entry):
                        continue
                    if pattern and not fnmatch.fnmatch(entry.name.lower(), pattern.lower()):
                        continue
                    st = entry.stat()
                    is_dir = entry.is_dir()
                    entries.append(
                        {
                            "name": entry.name,
                            "type": "dir" if is_dir else "file",
                            "size": None if is_dir else st.st_size,
                            "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="minutes"),
                        }
                    )
                except OSError:
                    continue  # unreadable entry; skip it
        entries.sort(key=lambda e: (e["type"] != "dir", e["name"].lower()))
        return ok(
            path=str(p),
            total=len(entries),
            truncated=len(entries) > _MAX_ENTRIES,
            entries=entries[:_MAX_ENTRIES],
        )
    except Exception as e:
        return err(f"{type(e).__name__}: {e}")


_URL = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")


def _launch(target: str) -> str | None:
    """Start the target without waiting; return an error message or None."""
    is_url = bool(_URL.match(target))
    path = None if is_url else resolve_path(target)
    location = target if is_url else (str(path) if path.exists() else None)

    if IS_WINDOWS:
        if location:
            os.startfile(location)
            return None
        # App name (notepad, chrome, code, calc...). Start-Process returns immediately.
        safe = target.replace("'", "''")
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", f"Start-Process '{safe}'"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
            stdin=subprocess.DEVNULL,
        )
        if proc.returncode:
            return proc.stderr.strip() or f"exit code {proc.returncode}"
        return None

    if sys.platform == "darwin":
        argv = ["open", location] if location else ["open", "-a", target]
    else:
        argv = ["xdg-open", location] if location else [target]
    subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return None


@tool(
    "open_app",
    "Open an app, file, folder, or URL on Gopi's computer with its default program. "
    "Examples: 'notepad', 'chrome', 'calc', 'code', 'downloads', "
    "'~/Desktop/report.docx', 'https://example.com'. Doesn't wait for the app to close.",
    {
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "App name, file or folder path, or URL."},
            "confirmed": _CONFIRMED,
        },
        "required": ["target"],
    },
)
def open_app(target: str) -> str:
    try:
        target = target.strip()
        if not target:
            return err("nothing to open")
        problem = _launch(target)
        if problem:
            return err(f"couldn't open {target}: {problem[:500]}")
        return ok(opened=target)
    except Exception as e:
        return err(f"{type(e).__name__}: {e}")
