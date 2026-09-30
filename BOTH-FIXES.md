# BOTH-FIXES.md

Instructions for Claude Code. Fix two bugs in the existing Gopi_bot voice agent (OpenAI Realtime API). This file replaces `DEEP-RESEARCH-FIX.md`: do everything below in one pass.

## Scope

- **Fix 1:** make deep research work end to end.
- **Fix 2:** stop the bot from reciting past conversation history at startup, while keeping memory retrieval working.
- **Do not add features.** Don't build anything beyond these two fixes.
- **Do not touch echo cancellation or long-session handling.** Both are out of scope.
- **Keep memory storage as it is.** Saving session summaries and facts across close and reopen works, and Gopi likes it. Only change how memory is presented at startup (Fix 2).
- Read each file before you edit it. Make targeted edits, not whole-file rewrites.

---

## Fix 1: Deep research fails

### What Gopi saw

When he asks a question that needs deep research, the bot starts a job, then says the job hit an error and "couldn't read the pages it found." The research never finishes, and no report file appears in `output/`. Normal (non-deep) `research` calls worked earlier today (08:20–08:25 in `bot.log`).

### Evidence from bot.log (09:00:39–09:01:00)

1. **Two jobs for one request.** The model called `start_background_job(kind="research", args={..., "mode": "deep"})`. That started `job-1` ("research ... mode=deep") **and** `job-2` ("deep research: ..."). The dispatcher then also ran `research(..., mode="deep", confirmed=true)`, which returned in 0 ms, and `job-1` reported "done after 0 s". The research path appears to spawn its own job, or return immediately, instead of doing the work.
2. **Realtime API error:** `conversation_already_has_active_response`. Something (the job start or done notice, or a tool follow-up) sent `response.create` while a response was already in progress.
3. **Misleading spoken status.** The bot said "That's done. A deep research job is running." That is a start notice worded as a completion.
4. **The real failure:** `job-2 failed after 21 s`. Per the bot, pages were found but couldn't be read, so most were skipped. **The actual exception and traceback were not logged.**
5. No report file was written to `output/`.

### 1a. Diagnose first

- Trace the full deep research path: the tool schema in `prompts.py`, then `dispatcher.py`, `bot/jobs.py`, `bot/tools/research.py`, `bot/tools/web_utils.py`, and back into `realtime_client.py` for the spoken updates.
- Reproduce the failure without voice. Use `tools_cli.py`, or a small script that calls deep research directly with a real question (for example "What are major tech companies saying about AI governance? Focus on recent news."), using the same args as in the log.
- Log the real exception with its full traceback from inside the job, so failures are never silent again.
- Treat these only as hypotheses, and verify each one:
  - Page fetching or reading fails for most URLs. Possible causes: missing or blocked user-agent, timeouts too short, non-HTML or PDF content, encoding or decoding errors, redirects, or a function signature mismatch between the deep mode and `web_utils.py`.
  - The deep mode passes args the fetch or search helpers don't accept.
  - An exception in one source aborts the whole job instead of skipping only that source.
  - The double job spawn (job wraps research, and research spawns its own job) causes the real job to run in an unexpected context.
- Write down the root cause or causes you actually found before changing code.

### 1b. Fix

- **Page reading:** make fetching and reading robust. Skip failed sources individually and continue. Fail the job only if zero sources could be read, and in that case report a clear reason.
- **One request, one job:** a deep research request must create exactly one background job. Either `start_background_job` runs the research work directly, or `research(mode="deep")` starts the job itself, but not both.
- **No overlapping responses:** track whether a response is active. Queue job start, progress, and done notices, and send `response.create` only once the current response is finished (`response.done`). Eliminate `conversation_already_has_active_response`.
- **Honest status wording:** the start notice says it has started; only the completion notice says it is done. On failure, give a short spoken reason.
- **Output:** on success, save the synthesized answer with its sources to a report file in `output/`, and speak a short summary that mentions the file.

### 1c. Tests

- Add or extend tests in `tests/test_research.py` (and a jobs test if one exists). Mock the network. Cover:
  - Deep research with a mix of readable and failing pages completes, using the readable ones.
  - Deep research where all pages fail produces a clear failure message, and the exception is logged.
  - One deep research request creates exactly one job.
  - Job notices are not sent while a response is active; they are queued and sent after `response.done`.
- Run `python -m pytest -q`. All tests must pass, including the existing ones.

---

## Fix 2: The bot recites past history at startup

### What Gopi saw

On startup the bot says "Hi Gopi, what's on your mind?" and then reads the entire previous conversation history out loud.

### Desired behavior (like Grok's memory)

- Greet briefly only, for example "Hi Gopi, what's on your mind?", and then stop and listen.
- Never read out, list, or summarize past sessions unless Gopi asks, for example "what were we working on?" or "do you remember X?".
- Use past history silently: when a question relates to earlier sessions or saved facts, the answer should reflect that knowledge naturally, without narrating the memory.

### Diagnose first

Find exactly what makes it recite the history. Treat these only as hypotheses, and verify each one:

- `CLAUDE-CODE-INSTRUCTIONS.md` told you to "Greet the user once on start, using the persona and the session summary" (feature 9). It also said "a new call greets the user with awareness of the last call" (feature 3). The greeting code or prompt may literally tell the model to talk about the summary.
- The memory is injected into the instructions under a heading like "What you remember from previous calls", with no rule against reciting it, so the model treats it as something to say.
- The startup greeting may be sent as a `response.create` with instructions or a conversation item that contains the summary text, so the model reads it aloud.
- Full raw transcripts, rather than short summaries, may be loaded at startup (the fallback path) and then echoed back.

### Fix

- **Greeting:** the startup `response.create` must only ask for a short greeting in persona, with no memory content in that response's instructions or conversation items.
- **Memory framing:** keep loading the summaries and facts into the session instructions, but wrap them in a clear private-context block. Add explicit rules:
  - "This is private background memory. Do not recite, list, or summarize it unprompted."
  - "Use it silently to answer questions and personalize replies."
  - "Only talk about past sessions when Gopi asks about them."
- **Size:** load only short summaries (the most recent 1–3, capped at a few hundred words total), never full raw transcripts. If only raw turns exist from the fallback, condense or trim them before injecting.
- **Correct the source instructions:** in `CLAUDE-CODE-INSTRUCTIONS.md`, change feature 9's greeting line to "Greet briefly once on start in persona. Do not mention past sessions unless asked." Change feature 3's done-when line to "the bot answers questions about the last call correctly when asked, without reciting it unprompted." This prevents the bug from coming back.

### Tests

- The startup greeting request contains no memory or summary text.
- The session instructions contain the memory block together with the do-not-recite rules.
- Oversized or raw-transcript memory is trimmed before injection.
- Existing memory tests (save, load, fallback, empty-memory boot, remember / forget) still pass.

---

## Done when

- **Deep research:** asking by voice "Do deep research on what major tech companies are saying about AI governance" results in one job, a spoken "started" notice, and a spoken summary within a reasonable time, with a report file saved in `output/`. `bot.log` shows no `conversation_already_has_active_response` errors. If some pages fail, research still completes from the rest. If all fail, the log has the real traceback and the bot gives a clear spoken reason.
- **Startup:** after closing and reopening the bot, it says only a short greeting and does not recite any history. Asking "what were we working on last time?" gives a correct answer drawn from memory, and saved facts still shape answers naturally.
- `python -m pytest -q` is all green.

## Report back

For each fix, tell Gopi the root cause or causes you found, what you changed (files plus a one-line reason for each), the test results, and anything still unresolved.
