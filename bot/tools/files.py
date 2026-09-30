"""create_document: md, pdf, docx, csv, xlsx, txt, json, html.

The model writes content once, in Markdown (or rows for csv/xlsx); the
md_blocks parser feeds the docx, pdf, html, and txt writers so formatting
stays consistent. Overwrite confirmation happens in the dispatcher via
safety.py; `confirmed` is accepted here only so the schema can carry it.
"""
import csv
import html
import io
import json
import logging
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from bot.tools import md_blocks
from bot.tools.base import CONFIRMED_PARAM, err, ok, tool
from bot.tools.paths import EXTENSIONS, normalize_format, resolve_folder, slugify, unique_path

# fpdf2's font subsetter warns about harmless Segoe UI tables ("MERG NOT subset").
logging.getLogger("fontTools").setLevel(logging.ERROR)

# ---- shared helpers -------------------------------------------------------------


def _with_title(blocks: list[dict], title: str | None) -> list[dict]:
    """Drop a leading H1 that just repeats the title."""
    if title and blocks and blocks[0]["type"] == "heading" and blocks[0]["level"] == 1:
        if md_blocks.plain(blocks[0]["text"]).strip().lower() == title.strip().lower():
            return blocks[1:]
    return blocks


def _rows(content: str) -> list[list[str]]:
    """JSON array (of lists or dicts), a Markdown table, or CSV text -> rows."""
    text = content.strip()
    if text.startswith("["):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, list):
            if data and all(isinstance(r, dict) for r in data):
                header: list[str] = []
                for r in data:
                    header += [k for k in r if k not in header]
                return [header] + [[_cell(r.get(k, "")) for k in header] for r in data]
            return [[_cell(c) for c in (r if isinstance(r, list) else [r])] for r in data]
    if text.startswith("|"):
        tables = [b for b in md_blocks.parse(text) if b["type"] == "table"]
        if tables:
            return tables[0]["rows"]
    return [row for row in csv.reader(io.StringIO(text)) if row]


def _cell(value) -> str:
    return "" if value is None else str(value)


# ---- text-like writers ---------------------------------------------------------


def _write_md(path: Path, content: str, title: str | None) -> None:
    text = content
    if title and not content.lstrip().startswith("#"):
        text = f"# {title}\n\n{content}"
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def _write_txt(path: Path, content: str, title: str | None) -> None:
    lines = []
    if title:
        lines += [title, ""]
    for line in content.replace("\r\n", "\n").split("\n"):
        line = re.sub(r"^\s{0,3}#{1,6}\s+", "", line)
        lines.append(line.replace("**", "").replace("__", ""))
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_json(path: Path, content: str, title: str | None) -> None:
    data = json.loads(content)  # JSONDecodeError is reported by create_document
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _html_inline(text: str) -> str:
    out = []
    for t, bold, italic in md_blocks.inline_runs(text):
        t = html.escape(t)
        if bold:
            t = f"<strong>{t}</strong>"
        if italic:
            t = f"<em>{t}</em>"
        out.append(t)
    return "".join(out)


def _write_html(path: Path, content: str, title: str | None) -> None:
    if "<html" in content.lower():
        path.write_text(content, encoding="utf-8")
        return
    body: list[str] = []
    if title:
        body.append(f"<h1>{html.escape(title)}</h1>")
    open_list = None
    for b in _with_title(md_blocks.parse(content), title):
        tag = {"bullet": "ul", "numbered": "ol"}.get(b["type"])
        if open_list and tag != open_list:
            body.append(f"</{open_list}>")
            open_list = None
        if tag and not open_list:
            body.append(f"<{tag}>")
            open_list = tag
        if tag:
            body.append(f"<li>{_html_inline(b['text'])}</li>")
        elif b["type"] == "heading":
            body.append(f"<h{b['level']}>{_html_inline(b['text'])}</h{b['level']}>")
        elif b["type"] == "paragraph":
            body.append(f"<p>{_html_inline(b['text'])}</p>")
        elif b["type"] == "code":
            body.append(f"<pre><code>{html.escape(b['text'])}</code></pre>")
        elif b["type"] == "table":
            rows = b["rows"]
            head = "".join(f"<th>{_html_inline(c)}</th>" for c in rows[0]) if rows else ""
            rest = "".join(
                "<tr>" + "".join(f"<td>{_html_inline(c)}</td>" for c in r) + "</tr>" for r in rows[1:]
            )
            body.append(f"<table><thead><tr>{head}</tr></thead><tbody>{rest}</tbody></table>")
    if open_list:
        body.append(f"</{open_list}>")
    page = (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<title>{html.escape(title or path.stem)}</title>"
        "<style>body{font-family:system-ui,Segoe UI,sans-serif;max-width:760px;margin:2rem auto;"
        "padding:0 1rem;line-height:1.55;color:#222}table{border-collapse:collapse}"
        "th,td{border:1px solid #ccc;padding:.35rem .6rem}th{background:#f3f3f3}"
        "pre{background:#f5f5f5;padding:.8rem;overflow:auto}</style></head><body>\n"
        + "\n".join(body)
        + "\n</body></html>\n"
    )
    path.write_text(page, encoding="utf-8")


# ---- spreadsheets --------------------------------------------------------------


def _write_csv(path: Path, content: str, title: str | None) -> None:
    # utf-8-sig adds a BOM so Excel on Windows shows non-ASCII characters correctly.
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows(_rows(content))


def _number(value: str):
    """Let Excel see numbers as numbers."""
    if re.fullmatch(r"-?\d{1,15}", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    return value


def _write_xlsx(path: Path, content: str, title: str | None) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    rows = _rows(content)
    wb = Workbook()
    ws = wb.active
    ws.title = (re.sub(r"[\[\]:*?/\\]", "", title or "") or "Sheet1")[:31]
    for r_idx, row in enumerate(rows):
        ws.append(row if r_idx == 0 else [_number(c) for c in row])
    if rows:
        for cell in ws[1]:
            cell.font = Font(bold=True)
        ws.freeze_panes = "A2"
        for col in ws.columns:
            width = max(len(str(c.value or "")) for c in col)
            ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 60)
    wb.save(path)


# ---- Word ----------------------------------------------------------------------


def _write_docx(path: Path, content: str, title: str | None) -> None:
    from docx import Document
    from docx.shared import Pt

    doc = Document()
    if title:
        doc.add_heading(title, level=0)

    def add_runs(paragraph, text: str) -> None:
        for t, bold, italic in md_blocks.inline_runs(text):
            run = paragraph.add_run(t)
            run.bold, run.italic = bold or None, italic or None

    for b in _with_title(md_blocks.parse(content), title):
        kind = b["type"]
        if kind == "heading":
            add_runs(doc.add_heading(level=b["level"]), b["text"])
        elif kind == "bullet":
            add_runs(doc.add_paragraph(style="List Bullet"), b["text"])
        elif kind == "numbered":
            add_runs(doc.add_paragraph(style="List Number"), b["text"])
        elif kind == "paragraph":
            add_runs(doc.add_paragraph(), b["text"])
        elif kind == "code":
            run = doc.add_paragraph().add_run(b["text"])
            run.font.name, run.font.size = "Consolas", Pt(9)
        elif kind == "table" and b["rows"]:
            rows = b["rows"]
            ncols = max(len(r) for r in rows)
            table = doc.add_table(rows=len(rows), cols=ncols)
            table.style = "Table Grid"
            for r_idx, row in enumerate(rows):
                for c_idx in range(ncols):
                    cell = table.cell(r_idx, c_idx)
                    cell.text = ""
                    para = cell.paragraphs[0]
                    add_runs(para, row[c_idx] if c_idx < len(row) else "")
                    if r_idx == 0:
                        for run in para.runs:
                            run.bold = True
    doc.save(path)


# ---- PDF -----------------------------------------------------------------------

_WIN_FONTS = Path("C:/Windows/Fonts")
# (regular, bold, italic, bold-italic) candidates, best first.
_TTF_FAMILIES = [
    ("segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "segoeuiz.ttf"),
    ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
]
_LINUX_MAC_FONTS = [
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/Library/Fonts/Arial Unicode.ttf"),
]


def _setup_pdf_font(pdf) -> tuple[str, Callable[[str], str]]:
    """Register a Unicode TTF if one exists; else core Helvetica with lossy text."""
    for family in _TTF_FAMILIES:
        files = [_WIN_FONTS / f for f in family]
        if files[0].exists():
            for style, f in zip(("", "B", "I", "BI"), files):
                pdf.add_font("Body", style, str(f if f.exists() else files[0]))
            return "Body", lambda s: s
    for f in _LINUX_MAC_FONTS:
        if f.exists():
            for style in ("", "B", "I", "BI"):
                pdf.add_font("Body", style, str(f))
            return "Body", lambda s: s
    to_latin1 = lambda s: s.replace("\u2022", "-").encode("latin-1", "replace").decode("latin-1")  # noqa: E731
    return "helvetica", to_latin1


def _write_pdf(path: Path, content: str, title: str | None) -> None:
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    pdf.set_margins(20, 20, 20)
    pdf.set_auto_page_break(True, margin=20)
    pdf.add_page()
    family, clean = _setup_pdf_font(pdf)
    unicode_font = family == "Body"
    bullet = "\u2022" if unicode_font else "-"
    body_size, line_h = 11, 6

    def rich(text: str, size: int = body_size, force_bold: bool = False, indent: float = 0) -> None:
        left = pdf.l_margin
        if indent:
            pdf.set_left_margin(left + indent)
            pdf.set_x(left + indent)
        for t, bold, italic in md_blocks.inline_runs(text):
            style = ("B" if bold or force_bold else "") + ("I" if italic else "")
            pdf.set_font(family, style, size)
            pdf.write(size * 0.5 + 0.5, clean(t))
        pdf.ln(size * 0.5 + 0.5)
        pdf.set_left_margin(left)

    if title:
        pdf.set_font(family, "B", 20)
        pdf.multi_cell(0, 10, clean(title), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

    sizes = {1: 18, 2: 15, 3: 13}
    number = 0  # running count for consecutive numbered items
    for b in _with_title(md_blocks.parse(content), title):
        kind = b["type"]
        number = number + 1 if kind == "numbered" else 0
        if kind == "heading":
            pdf.ln(2)
            rich(b["text"], sizes[b["level"]], force_bold=True)
            pdf.ln(1)
        elif kind == "paragraph":
            rich(b["text"])
            pdf.ln(2)
        elif kind in ("bullet", "numbered"):
            pdf.set_font(family, "", body_size)
            marker = bullet if kind == "bullet" else f"{number}."
            pdf.cell(7, line_h, clean(marker))
            rich(b["text"], indent=7)
            pdf.ln(0.5)
        elif kind == "code":
            if unicode_font:
                pdf.set_font(family, "", 9)
                text = b["text"]
            else:
                pdf.set_font("courier", "", 9)
                text = clean(b["text"])
            pdf.set_fill_color(242, 242, 242)
            pdf.multi_cell(0, 5, text, fill=True, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
        elif kind == "table" and b["rows"]:
            pdf.ln(2)
            pdf.set_font(family, "", 10)
            ncols = max(len(r) for r in b["rows"])
            with pdf.table(first_row_as_headings=True) as table:
                for row in b["rows"]:
                    r = table.row()
                    for c_idx in range(ncols):
                        r.cell(clean(md_blocks.plain(row[c_idx])) if c_idx < len(row) else "")
            pdf.ln(3)
    pdf.output(str(path))


# ---- the tool --------------------------------------------------------------------

_WRITERS: dict[str, Callable[[Path, str, str | None], None]] = {
    "md": _write_md, "txt": _write_txt, "json": _write_json, "html": _write_html,
    "csv": _write_csv, "xlsx": _write_xlsx, "docx": _write_docx, "pdf": _write_pdf,
}

@tool(
    "create_document",
    "Create a file on Gopi's computer: Markdown (md), PDF, Word (docx), CSV, Excel (xlsx), "
    "txt, json, or html. Write the full content yourself. Use Markdown for md/docx/pdf/txt/html "
    "(# headings, - bullets, 1. numbered, **bold**, | tables |); CSV text or a JSON array of "
    "rows/objects for csv/xlsx; raw JSON for json. folder can be 'desktop', 'documents', "
    "'downloads', or any path (default: the output folder). Never overwrites: an existing name "
    "gets -1, -2. Returns the saved file's full path; pass it to open_app to open it.",
    {
        "type": "object",
        "properties": {
            "format": {"type": "string", "enum": sorted(EXTENSIONS)},
            "filename": {"type": "string", "description": "Human name, e.g. 'weekly goals'. Extension is added."},
            "content": {"type": "string", "description": "The document body (see description)."},
            "title": {"type": "string", "description": "Heading at the top, or the sheet name for xlsx."},
            "folder": {"type": "string", "description": "'desktop', 'documents', 'downloads', 'output', or a path."},
            "overwrite": {"type": "boolean", "description": "Replace an existing file. Needs Gopi's confirmation."},
            "confirmed": CONFIRMED_PARAM,
        },
        "required": ["format", "filename", "content"],
    },
)
def create_document(
    format: str,
    filename: str,
    content: str,
    title: str | None = None,
    folder: str | None = None,
    overwrite: bool = False,
    confirmed: bool = False,
) -> str:
    try:
        fmt = normalize_format(format)
        if fmt is None:
            return err(
                f"unsupported format {format!r}; use one of {sorted(EXTENSIONS)}. "
                "For other formats use write_file or run_shell."
            )
        target_dir = resolve_folder(folder)
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"{slugify(filename)}.{fmt}"
        if not overwrite:
            path = unique_path(path)
        try:
            _WRITERS[fmt](path, content or "", title)
        except json.JSONDecodeError as e:
            return err(f"content is not valid JSON: {e}")
        except PermissionError:
            return err(
                "File is open in another program. Close it and try again, or save under a new name.",
                path=str(path),
            )
        saved = path.resolve()
        return ok(
            path=str(saved),
            filename=path.name,
            folder=str(saved.parent),
            format=fmt,
            bytes=path.stat().st_size,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
    except Exception as e:
        return err(f"{type(e).__name__}: {e}")

