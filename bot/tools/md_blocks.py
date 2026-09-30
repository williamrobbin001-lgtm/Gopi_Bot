"""Tiny Markdown -> blocks parser shared by the docx, pdf, html, and txt writers.

Blocks:
    {"type": "heading", "level": 1-3, "text": ...}
    {"type": "paragraph", "text": ...}
    {"type": "bullet", "text": ...} / {"type": "numbered", "text": ...}
    {"type": "table", "rows": [[cell, ...], ...]}
    {"type": "code", "text": ...}
"""
import re

Block = dict

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^\s*[-*+]\s+(.*)$")
_NUMBERED = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_TABLE_SEP = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$")
_INLINE = re.compile(r"(\*\*.+?\*\*|__.+?__|\*[^*\s][^*]*?\*|`[^`]+`)")


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse(md: str) -> list[Block]:
    blocks: list[Block] = []
    para: list[str] = []
    lines = (md or "").replace("\r\n", "\n").split("\n")

    def flush() -> None:
        if para:
            blocks.append({"type": "paragraph", "text": " ".join(para)})
            para.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            code = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            blocks.append({"type": "code", "text": "\n".join(code)})
        elif not stripped:
            flush()
        elif m := _HEADING.match(stripped):
            flush()
            blocks.append({"type": "heading", "level": min(len(m.group(1)), 3), "text": m.group(2).strip()})
        elif stripped.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                if not _TABLE_SEP.match(lines[i].strip()):
                    rows.append(_cells(lines[i]))
                i += 1
            blocks.append({"type": "table", "rows": rows})
            continue
        elif m := _BULLET.match(line):
            flush()
            blocks.append({"type": "bullet", "text": m.group(1).strip()})
        elif m := _NUMBERED.match(line):
            flush()
            blocks.append({"type": "numbered", "text": m.group(1).strip()})
        else:
            para.append(stripped)
        i += 1
    flush()
    return blocks


def inline_runs(text: str) -> list[tuple[str, bool, bool]]:
    """Split "a **b** *c*" into (text, bold, italic) runs. `code` becomes plain text."""
    runs = []
    for part in _INLINE.split(text):
        if not part:
            continue
        if (part.startswith("**") and part.endswith("**")) or (part.startswith("__") and part.endswith("__")):
            runs.append((part[2:-2], True, False))
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            runs.append((part[1:-1], False, True))
        elif part.startswith("`") and part.endswith("`"):
            runs.append((part[1:-1], False, False))
        else:
            runs.append((part, False, False))
    return runs


def plain(text: str) -> str:
    """Inline Markdown stripped to plain text."""
    return "".join(t for t, _, _ in inline_runs(text))
