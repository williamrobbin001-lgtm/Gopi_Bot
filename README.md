# Gopi Bot

A local speech-to-speech voice assistant for your computer, built on the OpenAI Realtime API (`gpt-realtime-2.1-mini`). You talk and it talks back in real time. You can interrupt it mid-sentence, and it **does things**: runs commands, reads and writes files, opens apps, creates Word, PDF and Excel documents, researches the web, looks at your screen, remembers you between calls, and hands hard problems to stronger models.

It's built and tested on **Windows 10/11** and written to be cross-platform. There are notes for macOS and Linux below.

> **Heads-up: this bot can control your computer.** It can run shell commands and change files. Destructive actions (deleting, overwriting, killing processes, shutting down) always ask for a spoken "yes" first, and by default it asks before *any* risky action. Read [Safety](#safety) before turning that off.

---

## Contents

1. [What it can do](#what-it-can-do)
2. [Requirements](#requirements)
3. [Installation](#installation)
   - [GitHub Codespaces / Linux](#github-codespaces--linux)
4. [Configuration (`.env`)](#configuration-env)
5. [Running the bot](#running-the-bot)
6. [Testing](#testing)
7. [Voice test checklist](#voice-test-checklist)
8. [Safety](#safety)
9. [Project layout](#project-layout)
10. [Costs](#costs)
11. [Troubleshooting](#troubleshooting)

---

## What it can do

| Area | What you can say | Tools behind it |
|---|---|---|
| **Conversation** | Just talk. It waits through thinking pauses, and you can interrupt it at any time. | Realtime API with semantic turn detection |
| **Computer** | "What's on my desktop?", "How much free disk space do I have?", "Open Notepad" | `run_shell`, `read_file`, `write_file`, `list_dir`, `open_app` |
| **Documents** | "Make a Word doc on my desktop with three goals for this week", "Turn that into a PDF" | `create_document` (md, pdf, docx, csv, xlsx, txt, json, html) |
| **Web** | "What's the latest on OpenAI's realtime models?", "Open the first article" | `web_search`, `scrape_page`, `open_url`, `research` |
| **Deep research** | "Do deep research on what tech companies say about AI governance" | `research(mode="deep")` runs in the background and saves a sourced report |
| **Hard thinking** | "Think this through: should I build or buy X?" | `think_deeply` (a strong reasoning model) |
| **Big tasks** | "This is a huge build. Hand it off." | `handoff_to_stronger_model` |
| **Screen** | "What's on my screen?", "What does this error mean?" | `look_at_screen` (one screenshot, only when asked) |
| **Memory** | "Remember I prefer Word reports", "What were we working on last time?" | `remember`, `forget`, plus automatic call summaries |
| **Background jobs** | Keep chatting while slow work runs, and hear "That's done: …" when it finishes | `start_background_job`, `job_status`, `cancel_job` |
| **Permissions** | "Turn off confirmations", "Ask me before doing things" | `set_permission_mode` |

---

## Requirements

| Need | Details |
|---|---|
| **Python** | 3.11 or newer (developed on 3.12). Check with `python --version`. |
| **OpenAI API key** | Required. Get one at <https://platform.openai.com/api-keys> and add some prepaid credit (US$5 is plenty to start). Your account needs access to the Realtime model. |
| **Tavily API key** | Optional, but needed for web search and research. The free tier at <https://tavily.com> is enough. |
| **Brave Search API key** | Optional fallback if Tavily fails. |
| **Microphone and speakers** | **Use headphones.** The bot has no echo cancellation, so with laptop speakers it hears itself and keeps interrupting. |
| **OS** | Windows 10/11 is the main target. macOS and Linux should work; see [Troubleshooting](#troubleshooting). |

---

## Installation

### 1. Get the code

```bash
git clone https://github.com/williamrobbin001-lgtm/Gopi_Bot.git
cd Gopi_Bot
```

### 2. Create a virtual environment and install dependencies

**Windows (PowerShell):**

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

**macOS / Linux:**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

> **Windows tip:** `.venv\Scripts\activate` may fail with *"running scripts is disabled on this system"*. You can skip activation and call `.venv\Scripts\python` directly, as every command in this README does. Or allow local scripts once, for your user only:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```

> **Linux only:** the audio library needs PortAudio: `sudo apt install libportaudio2`.

### 3. Add your API keys

Copy the example settings file and fill in your keys:

```powershell
copy .env.example .env        # Windows
```
```bash
cp .env.example .env          # macOS / Linux
```

Open `.env` in any editor and set at least:

```ini
OPENAI_API_KEY=sk-...
TAVILY_API_KEY=tvly-...      # for web search and research
```

`.env` is in `.gitignore`. **Never commit it or share it.**

### 4. Check the install (no microphone or API key needed)

```powershell
.venv\Scripts\python -m pytest -q
```

You should see every test pass. If you've set `TAVILY_API_KEY`, one extra live search test also runs; otherwise it's skipped.

### GitHub Codespaces / Linux

A GitHub Codespace (the **Code → Codespaces** button on GitHub) is a **Linux** machine in the cloud with a `bash` terminal. The Windows commands above won't work there. In bash, `\` is an escape character, so `.venv\Scripts\python` turns into `.venvScriptspython: command not found`. Use forward slashes and `bin` instead of `Scripts`:

```bash
# 1. The audio library the bot imports (needed even just to run the tests)
sudo apt-get update && sudo apt-get install -y libportaudio2

# 2. Virtual environment and dependencies
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

# 3. Run the tests (no keys, microphone, or internet needed)
.venv/bin/python -m pytest -q
```

| Windows | Linux / Codespaces / macOS |
|---|---|
| `.venv\Scripts\python` | `.venv/bin/python` |
| `copy .env.example .env` | `cp .env.example .env` |
| `"{\"path\": \"~/Desktop\"}"` | `'{"path": "~/Desktop"}'` (single quotes, no backslashes) |

**What works in Codespaces:**

- Reading and editing the code, and running the test suite.
- Trying tools without voice:
  ```bash
  .venv/bin/python tools_cli.py list
  .venv/bin/python tools_cli.py list_dir '{"path": "~"}'
  .venv/bin/python tools_cli.py create_document '{"format":"md","filename":"test","content":"# Hi"}'
  ```
- Web search and research, once you add keys: `cp .env.example .env`, then edit `.env`. Your `.env` is never on GitHub, so each new machine or Codespace needs its own.

**What doesn't work in Codespaces:**

- **Talking to the bot.** A cloud machine has no microphone or speakers, so `main.py` has nothing to listen to or play through. To use voice, clone the repo onto a real computer (Windows, macOS, or Linux desktop) and follow the steps above.
- **Tools that act on a desktop.** `open_app`, `open_url`, and `look_at_screen` need a real screen. `run_shell` runs `bash` inside the Codespace, not on your laptop.

---

## Configuration (`.env`)

Everything has a sensible default. You only *need* `OPENAI_API_KEY`.

### Keys

| Setting | Default | What it does |
|---|---|---|
| `OPENAI_API_KEY` | *(required)* | Used for voice, summaries, reasoning, and handoff. |
| `TAVILY_API_KEY` | *(empty)* | Main web search provider. |
| `BRAVE_API_KEY` | *(empty)* | Fallback search provider. |

### Voice and persona

| Setting | Default | What it does |
|---|---|---|
| `REALTIME_MODEL` | `gpt-realtime-2.1-mini` | The speech-to-speech model. |
| `VOICE` | `marin` | The bot's voice (`cedar` is a good alternative). Overrides `REALTIME_VOICE`. |
| `PERSONA_NAME` | `Gopi Bot` | The bot's name. |
| `TURN_EAGERNESS` | `low` | How quickly it replies after you stop: `low` (most patient), `medium`, `high`, `auto`. |
| `TRANSCRIBE_MODEL` | `gpt-4o-mini-transcribe` | Turns your speech into text for the log and memory. |

### Safety

| Setting | Default | What it does |
|---|---|---|
| `CONFIRM_ACTIONS` | `true` | Starts in **ask** mode: it confirms before commands, file writes, opening apps and links, or sending data to another model. `false` starts in **auto** mode. |
| `CONFIRM_DESTRUCTIVE` | `true` | Deletes, overwrites, kills and shutdowns **always** ask, even in auto mode. Set `false` only if you really mean it. |

### Tools and limits

| Setting | Default | What it does |
|---|---|---|
| `OUTPUT_DIR` | `./output` | Where created documents and reports go. |
| `TOOL_TIMEOUT_SECONDS` | `60` | Maximum run time for a normal tool call. |
| `MAX_TOOL_OUTPUT_CHARS` | `8000` | Cap on tool output sent back to the model, to protect cost and context. |
| `SEARCH_TIMEOUT_SECONDS` | `15` | HTTP timeout for search and page fetches. |
| `SCRAPE_MAX_CHARS` | `6000` | How much text is kept from a web page. |
| `JOB_TIMEOUT_SECONDS` | `900` | Maximum run time for a background job. |
| `JOB_PROGRESS_AFTER_SECONDS` | `30` | Jobs longer than this give a spoken progress update. |

### Models for thinking, research, and memory

| Setting | Default | What it does |
|---|---|---|
| `REASONING_MODEL` | `gpt-5.6-sol` | Used by `think_deeply` and to plan and write deep research. |
| `SUMMARY_MODEL` | `gpt-5.6-luna` | Cheap model that summarizes each call for memory. |
| `HANDOFF_MODEL` | `GPT 6 Luna` | The name the bot *says* when handing off. |
| `HANDOFF_MODEL_ID` | `gpt-6-luna` | The API model ID used for handoffs. Change it if your account doesn't have this model. |
| `HANDOFF_ENABLED` | `true` | Turn the handoff tool on or off. |

### Memory and logging

| Setting | Default | What it does |
|---|---|---|
| `MEMORY_DIR` | `./memory` | Where call summaries (`sessions/`) and facts (`facts.json`) are stored. |
| `MEMORY_SESSIONS_TO_LOAD` | `3` | How many recent call summaries are loaded at startup (1–3). |
| `MEMORY_MAX_WORDS` | `300` | Word cap on the summaries loaded at startup. |
| `LOG_LEVEL` | `INFO` | Set `DEBUG` when troubleshooting. |
| `LOG_FILE` | `bot.log` | Log file (includes one JSON line per tool call, with secrets redacted). |

---

## Running the bot

```powershell
.venv\Scripts\python main.py
```

1. Put your headphones on.
2. Wait for `Session ready. Just start talking (Ctrl+C to quit).`
3. The bot greets you once ("Hi Gopi, what's on your mind?"). Then just talk. There's no wake word and no push-to-talk.
4. Press **Ctrl+C** to quit. On exit, the call is summarized into `memory/sessions/` so the bot remembers it next time.

The console shows what you said (`Gopi: …`), what the bot said (`Bot: …`), and every tool call (`[tool] list_dir(...) -> ok in 5 ms`).

### Try tools without voice or an API key

`tools_cli.py` runs any tool through the same dispatcher (and safety checks) the voice loop uses:

```powershell
.venv\Scripts\python tools_cli.py list
.venv\Scripts\python tools_cli.py list_dir "{\"path\": \"~/Desktop\"}"
.venv\Scripts\python tools_cli.py create_document "{\"format\":\"docx\",\"filename\":\"test\",\"content\":\"# Hi\\n- one\\n- two\"}"
.venv\Scripts\python tools_cli.py web_search "{\"query\": \"python 3.13 release date\"}"
.venv\Scripts\python tools_cli.py run_shell "{\"command\": \"Remove-Item ~/Desktop/x.txt\"}"
```

The last one returns `needs_confirmation` instead of deleting anything.

---

## Testing

### Automated tests

```powershell
.venv\Scripts\python -m pytest -q
```

- All network calls (OpenAI, Tavily, Brave, web pages) are **mocked**, so tests need no keys, no microphone, and no internet.
- Tests use temporary folders and never touch your real files, `bot.log`, or `memory/`.
- Tests marked `live` really hit Tavily. They run only when `TAVILY_API_KEY` is set. To run them on their own:

```powershell
.venv\Scripts\python -m pytest -q -m live
```

To run everything except the live tests:

```powershell
.venv\Scripts\python -m pytest -q -m "not live"
```

| Test file | Covers |
|---|---|
| `test_computer_tools.py` | Shell, file, folder and app tools, the safety check, and the dispatcher (timeouts, errors, truncation, logging) |
| `test_files.py` | Every document format, file naming, never-overwrite, folder aliases, and the Markdown parser |
| `test_research.py` | Search provider fallback, caching, page reading, blocked pages, and deep research end to end |
| `test_realtime_loop.py` | Tool-call loop, barge-in and truncation, stale-audio dropping, turn detection config, greeting |
| `test_jobs.py` | Background jobs, progress and done notices, never talking over you, no overlapping responses |
| `test_memory.py` | Call summaries (save, load, fallback, trimming), `remember` / `forget`, and no reciting history at startup |
| `test_permissions.py` | Ask and auto modes, and destructive actions always confirming |
| `test_screen.py` | Screenshot capture, downscaling, and sending it as an image |
| `test_reasoning_handoff.py` | `think_deeply`, deep research reports, and the handoff |
| `test_persona.py` | Persona and voice used on every response path |

### Live API check (optional, costs a fraction of a cent)

To confirm your key can use every configured model:

```powershell
.venv\Scripts\python -c "import httpx; from bot import config as c; h={'Authorization': f'Bearer {c.OPENAI_API_KEY}'}; [print(m, httpx.get(f'https://api.openai.com/v1/models/{m}', headers=h).status_code) for m in (c.REALTIME_MODEL, c.REASONING_MODEL, c.SUMMARY_MODEL, c.HANDOFF_MODEL_ID, c.TRANSCRIBE_MODEL)]"
```

`200` means the model is available. `404` means change that model in `.env`.

---

## Voice test checklist

Run `.venv\Scripts\python main.py` with headphones on and try each line.

| # | Say | Expected |
|---|---|---|
| 1 | *(start the bot)* | One short greeting, with no recap of past calls |
| 2 | "Tell me a long story", then interrupt mid-sentence | It goes silent immediately; "go on" resumes where it stopped |
| 3 | Pause 1–2 s in the middle of a sentence | It waits for you to finish |
| 4 | "What's on my desktop?" | A short spoken summary of your desktop |
| 5 | "How much free disk space do I have?" | The correct amount |
| 6 | "Open Notepad" | In ask mode it asks first, then opens Notepad after you say yes |
| 7 | "Create a file called hello.txt on my desktop that says hi" | The file is created |
| 8 | "Delete hello.txt" | It asks "Should I go ahead?" and deletes only after a yes |
| 9 | "Make a Word doc on my desktop with three goals for this week" | A `.docx` is created and it offers to open it |
| 10 | "Make a spreadsheet of five countries and their capitals" | A CSV that opens cleanly in Excel |
| 11 | "What's the latest news on OpenAI's realtime models?" | "Searching now", then a short answer that names its sources |
| 12 | "Do deep research on what tech companies say about AI governance" | "Started" now, a progress update around 30 s, then "That's done: …" and a report in `output/` |
| 13 | "What's on my screen?" | An accurate description of your screen |
| 14 | "Remember that I prefer Word reports", quit, restart, then "What do you know about my preferences?" | It knows the preference |
| 15 | "What were we working on last time?" | A correct answer from memory |
| 16 | "Turn off confirmations" | It asks once, then switches to auto mode and says so |
| 17 | "Read the file C:\nope.txt" | A calm error, and the session keeps going |

---

## Safety

- **Permission modes.** In **ask** mode (the default), the bot describes each risky action (running a command, writing a file, opening an app or link, sending data to another model) and waits for your spoken "yes". In **auto** mode it acts immediately. Switch by voice ("turn off confirmations" / "ask me before doing things"). Switching *to* auto always requires a spoken yes.
- **Destructive actions always ask**, in both modes: deleting, overwriting, `Stop-Process` / `kill`, shutdown or restart, `git push --force`, `git reset --hard`, registry deletes, disk formatting, and similar. Only `CONFIRM_DESTRUCTIVE=false` turns this off.
- **Web content is untrusted.** Text from web pages and research results is marked as untrusted, and the bot is told never to follow instructions found in it. After the bot reads a web page, any later command or file action is logged with that page's URL (`after_web_url` in `bot.log`), so you can trace what led to it.
- **Screenshots** are taken only when you ask ("what's on my screen?"), never continuously.
- **Privacy.** `bot.log` contains what you said and every tool call. `memory/` contains summaries of your calls. Both stay on your machine and are git-ignored. Keys are redacted from logs.

---

## Project layout

```
Gopi_Bot/
├── main.py                 # entry point: python main.py
├── tools_cli.py            # run any tool from the terminal, no voice needed
├── requirements.txt
├── .env.example            # copy to .env and add your keys
├── pytest.ini
├── bot/
│   ├── config.py           # settings from .env
│   ├── prompts.py          # persona + system prompt
│   ├── audio_io.py         # mic capture and speaker playback (24 kHz PCM16)
│   ├── realtime_client.py  # WebSocket session, barge-in, tool-call loop, spoken updates
│   ├── dispatcher.py       # runs tools safely: threads, timeouts, errors, truncation, logging
│   ├── safety.py           # permission modes and destructive-action detection
│   ├── jobs.py             # background job manager
│   ├── llm.py              # text-model calls (summaries, reasoning, handoff)
│   ├── memory/             # call summaries and the fact store
│   └── tools/              # one file per tool group; each tool is a function plus a JSON schema
│       ├── computer.py     # run_shell, read_file, write_file, list_dir, open_app
│       ├── files.py        # create_document
│       ├── research.py     # web_search, scrape_page, open_url, research (quick and deep)
│       ├── screen.py       # look_at_screen
│       ├── reasoning.py    # think_deeply
│       ├── handoff.py      # handoff_to_stronger_model
│       ├── memory_tools.py # remember, forget
│       ├── jobs_tools.py   # start_background_job, job_status, cancel_job
│       └── permissions.py  # set_permission_mode
├── tests/                  # pytest suite (network mocked)
├── output/                 # created documents and reports (git-ignored)
└── memory/                 # your saved memory (git-ignored)
```

**Adding a tool:** write one function decorated with `@tool(name, description, parameters)` in `bot/tools/`, return a JSON string with the `ok()` / `err()` helpers, and import the module in `bot/tools/__init__.py`. The voice loop picks it up automatically.

---

## Costs

| Item | Rough cost |
|---|---|
| Voice (`gpt-realtime-2.1-mini`) | About US$0.20 per 15 minutes of conversation |
| Call summary on exit | A fraction of a cent |
| `think_deeply` / deep research / handoff | Depends on the model and length; each is a single strong-model call (deep research makes two) |
| Tavily search | Free tier covers normal personal use |

Check your usage at <https://platform.openai.com/usage>.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `Add OPENAI_API_KEY to .env to start voice` | Create `.env` from `.env.example` and set your key. |
| `ModuleNotFoundError: No module named 'numpy'` | You ran the system Python. Use `.venv\Scripts\python main.py`. |
| `running scripts is disabled on this system` | See the Windows tip in [Installation](#2-create-a-virtual-environment-and-install-dependencies). |
| The bot keeps interrupting itself | It's hearing its own voice. Use headphones. |
| It replies too slowly after you finish | Set `TURN_EAGERNESS=medium` (or `high`) in `.env`. |
| It jumps in while you're still thinking | Keep `TURN_EAGERNESS=low`. |
| No sound, or the wrong microphone | Set the default input and output devices in your OS sound settings, then restart the bot. |
| "Web search unavailable: no TAVILY_API_KEY…" | Add `TAVILY_API_KEY` (or `BRAVE_API_KEY`) to `.env`. |
| A web page "blocked access (HTTP 403)" | Some sites block bots. Quick research skips them; deep research reads them through Tavily. |
| Handoff fails with HTTP 404 | Your account doesn't have `HANDOFF_MODEL_ID`. Set it to a model you can use (for example `gpt-5.6-sol`). |
| `Realtime error: …` in the console | Set `LOG_LEVEL=DEBUG`, run again, and check the end of `bot.log`. |
| Screenshot fails on Linux | Screen capture needs an X11 session. Wayland may not be supported by Pillow. |
| "File is open in another program" | Close the document in Word or Excel and try again, or save under a new name. |

**Not supported yet:** echo cancellation (use headphones), and automatic reconnect or compaction for very long sessions.
