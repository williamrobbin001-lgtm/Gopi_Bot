# Stage 2 Instructions: Tool-Calling Layer for Computer Access

> **Paste this into Claude Code** in the `Gopi_bot` project folder. It builds on `gopi-voice-bot-architecture.md`, `CLAUDE.md`, and `STAGE-1-BUILD-INSTRUCTIONS.md`. If those files are present, follow them too. If they conflict, this file wins for Stage 2.

| Item | Value |
|---|---|
| Project | Gopi's speech-to-speech voice bot |
| Voice model | OpenAI Realtime API, `gpt-realtime-2.1-mini` (about $0.20 per 15 min) |
| This stage | **Stage 2 of 5: wire the tool-calling layer for computer access** |
| Timebox | **~15 min (0:10–0:25 of the one-hour build)** |
| Machine | Gopi's Windows PC (write cross-platform code, but test on Windows/PowerShell first) |
| End goal | A bot like Grok Bot, Codex, or ChatGPT that can access anything on the computer and do whatever Gopi asks |

---

## 0. API key: Gopi's step, not yours

- Gopi will get the OpenAI API key himself. **Don't ask for it, and don't block on it.**
- It goes in `.env` at the project root as `OPENAI_API_KEY=sk-...`. Keep `.env.example` with the key blank, and keep `.env` in `.gitignore`.
- `bot/config.py` loads it with `python-dotenv`. If it's missing, the **voice session** prints a clear message ("Add OPENAI_API_KEY to .env to start voice") and exits. **Tools, the dispatcher, the CLI harness, and tests must all work without the key.**

---

## 1. What you're building

The layer that lets the Realtime model **act on the computer**:

1. A **tool registry**: every tool's JSON schema (sent to the model) plus its Python handler.
2. A **dispatcher**: runs a requested tool safely (worker thread, timeout, error capture, truncation, logging, confirmation check).
3. **Event wiring** in `realtime_client.py`: receive the model's function calls, run them, return results, and let the model continue.
4. **Five computer-access tools**: `run_shell`, `read_file`, `write_file`, `list_dir`, `open_app`.
5. **Safety and observability**: destructive-command confirmation, error handling, and a `bot.log` of every tool call.

Design every piece so new tools (file creation in Stage 3, web research in Stage 4, and later screen control) plug in by adding **one function + one schema**, with no changes to the loop.

---

## 2. Architecture flow

```
Gopi speaks
   │  mic audio (PCM16, 24 kHz) ──► input_audio_buffer.append
   ▼
Realtime model (gpt-realtime-2.1-mini)
   │  decides a tool is needed
   ▼
function call  {name, call_id, arguments(JSON string)}
   │
   ▼
realtime_client.py ──► dispatcher.dispatch(name, arguments)
                           │ 1. parse + validate args
                           │ 2. destructive? not confirmed → needs_confirmation
                           │ 3. run handler in worker thread, with timeout
                           │ 4. catch errors, truncate output
                           │ 5. log to bot.log
                           ▼
                     result string (JSON)
   │
   ▼
conversation.item.create {type: "function_call_output", call_id, output}
response.create
   │
   ▼
Model either calls another tool (loop) or speaks the result ──► speaker
```

---

## 3. Files to create or modify

```
bot/
├── config.py            # add TOOL_TIMEOUT_SECONDS, MAX_TOOL_OUTPUT_CHARS, CONFIRM_DESTRUCTIVE, LOG_FILE
├── prompts.py           # add tool-use rules to the system prompt
├── dispatcher.py        # NEW
├── safety.py            # NEW: destructive-command detection
├── realtime_client.py   # MODIFY: register tools, handle function calls
└── tools/
    ├── __init__.py      # NEW: TOOLS + HANDLERS registry
    ├── base.py          # NEW: tool decorator, ok()/err() helpers
    └── computer.py      # NEW: the five tools
tools_cli.py             # NEW: run any tool from the terminal without voice or API key
tests/test_computer_tools.py  # NEW
```

`.env` additions (also put these in `.env.example`):
```
CONFIRM_DESTRUCTIVE=true
TOOL_TIMEOUT_SECONDS=60
MAX_TOOL_OUTPUT_CHARS=8000
LOG_FILE=bot.log
```

---

## 4. Tool registry (`bot/tools/base.py`, `bot/tools/__init__.py`)

- Provide a `@tool(name, description, parameters)` decorator that records the schema and handler in a global registry.
- Schema format sent in `session.update`:
  ```json
  {"type": "function", "name": "run_shell", "description": "...", "parameters": {"type": "object", "properties": {...}, "required": [...]}}
  ```
- Helpers: `ok(**data) -> str` returns `json.dumps({"ok": true, ...})`, and `err(msg, **data) -> str` returns `json.dumps({"ok": false, "error": msg, ...})`.
- `bot/tools/__init__.py` imports `computer` (and later `files` and `research`) and exposes `TOOLS: list[dict]` and `HANDLERS: dict[str, Callable]`.
- **Descriptions matter.** Write them for the model: say when to use the tool, and give an example. Example for `run_shell`: *"Run a command on Gopi's Windows PC in PowerShell. Use for system info, installing packages, running scripts, git, searching files, or anything a terminal can do."*

---

## 5. The five tools (`bot/tools/computer.py`)

All handlers are **sync** functions, return a **JSON string**, and **never raise**. Expand `~` and environment variables in paths. Treat "desktop", "downloads", and "documents" as `~/Desktop`, `~/Downloads`, and `~/Documents` (on Windows, also check `~/OneDrive/Desktop` if `~/Desktop` doesn't exist).

### 5.1 `run_shell`
- Params: `command` (string, required), `cwd` (string, optional, default home), `timeout_seconds` (int, optional, max `TOOL_TIMEOUT_SECONDS`), `confirmed` (bool, optional).
- Windows: `subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command], ...)`. macOS/Linux: `["bash", "-lc", command]`.
- `capture_output=True, text=True, encoding="utf-8", errors="replace"`, with a timeout.
- Returns `{ok, exit_code, stdout, stderr, duration_ms}`. A non-zero exit is **not** an exception: return `ok: false` with the output so the model can react.
- On a timeout, kill the process and return `err("timed out after N s")`.
- Never start interactive programs that wait for input. Tell the model this in the description (for example, use `-y` flags).

### 5.2 `read_file`
- Params: `path` (required), `max_chars` (optional, default 8000), `start_line` (optional).
- Reads UTF-8 with `errors="replace"`. If the file looks binary, return `err("binary file", size=...)`.
- Returns `{ok, path, total_chars, content, truncated}`.

### 5.3 `write_file`
- Params: `path` (required), `content` (required), `mode` (`"overwrite"` | `"append"` | `"create"`, default `"create"`), `confirmed` (optional).
- Creates parent folders. In `create` mode, fail if the file exists (suggest overwrite). **Overwriting an existing file is destructive** and needs `confirmed=true`.
- Returns `{ok, path, bytes_written}`.

### 5.4 `list_dir`
- Params: `path` (required), `show_hidden` (optional, default false), `pattern` (optional glob, for example `*.pdf`).
- Returns up to 200 entries, sorted folders first, each with `{name, type, size, modified}`, plus a `total` count and a `truncated` flag.

### 5.5 `open_app`
- Params: `target` (required: an app name, file path, folder path, or URL).
- Windows: if it's a path or URL, use `os.startfile(target)`. Otherwise use PowerShell `Start-Process "<target>"` (works for `notepad`, `chrome`, `code`, `explorer`, `calc`, and so on). macOS: `open` or `open -a`. Linux: `xdg-open`.
- Returns `{ok, opened: target}`. Don't wait for the app to exit.

---

## 6. Dispatcher (`bot/dispatcher.py`)

```python
async def dispatch(name: str, arguments_json: str) -> str:
    # 1. unknown tool      -> err("unknown tool", available=[...])
    # 2. bad JSON args     -> err("invalid arguments JSON")
    # 3. safety check      -> if destructive and not confirmed: needs_confirmation result
    # 4. run               -> await asyncio.wait_for(asyncio.to_thread(handler, **args), timeout)
    # 5. TypeError (bad/missing args) -> err with the expected parameter names
    # 6. any Exception     -> err(f"{type(e).__name__}: {e}")   (never crash the session)
    # 7. truncate          -> cap at MAX_TOOL_OUTPUT_CHARS, append "...[truncated N chars]"
    # 8. log               -> one JSON line to bot.log: ts, tool, args (secrets redacted), ok, duration_ms, output_chars
    return result_string
```

- **Never block the asyncio loop.** Tools always run via `asyncio.to_thread`.
- Redact anything that looks like a key (`sk-...`, `api_key=...`, `token=...`) in logs.
- Also log to the console at INFO: `🔧 run_shell(dir ~/Desktop) → ok in 120 ms`.

---

## 7. Destructive-command confirmation (`bot/safety.py`)

When `CONFIRM_DESTRUCTIVE=true`:

- **`run_shell` is destructive if the command matches** (case-insensitive, word boundaries): `Remove-Item`, `rm`, `del`, `erase`, `rd`, `rmdir`, `Format-Volume`, `format`, `diskpart`, `Stop-Process`, `taskkill`, `kill`, `Stop-Computer`, `Restart-Computer`, `shutdown`, `reg delete`, `Set-ExecutionPolicy`, `Clear-Content`, `Move-Item` onto an existing path, `git reset --hard`, `git clean`, `git push --force` / `-f`, `sudo`, `mkfs`, `dd`, `chmod -R`, or any output redirection (`>`) onto an existing file.
- **`write_file` is destructive** when overwriting an existing file.
- If destructive and not `confirmed`, **don't run it.** Return:
  ```json
  {"ok": false, "needs_confirmation": true, "action": "Delete C:\\Users\\...\\report.docx", "how_to_proceed": "Ask Gopi aloud. If he clearly says yes, call the same tool again with confirmed=true."}
  ```
- The system prompt enforces the spoken yes (section 9).
- Setting `CONFIRM_DESTRUCTIVE=false` in `.env` turns this off completely for full autonomy. Only Gopi changes that.

---

## 8. Event wiring (`bot/realtime_client.py`)

1. **Register tools:** in `session.update`, set `tools: TOOLS` and `tool_choice: "auto"`.
2. **Collect calls:** on `response.done`, walk `response.output` and collect every item with `type == "function_call"` (`name`, `call_id`, `arguments`). This handles one or several calls per response. (`response.function_call_arguments.done` also carries completed calls. Pick one source and don't handle both, or tools run twice.)
3. **Run them:** start `asyncio.create_task(handle_calls(calls))`, so audio keeps flowing while tools run.
4. **Return results:** for each call, send
   ```json
   {"type": "conversation.item.create", "item": {"type": "function_call_output", "call_id": "...", "output": "<result string>"}}
   ```
   then send **one** `{"type": "response.create"}` after all outputs are in.
5. **Don't overlap responses:** keep a `response_active` flag (set on `response.created`, cleared on `response.done`). Only send `response.create` when no response is active.
6. **Barge-in still wins:** if Gopi talks while a tool runs, let the tool finish, return its output, and let the model decide what to do with the new speech.
7. **Verify event names** (`response.done`, `response.output_audio.delta` vs `response.audio.delta`, and so on) against the current OpenAI Realtime docs, and log unknown event types at DEBUG.

---

## 9. System prompt additions (`bot/prompts.py`)

```
TOOLS
You can act on Gopi's Windows PC with tools: run_shell (PowerShell), read_file,
write_file, list_dir, open_app. When he asks you to do something, do it with tools.
Don't just explain how.

- Before a tool that may take a moment, say a very short phrase ("On it.", "Checking.").
- Chain tools until the task is done. Prefer one precise command over many small ones.
- After acting, say in one or two sentences what you did and the result. Never read
  raw output, code, long paths, or file contents aloud; summarize.
- If a tool returns ok=false, say briefly what went wrong and try a sensible fix
  (different command, path, or approach) before giving up.
- If a tool returns needs_confirmation, describe the action in plain words and ask
  "Should I go ahead?" Only after a clear yes, call it again with confirmed=true.
  Never set confirmed=true on your own.
- Never run interactive commands that wait for input. Use non-interactive flags.
```

---

## 10. CLI harness (`tools_cli.py`), no voice or API key needed

```
python tools_cli.py list                       # print all registered tools
python tools_cli.py run_shell "{\"command\": \"Get-Date\"}"
python tools_cli.py list_dir "{\"path\": \"~/Desktop\"}"
```
It calls the same `dispatch()` the voice loop uses, so what works here works by voice.

---

## 11. Tests (`tests/test_computer_tools.py`)

Use `tmp_path`, and don't touch real user files:
- `run_shell` echoes text and returns exit code 0, a failing command returns `ok: false` with stderr, and a timeout is enforced.
- `read_file` returns content, truncates long files, and rejects binary files.
- `write_file` creates a file, create mode refuses an existing file, and overwrite without `confirmed` returns `needs_confirmation`.
- `list_dir` lists files and filters by pattern.
- `safety` flags `Remove-Item x`, `rm -rf y`, and `git push --force`, and doesn't flag `Get-ChildItem` or `git status`.
- `dispatch` covers an unknown tool, bad JSON, handler exceptions returned as `ok: false`, and output truncation.
- `open_app` is mocked, so it doesn't actually launch anything in tests.

Run `pytest -q`. All tests must pass without `OPENAI_API_KEY`.

---

## 12. Step-by-step order (fits ~15 min)

1. `base.py` + `__init__.py` registry (2 min)
2. `computer.py`: `run_shell`, `read_file`, `list_dir` (4 min)
3. `dispatcher.py` + `safety.py` + logging (3 min)
4. `write_file`, `open_app` (2 min)
5. `tools_cli.py` + tests, then run `pytest -q` (2 min)
6. Wire into `realtime_client.py` + prompt additions (2 min)

**If over budget, cut scope, never testing:** ship `run_shell`, `read_file`, and `list_dir` with the dispatcher and safety check first. Add `write_file` and `open_app` after, and log anything dropped in `TODO.md`.

---

## 13. Done when

**Without the API key:**
- [ ] `pytest -q` passes
- [ ] `python tools_cli.py list_dir "{\"path\": \"~/Desktop\"}"` works
- [ ] A destructive command via the CLI returns `needs_confirmation`
- [ ] `bot.log` has one line per tool call

**Once Gopi adds the key (voice test):**
- [ ] "What's on my desktop?" gets a spoken summary
- [ ] "Open Notepad" opens Notepad
- [ ] "How much free disk space do I have?" gets a correct spoken answer
- [ ] "Create a file called hello.txt on my desktop that says hi" works
- [ ] "Delete hello.txt" asks first, and deletes only after "yes"
- [ ] "Read C:\nope.txt" gets a calm spoken error, and the session stays alive

Stop after this and tell Gopi how to run the checks. **Don't start Stage 3.**

---

## 14. Worth adding now (small, high-value)

- **Error handling everywhere:** every failure returns `ok: false` with a readable reason, and the session never crashes on a bad tool call.
- **Confirmation for destructive commands** (section 7), with a single `.env` switch.
- **Tool-call logging** to `bot.log` (JSON lines), with keys redacted.
- **Per-call timeout** plus a hard output cap to protect cost and context.
- **Working-directory memory:** remember the last `cwd` used by `run_shell`, so "now go into that folder" works.
- **Short spoken "working" phrase** before slow tools, so silence doesn't feel like a hang.

## 15. Later (not Stage 2)

Screen capture + mouse/keyboard control, clipboard read/write, background jobs with spoken completion, a `think` tool backed by a strong text model, Codex/Claude Code as a coding worker, a per-folder allowlist, and a sandbox/VM for risky actions.
