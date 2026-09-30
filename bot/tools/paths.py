"""Where created documents go and what they're called.

Shared by files.py (to write) and safety.py (to check overwrites), so both
always agree on the exact target path.
"""
import re
from datetime import datetime
from pathlib import Path

from bot import config
from bot.tools.base import known_folder, resolve_path

EXTENSIONS = {"md", "pdf", "docx", "csv", "xlsx", "txt", "json", "html"}
FORMAT_ALIASES = {
    "word": "docx", "doc": "docx", "markdown": "md", "excel": "xlsx", "xls": "xlsx",
    "spreadsheet": "csv", "text": "txt", "htm": "html",
}

_FOLDER_ALIASES = {
    "desktop": "Desktop", "documents": "Documents", "docs": "Documents",
    "my documents": "Documents", "downloads": "Downloads",
}
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
_MAX_NAME = 80


def normalize_format(fmt: str) -> str | None:
    f = (fmt or "").strip().lower().lstrip(".")
    f = FORMAT_ALIASES.get(f, f)
    return f if f in EXTENSIONS else None


def resolve_folder(folder: str | None) -> Path:
    """Alias ("desktop", "my downloads", "output") or any path; default OUTPUT_DIR."""
    key = (folder or "").strip().lower().removeprefix("my ").strip()
    if not key or key in ("output", "outputs", "output folder", "default"):
        return config.OUTPUT_DIR
    if key in _FOLDER_ALIASES:
        return known_folder(_FOLDER_ALIASES[key])
    return resolve_path(folder)


def slugify(name: str) -> str:
    """ "Weekly Goals!" -> "weekly-goals"; empty -> document-YYYY-MM-DD-HHMM."""
    stem = (name or "").strip()
    # Drop an extension the model may have typed ("report.doc").
    stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", stem)
    stem = stem.lower()
    stem = re.sub(r"[^\w\s-]", "", stem)  # strips \/:*?"<>| and other symbols
    stem = re.sub(r"[\s_-]+", "-", stem).strip("-")[:_MAX_NAME].strip("-")
    if not stem:
        stem = f"document-{datetime.now():%Y-%m-%d-%H%M}"
    if stem in _RESERVED:
        stem += "-file"
    return stem


def target_path(fmt: str, filename: str, folder: str | None) -> Path:
    """The exact path a create_document call would write (before de-duplication)."""
    return resolve_folder(folder) / f"{slugify(filename)}.{fmt}"


def unique_path(path: Path) -> Path:
    """path, or path-1, path-2... if it already exists."""
    if not path.exists():
        return path
    n = 1
    while True:
        candidate = path.with_name(f"{path.stem}-{n}{path.suffix}")
        if not candidate.exists():
            return candidate
        n += 1
