# CLAUDE.md: Gopi's Speech-to-Speech Voice Bot

This file tells Claude Code how this project is built and what rules to follow. Read it before every task.

## Project summary

A local Python voice assistant for Gopi. It uses the **OpenAI Realtime API (`gpt-realtime-2.1-mini`)** for speech-to-speech (about $0.20 per 15 min). It has **full access to his computer** through tools, creates documents (Markdown, PDF, Word, CSV and more), and researches the web. The target experience is a Perplexity voice agent, Grok Bot, or Codex voice agent: it does what Gopi says.

**Current stage: Stage 1 (v1), one-hour build.** See `STAGE-1-BUILD-INSTRUCTIONS.md` for the step-by-step plan.

## Stage 1 timebox (60 minutes total)

| Step | Budget | Clock |
|---|---|---|
| 1. Stand up the Realtime 2.1 mini voice session | ~10 min | 0:00–0:10 |
| 2. Wire the tool-calling layer for computer access | ~15 min | 0:10–0:25 |
| 3. Add file creation (md, pdf, docx, csv) | ~10 min | 0:25–0:35 |
| 4. Hook up web search | ~10 min | 0:35–0:45 |
| 5. Test the full loop end to end | ~15 min | 0:45–1:00 (protected) |

**Overrun rule:** if a step runs past its budget, **cut scope rather than skip testing**. Ship the minimum version of that step (see the cut list in `STAGE-1-BUILD-INSTRUCTIONS.md`, section 6), record what was dropped in `TODO.md`, and move on. Step 5 is never shortened or skipped.

## Stack

- Python 3.11+, `asyncio`
- `websockets` for the Realtime API connection
- `sounddevice` + `numpy` for audio (24 kHz, mono, PCM16)
- `python-dotenv` for config
- `httpx`, `trafilatura`, `beautifulsoup4` for research
- `python-docx` for Word, `fpdf2` for PDF, stdlib `csv` for CSV
- `pytest` for tests

Don't add other frameworks (no LangChain, no web servers) in Stage 1.

## Architecture

| Layer | Files | Responsibility |
|---|---|---|
| Voice | `bot/audio_io.py`, `bot/realtime_client.py` | Mic capture, speaker playback, WebSocket session, server voice activity detection, barge-in |
| Agent loop | `bot/realtime_client.py`, `bot/dispatcher.py` | Receive function calls, execute tools off the event loop, return `function_call_output`, trigger `response.create` |
| Tools | `bot/tools/computer.py`, `bot/tools/files.py`, `bot/tools/research.py` | Plain Python functions with JSON schemas |
| Config/prompt | `bot/config.py`, `bot/prompts.py` | Env settings, system prompt |
| Entry | `main.py` | `python main.py` |

### Agent loop contract

1. The model emits a function call with `name`, `call_id`, and `arguments` (JSON string).
2. `dispatcher.dispatch(name, arguments)` runs the handler via `asyncio.to_thread` under `asyncio.wait_for(TOOL_TIMEOUT_SECONDS)`.
3. The result string is truncated to `MAX_TOOL_OUTPUT_CHARS`.
4. The client sends `conversation.item.create` → `{type: "function_call_output", call_id, output}`, then `response.create`.
5. On `input_audio_buffer.speech_started`: clear playback and send `response.cancel` (barge-in).

Realtime event names change between API versions. **Check them against the current OpenAI docs**, and log unknown event types at DEBUG.

## Tools (all must exist in Stage 1)

| Tool | Module | Purpose |
|---|---|---|
| `run_shell(command, cwd?, confirmed?)` | computer | Run a shell command (PowerShell on Windows). Returns exit code, stdout, stderr. |
| `read_file(path, max_chars?)` | computer | Read a text file |
| `write_file(path, content, append?, confirmed?)` | computer | Create/append/overwrite a text file |
| `list_dir(path, show_hidden?)` | computer | List a folder (max 200 entries) |
| `open_app(target)` | computer | Open an app, file, folder, or URL with the OS default |
| `create_document(format, filename, content, title?, folder?)` | files | Create md, pdf, docx, csv, txt, json, or html |
| `web_search(query, max_results?)` | research | Tavily search, with Brave fallback |
| `scrape_page(url, max_chars?)` | research | Fetch a page and extract readable text |
| `open_url(url)` | research | Open a URL in the default browser |

### Tool rules

- Signature: plain function, JSON-serializable args, **returns `str`**.
- **Never raise.** Catch everything and return `{"ok": false, "error": "..."}`.
- Expand `~` and relative paths. "Desktop" means `~/Desktop`.
- Output is always truncated by the dispatcher, and tools should also cap their own output.
- `create_document` never overwrites. Add a `-1`, `-2` suffix instead.
- Register each tool in `bot/tools/__init__.py` in both `TOOLS` (schema) and `HANDLERS` (function).
- Every new tool gets a test in `tests/test_tools.py`.

### Destructive-action guardrail

When `CONFIRM_DESTRUCTIVE=true`, `run_shell` and `write_file` refuse destructive actions unless `confirmed=true`. This covers `rm`, `del`, `Remove-Item`, `rmdir`, `format`, `mkfs`, `dd`, `shutdown`, `reboot`, `kill`, `sudo`, `chmod -R`, `git push --force`, `git reset --hard`, and overwriting existing files. Instead they return `{"ok": false, "needs_confirmation": true, "action": "..."}`. The model asks Gopi aloud and retries with `confirmed=true` only after a clear yes. Don't remove this guardrail unless Gopi explicitly asks.

## Config (`.env`)

`OPENAI_API_KEY`, `REALTIME_MODEL=gpt-realtime-2.1-mini`, `REALTIME_VOICE`, `TAVILY_API_KEY`, `BRAVE_API_KEY`, `OUTPUT_DIR=./output`, `CONFIRM_DESTRUCTIVE=true`, `TOOL_TIMEOUT_SECONDS=60`, `MAX_TOOL_OUTPUT_CHARS=8000`, `LOG_LEVEL=INFO`

## Commands

- Install: `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt` (Windows: `.venv\Scripts\activate`)
- Run: `python main.py`
- Test: `pytest -q`

## Coding rules

- Never block the asyncio loop. Mic, playback, the WebSocket, and tools run concurrently.
- Keep modules small, typed, and readable. Use `logging`, not `print`, and log tool calls to `bot.log` with secrets redacted.
- Never hard-code or log API keys. Keep `.env`, `output/`, and `bot.log` out of git.
- Spoken replies are short. Never have the model read code, long files, or URLs aloud.
- Build one step at a time and tell Gopi how to test each one before moving on.
- Keep to the Stage 1 timebox. When a step overruns, cut scope and log it in `TODO.md`. Never skip testing.
- Stay within the current stage. Anything on the Later list needs Gopi's go-ahead.

## Definition of done (Stage 1)

1. A natural voice conversation with barge-in works (headphones recommended).
2. Computer tools work by voice, with confirmation on destructive actions.
3. `create_document` produces valid md, pdf, docx, and csv files.
4. Research answers name their sources and can be saved as a report.
5. The end-to-end chained task passes: research → save a Word report → open it.
6. `pytest -q` passes.

## Later (Stage 2+)

Screen vision + mouse/keyboard control, a `think` tool backed by a strong text model, Codex/Claude Code as a background worker, background jobs with spoken completion, echo cancellation and a wake word, memory across sessions, a phone/remote client over Tailscale, a VM sandbox for risky actions, and per-session cost tracking.
