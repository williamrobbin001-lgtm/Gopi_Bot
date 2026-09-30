# Stage 5 Instructions: Full-Loop End-to-End Test

> **Paste this into Claude Code** in the `Gopi_bot` project folder. It builds on `gopi-voice-bot-architecture.md`, `CLAUDE.md`, and the Stage 1–4 instruction files. If they are present, follow them too. If they conflict, this file wins for Stage 5. **This is the last stage of the one-hour build.**

| Item | Value |
|---|---|
| Project | Gopi's speech-to-speech voice bot |
| Voice model | OpenAI Realtime API, `gpt-realtime-2.1-mini` (about $0.20 per 15 min) |
| This stage | **Stage 5 of 5: test the full loop end to end** |
| Timebox | **~15 min (0:45–1:00). Protected: never shortened or skipped** |
| Machine | Gopi's Windows PC (PowerShell) |
| End goal | Proof that the bot works like Grok Bot, Codex, or ChatGPT: **voice in, tools out, files created, research done** |

---

## 0. Project recap: what's being tested

| Stage | Built | Key pieces |
|---|---|---|
| 1. Voice session | `audio_io.py`, `realtime_client.py`, `main.py` | Mic in, speaker out (24 kHz PCM16), server voice activity detection, barge-in, `session.update` |
| 2. Computer access | `tools/base.py`, `tools/__init__.py`, `dispatcher.py`, `safety.py`, `tools/computer.py`, `tools_cli.py` | `run_shell` (PowerShell), `read_file`, `write_file`, `list_dir`, `open_app`. Thread + timeout, errors as `ok:false`, truncation, `bot.log`, destructive confirmation |
| 3. File creation | `tools/files.py`, `tools/md_blocks.py`, `tools/paths.py` | `create_document` for md, pdf, docx, csv (+ txt, json, html, xlsx). Aliases, slugged names, no silent overwrite, absolute path returned |
| 4. Web search | `tools/research.py`, `tools/web_utils.py` | `web_search` (Tavily → Brave), `scrape_page` (focused excerpts, untrusted banner), `open_url`, optional `research` |

**Keys are Gopi's step:** `OPENAI_API_KEY` and `TAVILY_API_KEY` (optional `BRAVE_API_KEY`) go in `.env`. Parts A–B of this test run without keys. Parts C–D need them. If keys are missing, finish A–B, write the report, and list the voice tests as **Blocked: waiting on keys**. That's not a failure.

---

## 1. What you're building in this stage

Small test tooling, then the test run itself:

1. **`scripts/preflight.py`:** checks the environment before anything else.
2. **`scripts/smoke_test.py`:** runs every tool through the real `dispatch()` (no voice) and prints PASS/FAIL per tool.
3. **Text mode, `python main.py --text`:** type instead of speak. It sends typed text as a user message (`conversation.item.create` with `input_text`, then `response.create`) and prints the model's transcript plus each tool call. The model, tools, and loop are identical to voice. This lets you (Claude Code) drive the full agent loop yourself once the key exists, and makes failures easy to reproduce.
4. **Turn logging:** each turn in `bot.log` records the user transcript, tool calls (name, args, ok, ms), the assistant transcript, and time to first audio.
5. **`TEST-REPORT.md`:** generated at the end with PASS/FAIL/BLOCKED per test, failures fixed, scope cut, and the final checklist.

Don't add new features in this stage. Only test tooling and fixes.

---

## 2. Test workflow (run in this order)

```
A. Preflight ──► B. Automated (pytest + smoke) ──► C. Text-mode loop ──► D. Live voice ──► E. Report
   no keys          no keys                            OPENAI key            Gopi speaks,
                                                        (+ Tavily)           you verify bot.log
```

**Rule: fix before moving on.** If a test fails, stop, fix the cause, rerun that test **and** `pytest -q`, then continue. Never proceed past a failing part.

---

## 3. Part A: Preflight (~1 min)

`python scripts/preflight.py` checks and prints ✅/❌ for each:
- Python ≥ 3.11 and every package in `requirements.txt` imports
- `.env` exists. Which keys are present (print **present/missing only, never values**)
- `sounddevice.query_devices()` finds a default input and output device (print their names)
- `OUTPUT_DIR` exists and is writable. Desktop path resolves (OneDrive-aware)
- PowerShell is available (`powershell -NoProfile -Command "$PSVersionTable.PSVersion"`)
- A Windows TTF font for PDF exists (`segoeui.ttf` or `arial.ttf`)

**Pass:** every check passes except key checks, which may be missing (they only block C–D).

---

## 4. Part B: Automated tests (~3 min)

1. `pytest -q` covers all Stage 2–4 tests. **Pass: 0 failures.** Live tests stay skipped without keys.
2. `python scripts/smoke_test.py` runs through `dispatch()` and uses a temp folder (never touches real user files):

| # | Call | Pass criteria |
|---|---|---|
| B1 | `run_shell {"command":"Get-Date"}` | `ok:true`, exit 0, stdout has today's date |
| B2 | `run_shell {"command":"Remove-Item C:\\nope.txt"}` | `needs_confirmation:true`, nothing executed |
| B3 | `write_file` new file, then `read_file` | Content round-trips |
| B4 | `list_dir` temp folder | The file from B3 is listed |
| B5 | `open_app` | Mocked, or skipped with `--no-open` |
| B6 | `create_document` md, csv, docx, pdf | 4 files exist, sizes > 0, correct extensions, absolute paths. docx reopens, pdf starts with `%PDF`, csv has a BOM |
| B7 | `create_document` same name twice | Second is `-1` |
| B8 | `web_search` with no key | `ok:false`, message names `TAVILY_API_KEY` (with a key: ≥1 result) |
| B9 | `scrape_page` on a local test HTML string/server | Clean text, untrusted banner present |
| B10 | Unknown tool / bad JSON | `ok:false`, no crash |
| B11 | `bot.log` | One line per call above |

**Pass:** B1–B11 all PASS (B8 either way depending on key).

---

## 5. Part C: Text-mode full loop (~4 min, needs `OPENAI_API_KEY`)

Run `python main.py --text` and type each prompt. For each, verify **both** the reply and `bot.log`.

| # | Stage | Type this | Expected tool calls | Pass criteria |
|---|---|---|---|---|
| C1 | 1 | `Hi, who are you and what can you do?` | none | Short reply listing computer, files, and research abilities |
| C2 | 2 | `What's on my desktop?` | `list_dir` | Accurate short summary, no raw dump |
| C3 | 2 | `How much free space is on my C drive?` | `run_shell` | Correct GB figure (compare with `Get-PSDrive C`) |
| C4 | 3 | `Make a Word doc on my desktop called stage five test with three bullet points about today.` | `create_document` (docx, desktop) | File exists on Desktop, opens with bullets. Reply says where and offers to open |
| C5 | 3 | `Also make it a PDF and a CSV of the same bullets.` | `create_document` ×2 | Both files exist next to the docx |
| C6 | 4 | `What's the latest news about OpenAI's realtime API?` | `web_search` + `scrape_page` (or `research`) | Short answer naming 2–3 sources by site. **Blocked** if there's no Tavily key |
| C7 | 3+4 | `Save that as a Word report in my documents with sources.` | `create_document` | docx in Documents with a `## Sources` section of real URLs from C6 |
| C8 | 2 | `Delete the stage five test PDF.` then `yes` | `run_shell`, then `needs_confirmation`, then a rerun with `confirmed:true` | Asks first, deletes only after yes, file gone |
| C9 | 2 | `Read the file C:\does-not-exist.txt` | `read_file` → `ok:false` | Calm one-sentence error, session continues |
| C10 | 2 | `Run: Start-Sleep -Seconds 120` | `run_shell` → timeout | Reports a timeout, session continues |

**Pass:** C1–C10 PASS (C6/C7 may be BLOCKED without a Tavily key).

---

## 6. Part D: Live voice test (~5 min, Gopi speaks, needs `OPENAI_API_KEY`)

You can't speak, so **print this script for Gopi**, have him run `python main.py` **with headphones**, then read `bot.log` afterward to verify every tool call and mark each result.

| # | Gopi says | Pass criteria |
|---|---|---|
| D1 | "Hey, can you hear me? Tell me in one sentence what you can do." | Replies by voice within ~1–2 s, one sentence |
| D2 | *(While it's talking)* "Stop. Actually, what time is it?" | **Barge-in:** playback stops almost immediately, answers the new question (`run_shell Get-Date` or knows the time) |
| D3 | "Open Notepad." | Notepad opens, bot confirms briefly |
| D4 | "Research the top three open-source text-to-speech models, save a Word report on my desktop, and open it." | **The chained showcase:** says "Searching now", `web_search` → `scrape_page` ×2–3 → `create_document` (docx, desktop) → `open_app`. Report opens in Word with a Sources section. Spoken summary names sources |
| D5 | "Make a spreadsheet of those three models with their licenses." | CSV created, opens in Excel, readable columns |
| D6 | "Delete the spreadsheet." then "Yes." | Asks first, deletes only after yes |
| D7 | "Read my file called nope dot text." | Calm error, keeps going |
| D8 | Stay silent 20 s, then "Are you still there?" | Session alive, responds normally |

**Also verify:**
- **Latency:** in `bot.log`, time to first audio is roughly ≤ 1.5 s for simple replies. Tool turns are acceptable if it says "On it" or "Searching now" first.
- **No read-aloud dumps:** it never reads raw paths, URLs, or code aloud.
- **Cost:** check the OpenAI usage page. The whole test session should be well under about $0.50 (about $0.20 per 15 min).

**Pass:** D1–D8 PASS.

---

## 7. Pass/fail criteria per stage

| Stage | PASS means | Tests |
|---|---|---|
| 1. Voice session | Hears Gopi, replies by voice, barge-in works, survives silence | A (audio devices), D1, D2, D8 |
| 2. Computer access | Every computer tool works through the loop, destructive actions confirm, errors and timeouts don't crash | B1–B5, B10, C2, C3, C8–C10, D3, D6, D7 |
| 3. File creation | md, pdf, docx, csv created in the right folder with the right names, openable, path spoken, no silent overwrite | B6, B7, C4, C5, D5 |
| 4. Web search | Real results, focused reading, sources named, failures handled, report saved with sources | B8, B9, C6, C7, D4 |
| Full loop | Voice → tools → files → research chained hands-free | D4 |

A stage is **FAIL** if any of its tests fail after one fix attempt within the timebox. **BLOCKED** only applies to a missing key.

---

## 8. If something breaks: triage

| Symptom | Likely cause | Fix |
|---|---|---|
| No audio/silence | Wrong device, sample rate not 24 kHz, wrong audio-delta event name | Print devices in preflight, set device explicitly, check event names against current docs, check DEBUG unknown-event logs |
| Bot interrupts itself constantly | Speaker echo triggering voice activity detection | Use headphones, raise the VAD threshold / silence duration |
| Tool never called | Tools missing from `session.update`, bad schema, `tool_choice` not `"auto"` | Log the `session.update` payload, validate schemas |
| Tool runs twice | Handling both `response.function_call_arguments.done` and `response.done` | Handle one source only |
| Model goes silent after a tool | Missing `response.create` after `function_call_output`, or sent while a response is active | Send one `response.create` after all outputs, respect the `response_active` flag |
| Audio stutters during tools | Tool running on the event loop | Ensure `asyncio.to_thread` + `create_task` |
| PowerShell errors / garbled text | Encoding or quoting | `-NoProfile -NonInteractive`, `encoding="utf-8", errors="replace"` |
| File saved in the wrong place | OneDrive Desktop redirect | Fix the alias resolution in `paths.py` |
| PDF crashes on symbols | No Unicode font | TTF fallback chain |
| Search fails | Key missing, wrong Tavily auth format | Check the key is present (not the value), check the auth header against Tavily docs, confirm the Brave fallback |
| Reads URLs/code aloud | Prompt rules missing | Re-add the speaking rules in `prompts.py` |

**Rules:**
- **Fix before moving on.** Rerun the failed test and `pytest -q` after each fix.
- **If you're running over time, cut scope, never testing.** Disable or unregister the broken non-core piece (for example `research`, xlsx, the Brave fallback, PDF tables), log it in `TODO.md` and the report, and continue. Core that must work: voice + barge-in, `run_shell`, `read_file`, `write_file`, `list_dir`, `create_document` (md/docx/csv), `web_search` + `scrape_page`.
- Never weaken safety (the destructive confirmation or the untrusted-content rule) to make a test pass.
- Never mark a test PASS without seeing it in the output or `bot.log`.

---

## 9. `TEST-REPORT.md` (generate at the end)

```markdown
# Voice Bot – End-to-End Test Report
Date: <date/time>   Model: gpt-realtime-2.1-mini   Machine: Windows
Keys: OPENAI <present/missing>, TAVILY <present/missing>, BRAVE <present/missing>

## Results
| Part | Test | Result (PASS/FAIL/BLOCKED) | Notes |
|---|---|---|---|
| A | Preflight | | |
| B | B1 … B11 | | |
| C | C1 … C10 | | |
| D | D1 … D8 | | |

## Stage verdicts
Stage 1: … Stage 2: … Stage 3: … Stage 4: … Full loop: …

## Fixes made during testing
- …

## Scope cut (also in TODO.md)
- …

## Latency & cost
First-audio latency (median): … s   Session cost: $…

## Final checklist
(copy of section 10, ticked)
```

---

## 10. Final checklist: "works like Grok Bot, Codex, or ChatGPT"

- [ ] **Voice in:** Gopi talks naturally, the bot answers by voice quickly, and he can interrupt it mid-sentence
- [ ] **Tools out:** it acts on the PC by voice (runs commands, reads/writes files, lists folders, opens apps) without being told how
- [ ] **Safe:** destructive actions ask first. Errors and timeouts are explained calmly and never crash the session
- [ ] **Files created:** Markdown, PDF, Word, and CSV on request, in the right folder, with clean names, and it says where and opens them
- [ ] **Research done:** searches the live web, reads sources, answers briefly, names sources, and ignores instructions inside web pages
- [ ] **Chained tasks:** "research → save a report → open it" works hands-free in one request
- [ ] **Observable:** every tool call is in `bot.log`. `pytest -q` passes
- [ ] **Affordable:** cost is in line with about $0.20 per 15 minutes
- [ ] **Documented:** `TEST-REPORT.md` written, `TODO.md` lists anything cut

When every box is ticked (or only key-blocked items remain), **Stage 1 v1 is complete.** Tell Gopi the results in plain words, point him to `TEST-REPORT.md`, and list anything in `TODO.md` for Stage 2+ (screen control, `think` tool, Codex worker, background jobs, memory, and so on). **Don't start any new features.**

---

## 11. Step-by-step order (fits ~15 min)

1. `preflight.py` + run it (1 min)
2. `smoke_test.py` + `pytest -q`, fix failures (3 min)
3. `--text` mode + turn logging (2 min)
4. Part C text-mode run, fix failures (4 min)
5. Print the Part D script for Gopi. After he runs it, read `bot.log` and mark results (4 min)
6. Write `TEST-REPORT.md` and give Gopi a spoken-style summary (1 min)
