# Stage 3 Instructions: File Creation Tools

> **Paste this into Claude Code** in the `Gopi_bot` project folder. It builds on `gopi-voice-bot-architecture.md`, `CLAUDE.md`, `STAGE-1-BUILD-INSTRUCTIONS.md`, and `STAGE-2-TOOL-CALLING-LAYER.md`. If those files are present, follow them too. If they conflict, this file wins for Stage 3.

| Item | Value |
|---|---|
| Project | Gopi's speech-to-speech voice bot |
| Voice model | OpenAI Realtime API, `gpt-realtime-2.1-mini` (about $0.20 per 15 min) |
| This stage | **Stage 3 of 5: file creation** |
| Timebox | **~10 min (0:25–0:35 of the one-hour build)** |
| Machine | Gopi's Windows PC (cross-platform code, tested on Windows first) |
| End goal | A bot like Grok Bot, Codex, or ChatGPT that can access anything and do whatever Gopi asks, including producing real documents on request |

---

## 0. Project workflow so far

| Stage | Status | What it gives Stage 3 |
|---|---|---|
| 1. Realtime 2.1 mini voice session | Built | Mic in, speaker out, server voice activity detection, barge-in |
| 2. Tool-calling layer + computer access | Built | `@tool` registry, `dispatch()` (thread + timeout + errors + truncation + `bot.log`), `safety.py` confirmation, `run_shell`, `read_file`, `write_file`, `list_dir`, `open_app`, `tools_cli.py` |
| **3. File creation** | **This stage** | New tools plug into the Stage 2 registry. **No changes to the voice loop.** |
| 4. Web search | Next | Research results become reports via Stage 3 tools |
| 5. End-to-end test | Last | "Research X, save a Word report, open it" |

**API key:** Gopi adds `OPENAI_API_KEY` to `.env` himself. Don't block on it. Everything in this stage must build and test without it.

---

## 1. What you're building

A **file-creation module** (`bot/tools/files.py`) registered through the existing Stage 2 registry, so the model can create real documents by voice:

1. `create_document`: one tool that creates **Markdown, PDF, Word (.docx), CSV**, plus **txt, json, html**, and **xlsx** (if time allows).
2. A small **Markdown-to-blocks parser** (`bot/tools/md_blocks.py`) shared by the Word and PDF writers, so the model writes content once, in Markdown, for any format.
3. **Naming, location, and overwrite rules**, so files land in predictable places and never clobber anything silently.
4. **A clear result** (absolute path, size, format) so the model can tell Gopi exactly where the file is and offer to open it with `open_app`.

---

## 2. Architecture flow

```
Gopi: "Make a Word doc on my desktop with my three goals for this week."
   │  audio ──► Realtime model (hears + understands)
   ▼
function call: create_document {
  format: "docx", filename: "weekly goals", folder: "desktop",
  title: "Weekly Goals", content: "- Ship the voice bot\n- ...\n"
}
   │
   ▼
dispatcher.dispatch()  (Stage 2: thread, timeout, errors, log, safety)
   │
   ▼
files.create_document()
   ├─ resolve folder ("desktop" → C:\Users\<user>\Desktop, or OneDrive\Desktop)
   ├─ build safe filename ("weekly-goals.docx")
   ├─ exists? → auto-suffix "-1", or needs_confirmation if overwrite=true
   ├─ parse Markdown → blocks → python-docx writer
   └─ return {"ok": true, "path": "C:\\...\\Desktop\\weekly-goals.docx", "format": "docx", "bytes": 36712}
   │
   ▼
function_call_output ──► response.create
   ▼
Model (spoken): "Done. Weekly goals is saved on your desktop as a Word doc. Want me to open it?"
   │  "yes" ──► open_app(path)
```

---

## 3. Files to create or modify

```
bot/tools/
├── files.py        # NEW: create_document + writers
├── md_blocks.py    # NEW: tiny Markdown → blocks parser
├── paths.py        # NEW (or extend Stage 2 helpers): folder aliases + safe filenames
└── __init__.py     # MODIFY: import files so its tools register
bot/prompts.py      # MODIFY: add file-creation rules
tests/test_files.py # NEW
requirements.txt    # ADD: python-docx, fpdf2 (openpyxl if doing xlsx)
.env / .env.example # ADD: OUTPUT_DIR=./output
```

---

## 4. Tool spec: `create_document`

**Description for the model:** *"Create a file on Gopi's computer: Markdown, PDF, Word (docx), CSV, Excel (xlsx), txt, json, or html. Write the content in Markdown for md/docx/pdf/txt, CSV text or a JSON array of rows for csv/xlsx, and raw content for json/html. Returns the saved file's full path."*

| Param | Type | Required | Notes |
|---|---|---|---|
| `format` | enum: `md`, `pdf`, `docx`, `csv`, `xlsx`, `txt`, `json`, `html` | yes | Also accept `word`→`docx`, `markdown`→`md`, `excel`→`xlsx` |
| `filename` | string | yes | Human name, like `"weekly goals"`. The extension is added and fixed automatically |
| `content` | string | yes | See the format rules below |
| `title` | string | no | Heading at the top (md, docx, pdf, html), or the sheet name for xlsx |
| `folder` | string | no | Alias (`desktop`, `documents`, `downloads`, `output`) or any path. Default `OUTPUT_DIR` |
| `overwrite` | bool | no | Default false. True replaces an existing file, which is **destructive** |
| `confirmed` | bool | no | Required with `overwrite=true` when `CONFIRM_DESTRUCTIVE=true` |

**Returns** (JSON string): `{ok, path, filename, folder, format, bytes, created_at}`, or `{ok: false, error}`, or `{ok: false, needs_confirmation: true, action, path}`.

---

## 5. Format rules (writers in `files.py`)

| Format | Library | Rules |
|---|---|---|
| **md** | stdlib | Write as-is. If `title` is given and content doesn't start with `#`, prepend `# {title}`. UTF-8 |
| **txt** | stdlib | Strip Markdown symbols lightly (`#`, `**`), keep line breaks. UTF-8 |
| **json** | stdlib | `json.loads(content)` to validate, then pretty-print with indent 2. Invalid JSON returns `err` with the parse error |
| **html** | stdlib | If content has `<html`, write as-is. Otherwise convert blocks to simple HTML with basic CSS |
| **csv** | stdlib `csv` | Accept CSV text **or** a JSON array (list of lists, or list of dicts with dict keys as the header). Write with **`encoding="utf-8-sig"`** so Excel on Windows opens it correctly, and `newline=""` |
| **docx** | `python-docx` | Blocks: `#`/`##`/`###` become headings 1–3, `- `/`* ` become List Bullet, `1. ` becomes List Number, `**bold**` and `*italic*` become runs, Markdown tables become Word tables (style "Table Grid"), fenced code uses a monospace font, and blank lines separate paragraphs. `title` becomes the Title style |
| **pdf** | `fpdf2` | Same blocks. A4/Letter, 20 mm margins, auto page breaks. Headings are bold at 18/15/13 pt and body is 11 pt. **Unicode:** load a TTF font. On Windows try `C:\Windows\Fonts\segoeui.ttf`, then `arial.ttf`, then fall back to core Helvetica, replacing unsupported characters. Render tables as simple bordered cells (or monospace text if short on time) |
| **xlsx** *(if time)* | `openpyxl` | Same input as csv. Bold header row, auto column widths, freeze the top row |

**Anything else asked for** (pptx, a Python script, a .bat, an .ics, and so on): the model uses Stage 2 `write_file` for text formats, or `run_shell` with a short Python one-liner for others. Mention this in the prompt. Dedicated pptx/image tools are Later.

---

## 6. Markdown-to-blocks parser (`md_blocks.py`)

Keep it tiny (about 60 lines), with no external Markdown library:

```python
Block = dict  # {"type": "heading", "level": 1-3, "text": ...}
              # {"type": "paragraph", "text": ...}
              # {"type": "bullet", "text": ...} / {"type": "numbered", "text": ...}
              # {"type": "table", "rows": [[...], ...]}
              # {"type": "code", "text": ...}
def parse(md: str) -> list[Block]: ...
def inline_runs(text: str) -> list[tuple[str, bool, bool]]:  # (text, bold, italic)
```

Both the docx and PDF writers consume `parse()`, so formatting stays consistent.

---

## 7. Naming, location, and overwrite rules (`paths.py`)

**Folder aliases** (case-insensitive):
- `desktop` becomes `~/Desktop`, or `~/OneDrive/Desktop` if that's the real one on Windows (check which exists).
- `documents`/`docs` becomes `~/Documents` (with the same OneDrive check), `downloads` becomes `~/Downloads`, and `output`/unspecified becomes `OUTPUT_DIR` (default `./output`, created if missing).
- Any other value is treated as a path: expand `~` and env vars, and create missing folders.

**Filename convention:**
- Slugify: lowercase, spaces become `-`, strip `\/:*?"<>|` and other unsafe characters, collapse repeated dashes, and cap at 80 characters. `"Weekly Goals!"` becomes `weekly-goals`.
- Force the correct extension (`report.doc` with format docx becomes `report.docx`).
- If no meaningful name is given, use `document-YYYY-MM-DD-HHMM`.
- Avoid Windows reserved names (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`9`, `LPT1`–`9`) by appending `-file`.

**Overwrite rules:**
- Default: **never overwrite**. If `weekly-goals.docx` exists, save as `weekly-goals-1.docx`, `-2`, and so on, and return the actual path.
- `overwrite=true` goes through the Stage 2 safety check. It returns `needs_confirmation` until Gopi says yes, and the model then retries with `confirmed=true`.
- If the target file is open in Word or Excel on Windows, the write raises a `PermissionError`. Return `err("File is open in another program. Close it and try again, or save under a new name.")`.

**Always return the absolute path** so the model can say where the file is and pass it straight to `open_app`.

---

## 8. System prompt additions (`bot/prompts.py`)

```
FILES
You can create files with create_document (md, pdf, docx, csv, xlsx, txt, json, html).
- When Gopi asks for a document, write the full content yourself in Markdown
  (or CSV / JSON rows for spreadsheets) and call create_document. Don't ask him to dictate it.
- "Word" means docx, "spreadsheet" means csv (or xlsx if available), and "PDF" means pdf.
- If he names a place ("on my desktop", "in documents"), pass it as folder. Otherwise
  use the default output folder.
- After saving, say the file name and where it is in one short sentence (say
  "on your desktop", not the full path), then ask "Want me to open it?" If yes,
  call open_app with the returned path.
- Never overwrite a file unless he asks. If he does, call with overwrite=true and
  follow the confirmation rule.
- For formats create_document doesn't support, use write_file (text formats) or run_shell.
```

---

## 9. Tests (`tests/test_files.py`)

Use `tmp_path` as the folder in every test:
- One test per format (md, txt, json, html, csv, docx, pdf): the file exists, `bytes > 0`, and the returned path is absolute with the right extension.
- **docx:** reopen with `python-docx`, and assert the heading text and a bullet paragraph exist.
- **pdf:** file starts with `%PDF`. Non-ASCII text (for example `café, naïve, ₹`) doesn't crash.
- **csv:** JSON list-of-dicts input produces the right header, the file starts with a UTF-8 BOM, and it round-trips through `csv.reader`.
- **json:** invalid JSON returns `ok: false`.
- **Naming:** `"Weekly Goals!"` becomes `weekly-goals.docx`, a second create becomes `weekly-goals-1.docx`, and reserved names get fixed.
- **Overwrite:** `overwrite=true` without `confirmed` returns `needs_confirmation` and leaves the file untouched. With `confirmed=true` it replaces the file.
- **Aliases:** `folder="output"` resolves to `OUTPUT_DIR` (monkeypatch the env).
- Also check `python tools_cli.py create_document "{\"format\":\"docx\",\"filename\":\"cli test\",\"content\":\"# Hi\\n- one\\n- two\"}"`.

Run `pytest -q`. All tests (Stage 2 + Stage 3) must pass **without** `OPENAI_API_KEY`.

---

## 10. Step-by-step order (fits ~10 min)

1. `paths.py`: aliases, slugify, unique-name, reserved names (2 min)
2. `files.py`: md, txt, json, html, csv writers and `create_document` registration (2 min)
3. `md_blocks.py` + docx writer (2 min)
4. PDF writer with the Windows TTF font fallback (2 min)
5. Prompt additions, tests, `pytest -q`, CLI check (2 min)
6. *(If time)* xlsx via openpyxl

**If over budget, cut scope, never testing:** ship md + csv first, then docx, then PDF with plain paragraphs (no tables). Drop xlsx and HTML conversion. Log anything dropped in `TODO.md`.

---

## 11. Done when

**Without the API key:**
- [ ] `pytest -q` passes (Stages 2 + 3)
- [ ] The CLI creates a `.docx` in `./output` that opens in Word with a heading and bullets
- [ ] A PDF with a heading, paragraphs, and bullets opens correctly
- [ ] A CSV opens in Excel with correct columns and no garbled characters
- [ ] A second create with the same name gets `-1`, and overwrite asks first
- [ ] `bot.log` shows each `create_document` call

**Once Gopi adds the key (voice test):**
- [ ] "Make a Word doc on my desktop with three goals for this week": it's created on the desktop, the bot says where, and offers to open it
- [ ] "Yes, open it" opens it in Word
- [ ] "Turn that into a PDF too" creates the PDF alongside it
- [ ] "Make a spreadsheet of five countries and their capitals" creates a CSV that opens in Excel
- [ ] "Overwrite the goals doc with just one goal" asks first, and replaces it only after "yes"

Stop after this and tell Gopi how to run the checks. **Don't start Stage 4.**

---

## 12. Worth adding now (small, high-value)

- **Consistent naming** (slugified, correct extension, no reserved names) so files are easy to find later.
- **Never silently overwrite:** auto-suffix by default, and require confirmation for an explicit overwrite.
- **Always return the absolute path.** The model says it simply and can open the file right away.
- **Friendly "file is open" error** for Windows locks.
- **Last-created-file memory:** keep the most recent path in memory, so "open it", "convert that to PDF", or "add a line to it" works without restating the name.
- **UTF-8 BOM for CSV** so Excel on Windows shows the characters correctly.

## 13. Later (not Stage 3)

PowerPoint (`python-pptx`), images and charts (`matplotlib`), editing existing Word/PDF files, `convert_file` between formats (for example via pandoc or LibreOffice), templates and letterheads, and saving directly to Google Drive or OneDrive.
