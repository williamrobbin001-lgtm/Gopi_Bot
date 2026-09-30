# Stage 1 Build Instructions: Gopi's Speech-to-Speech Voice Bot

> **How to use this file:** Paste the whole file into Claude Code in an empty project folder (with `CLAUDE.md` saved in the same folder). Then say: *"Build Stage 1 following these instructions, one step at a time. Stop after each step so I can test it."*

---

## 0. What we're building

A voice assistant that runs on Gopi's own computer. Gopi talks, it talks back in real time, and it can **do things**: run commands, read and write files, open apps, create documents (Markdown, PDF, Word, CSV), and research the web. It should feel like a Perplexity voice agent, Grok Bot, or a Codex voice agent. It can access anything on the machine and does what Gopi says.

| Item | Decision |
|---|---|
| Voice model | OpenAI Realtime API, `gpt-realtime-2.1-mini` (speech-to-speech, about $0.20 per 15 min) |
| Language | Python 3.11+ |
| Transport | WebSocket to the Realtime API, from a local Python process |
| Audio | `sounddevice`, 24 kHz, mono, PCM16 |
| Search | Tavily API (fallback: Brave Search API) |
| Scraping | `httpx` + `trafilatura` (fallback: `beautifulsoup4`) |
| Word | `python-docx` |
| PDF | `fpdf2` (pure Python, no system dependencies) |
| Build window | **1 hour. Stage 1 = v1 only.** |

---

## 1. Architecture

```
            ┌──────────────────────────── Gopi's computer ────────────────────────────┐
 Mic ──►    │  audio_io.py ──► realtime_client.py ◄──── WebSocket ────► OpenAI Realtime│
 Speaker ◄─ │       ▲                 │                                  (2.1 mini)   │
            │       └── playback ◄────┤                                               │
            │                         ▼                                               │
            │                   dispatcher.py ──► tools/computer.py  (shell, files, apps)
            │                         │       ──► tools/files.py     (md, csv, docx, pdf)
            │                         │       ──► tools/research.py  (search, open, scrape)
            │                         ▼                                               │
            │                      bot.log                                            │
            └─────────────────────────────────────────────────────────────────────────┘
```

**Four layers:**
1. **Realtime voice layer** (`audio_io.py`, `realtime_client.py`): mic in, speaker out, turn detection, barge-in.
2. **Tool layer** (`tools/`): plain Python functions with JSON schemas.
3. **Search backend** (`tools/research.py`): web search, open URL, scrape page.
4. **Agent loop** (`dispatcher.py` + event handling in `realtime_client.py`): tool call → execute → return result → model continues.

---

## 2. The workflow (one turn)

1. Gopi speaks. Mic audio streams to the API as base64 PCM16 via `input_audio_buffer.append`.
2. Server voice activity detection notices the end of speech, and the model responds.
3. **If it only needs to talk:** the client receives audio deltas and plays them.
4. **If it needs a tool:** the client receives a completed function call (`name`, `call_id`, JSON `arguments`).
5. The dispatcher runs the tool **in a worker thread** (never block the audio loop) with a timeout, and truncates the output.
6. The client sends `conversation.item.create` with `{type: "function_call_output", call_id, output}`, then `response.create`.
7. The model either calls another tool (chaining) or speaks the answer.
8. **Barge-in:** if Gopi starts talking (`input_audio_buffer.speech_started`), stop playback immediately, clear the playback queue, and send `response.cancel`.

> ⚠️ **Verify event names against the current OpenAI Realtime docs before coding.** Names like `response.output_audio.delta` vs `response.audio.delta` have changed between versions. Log every unknown event type at DEBUG level so mismatches are obvious.

---

## 3. Project layout

```
voice-bot/
├── CLAUDE.md
├── STAGE-1-BUILD-INSTRUCTIONS.md
├── .env.example
├── .gitignore              # includes .env, output/, bot.log
├── requirements.txt
├── main.py                 # entry point: python main.py
├── bot/
│   ├── __init__.py
│   ├── config.py           # loads .env, constants
│   ├── prompts.py          # system prompt
│   ├── audio_io.py         # mic capture + speaker playback
│   ├── realtime_client.py  # WebSocket session + event loop
│   ├── dispatcher.py       # tool registry, execution, truncation, logging
│   └── tools/
│       ├── __init__.py     # collects TOOLS (schemas) and HANDLERS (functions)
│       ├── computer.py
│       ├── files.py
│       └── research.py
├── output/                 # default folder for created files
└── tests/
    └── test_tools.py
```

**`.env.example`**
```
OPENAI_API_KEY=
REALTIME_MODEL=gpt-realtime-2.1-mini
REALTIME_VOICE=marin
TAVILY_API_KEY=
BRAVE_API_KEY=
OUTPUT_DIR=./output
CONFIRM_DESTRUCTIVE=true
TOOL_TIMEOUT_SECONDS=60
MAX_TOOL_OUTPUT_CHARS=8000
LOG_LEVEL=INFO
```

**`requirements.txt`**
```
websockets>=12
sounddevice
numpy
python-dotenv
httpx
trafilatura
beautifulsoup4
python-docx
fpdf2
pytest
```

---

## 4. Tool specifications

Every tool is a Python function that returns a **string** (JSON-encoded if structured). Each has a JSON schema registered with the session. All tools must catch their own exceptions and return `{"ok": false, "error": "..."}` rather than raising.

### 4.1 Computer access (`tools/computer.py`)

| Tool | Args | Behavior |
|---|---|---|
| `run_shell` | `command: str`, `cwd?: str`, `confirmed?: bool` | Runs via `subprocess.run(shell=True, capture_output=True, text=True, timeout=TOOL_TIMEOUT_SECONDS)`. Uses PowerShell on Windows. Returns `{ok, exit_code, stdout, stderr}`. |
| `read_file` | `path: str`, `max_chars?: int` | Reads text (UTF-8, errors="replace"). Expands `~`. Returns content, truncated. |
| `write_file` | `path: str`, `content: str`, `append?: bool`, `confirmed?: bool` | Creates parent dirs. Overwriting an existing file counts as destructive. Returns `{ok, path, bytes}`. |
| `list_dir` | `path: str`, `show_hidden?: bool` | Returns up to 200 entries with name, type (file/dir), size, and modified time. |
| `open_app` | `target: str` | Opens an app, file, folder, or URL. macOS: `open` (or `open -a "<App>"` for app names). Windows: `os.startfile` / `start`. Linux: `xdg-open`. |

**Destructive-action guardrail** (only when `CONFIRM_DESTRUCTIVE=true`):
- Treat as destructive: `rm`, `rmdir`, `del`, `Remove-Item`, `mv` onto existing paths, `format`, `mkfs`, `dd`, `shutdown`, `reboot`, `kill`, `chmod -R`, `sudo`, `git push --force`, `git reset --hard`, and overwriting an existing file.
- If destructive and `confirmed` is not true, **do not execute**. Return `{"ok": false, "needs_confirmation": true, "action": "<plain description>"}`.
- The system prompt tells the model to ask Gopi aloud, and only after a clear "yes" to call the tool again with `confirmed: true`.

### 4.2 File creation (`tools/files.py`)

| Tool | Args | Behavior |
|---|---|---|
| `create_document` | `format: "md"\|"pdf"\|"docx"\|"csv"\|"txt"\|"json"\|"html"`, `filename: str`, `content: str`, `title?: str`, `folder?: str` | Writes to `folder` or `OUTPUT_DIR`. Returns `{ok, path}`. |

Format rules:
- **md, txt, json, html:** write `content` as-is (prepend `# {title}` for md if a title is given).
- **csv:** `content` is CSV text **or** a JSON array of rows/objects. Normalize with the `csv` module.
- **docx:** parse simple Markdown from `content`. `#`, `##`, and `###` become headings, `- ` becomes bullets, `1. ` becomes a numbered list, a blank line starts a new paragraph, and `**bold**` becomes bold runs.
- **pdf:** same simple Markdown parsing, rendered with `fpdf2` (Helvetica, auto page breaks, headings larger and bold). Use a Unicode TTF font if available, and otherwise replace unsupported characters.
- Never overwrite silently. If the file exists, append `-1`, `-2`, and so on.
- After creating, the model should say where it saved the file and offer to open it (via `open_app`).

### 4.3 Research (`tools/research.py`)

| Tool | Args | Behavior |
|---|---|---|
| `web_search` | `query: str`, `max_results?: int = 5` | Tavily `POST https://api.tavily.com/search`. Falls back to Brave if Tavily has no key or errors. Returns `[{title, url, snippet}]`. |
| `scrape_page` | `url: str`, `max_chars?: int = 8000` | `httpx.get` (follow redirects, 20 s timeout, browser-like User-Agent), then `trafilatura.extract`. Falls back to BeautifulSoup text. Returns `{ok, url, title, text}`, truncated. |
| `open_url` | `url: str` | Opens the URL in the default browser (`webbrowser.open`). Use when Gopi wants to *see* the page. |

**Research behavior (system prompt):** for a question, run `web_search`, scrape the two or three best results, give a short spoken answer that names the sources, and offer to save a full report with `create_document`.

---

## 5. System prompt (`bot/prompts.py`)

```
You are Gopi's personal voice assistant running on his computer. You can run
shell commands, read and write files, list folders, open apps and URLs, create
documents (Markdown, PDF, Word, CSV and more), search the web, and read pages.

- When Gopi asks you to do something, do it with your tools. Don't just explain how.
- Speak briefly: one to three sentences unless he asks for detail. Never read
  long file contents, code, or URLs aloud; summarize them.
- Before a tool that may take more than a couple of seconds, say a short
  phrase like "On it" or "Searching now".
- Chain tools as needed until the task is done, then say what you did and
  where any file was saved.
- If a tool returns needs_confirmation, describe the action in plain words and
  ask "Should I go ahead?" Only call it again with confirmed=true after a clear yes.
- If a tool fails, say what failed in one sentence and try a sensible alternative.
- For research, search, read the two or three best sources, answer briefly,
  name the sources, and offer to save a full report.
- Default save folder is the output folder unless Gopi names a location
  (for example "my desktop" means ~/Desktop).
```

---

## 6. Step-by-step build (the one-hour window)

All five steps are **v1**. Build them in order and stop after each one so Gopi can test it.

### Timebox (60 minutes total)

| Step | Budget | Clock | If it runs over, cut this scope (never the test) |
|---|---|---|---|
| 1. Realtime 2.1 mini voice session | ~10 min | 0:00–0:10 | Skip barge-in polish, and just stop playback on `speech_started` |
| 2. Tool-calling layer for computer access | ~15 min | 0:10–0:25 | Ship `run_shell`, `read_file`, `list_dir` first, and add `write_file` and `open_app` if time allows |
| 3. File creation (md, pdf, docx, csv) | ~10 min | 0:25–0:35 | Ship md and csv first, then docx, then pdf with plain paragraphs only |
| 4. Web search | ~10 min | 0:35–0:45 | Ship Tavily `web_search` + `scrape_page` only, and drop the Brave fallback and `open_url` |
| 5. End-to-end test | ~15 min | 0:45–1:00 | **Protected.** Never shortened or skipped |

**Overrun rule:** check the clock at the end of each step. If a step blows its budget, **cut scope** using the column above, note what was dropped in a `TODO.md`, and move on. **Never skip or shorten Step 5 testing.** An untested feature doesn't count as done. If the whole build is running late, drop features from Steps 3 and 4 before touching the test time.

### Step 1: Stand up the Realtime 2.1 mini voice session (~10 min, 0:00–0:10)
1. Create the project layout, `.env.example`, `.gitignore`, and `requirements.txt`. Set up a virtualenv and install dependencies.
2. `config.py`: load `.env` with `python-dotenv` and expose typed constants. Fail fast with a clear message if `OPENAI_API_KEY` is missing.
3. `audio_io.py`:
   - A mic `InputStream` (24 kHz, mono, int16, about 40 ms blocks). The callback pushes bytes into an `asyncio.Queue` via `loop.call_soon_threadsafe`.
   - An `OutputStream` fed from a thread-safe playback buffer, plus `clear()` for barge-in.
4. `realtime_client.py`:
   - Connect to `wss://api.openai.com/v1/realtime?model={REALTIME_MODEL}` with `Authorization: Bearer {OPENAI_API_KEY}`.
   - On connect, send `session.update` with the instructions, voice, PCM16 24 kHz in/out, server voice activity detection, `tools` (empty for now), and `tool_choice: "auto"`.
   - Task A: read the mic queue, base64-encode, and send `input_audio_buffer.append`.
   - Task B: receive events. Audio delta goes to the playback buffer, `speech_started` triggers barge-in (clear playback + `response.cancel`), `error` gets logged, and anything unknown is logged at DEBUG.
5. `main.py`: `asyncio.run(run())`, Ctrl+C to exit cleanly.
6. **Use headphones for testing.** Speaker echo will trigger false barge-ins. Echo cancellation is Later.

✅ **Done when:** Gopi can hold a natural spoken conversation and interrupt the bot mid-sentence.

### Step 2: Wire the tool-calling layer for computer access (~15 min, 0:10–0:25)
1. `tools/__init__.py`: build `TOOLS` (a list of `{type: "function", name, description, parameters}`) and `HANDLERS` (a name-to-function map).
2. `dispatcher.py`:
   - `async def dispatch(name, args_json) -> str`: parse JSON, look up the handler, run via `asyncio.to_thread` with `asyncio.wait_for(timeout)`, catch every error, and truncate to `MAX_TOOL_OUTPUT_CHARS` (add `...[truncated N chars]`).
   - Log each call to `bot.log`: timestamp, tool, args (secrets redacted), duration, ok/error.
3. `realtime_client.py`: include `TOOLS` in `session.update`. When a function call's arguments are complete, run `dispatch` **as a background task**, then send the `function_call_output` item and `response.create`.
4. Implement `computer.py` (`run_shell`, `read_file`, `write_file`, `list_dir`, `open_app`) with the guardrail.
5. Unit-test each tool in `tests/test_tools.py` without audio.

✅ **Done when:** by voice, "what's on my desktop?", "open my Downloads folder", and "what's my disk space?" all work, and "delete test.txt" asks for confirmation first.

### Step 3: Add file creation for Markdown, PDF, Word, CSV (~10 min, 0:25–0:35)
1. Implement `create_document` in `files.py` with the format rules in 4.2.
2. Add a tiny shared Markdown-to-blocks parser used by both the docx and PDF writers.
3. Register the tool and add tests that create one file of each format in a temp dir and assert it exists and isn't empty.

✅ **Done when:** "make a Word doc called plan with three bullet points about my week, and a CSV of the same list, then open the Word doc" works.

### Step 4: Hook up web search (~10 min, 0:35–0:45)
1. Implement `web_search` (Tavily, with Brave fallback), `scrape_page`, and `open_url`.
2. Register the tools and add the research behavior to the system prompt.
3. Tests: mock HTTP for search, plus one live smoke test that's skipped if no key is set.

✅ **Done when:** "what's the latest news on OpenAI's realtime models?" gives a short spoken answer naming the sources, and "save that as a PDF report" creates the PDF.

### Step 5: Test the full loop end to end (~15 min, 0:45–1:00, protected)
Run these by voice and fix anything that breaks:
1. **Chained task:** "Research the top three open-source text-to-speech models, save a Word report on my desktop, and open it."
2. **Barge-in:** interrupt a long answer. Playback should stop within about 200 ms.
3. **Guardrail:** "Delete the report you just made." It should ask, then act only after a yes.
4. **Failure handling:** "Read the file /does/not/exist." It should report the error calmly.
5. **Timeout:** "Run sleep 120." It should time out and say so.
6. Check that `bot.log` shows every call, and that the OpenAI usage page roughly matches the expected cost (about $0.20 per 15 minutes).

✅ **Done when:** all six pass hands-free with no code changes between them.

---

## 7. Rules for Claude Code while building

- Build **one step at a time**, then stop and tell Gopi how to test it.
- Respect the timeboxes in section 6. When a step overruns, cut scope, log it in `TODO.md`, and move on. Never cut Step 5 testing.
- Keep it to **Stage 1 only**. Don't add anything from the Later list.
- Never block the event loop. Audio and tools run concurrently.
- Every tool returns a string, never raises, and output is always truncated.
- Never hard-code keys. Never commit `.env`.
- Check Realtime event names against current docs, and log unknown events.
- Keep files small and readable. No frameworks beyond the listed packages.

---

## 8. Later (not Stage 1)

- Screen vision (screenshots) plus mouse and keyboard control
- A `think` tool that routes hard reasoning to a strong text model
- Codex / Claude Code as a background coding worker
- Background jobs with spoken "done" notices
- Echo cancellation / speakerphone mode, and a wake word
- Memory across sessions
- Phone/remote client (a web page over Tailscale)
- Sandbox/VM for risky actions
- Cost tracker per session
