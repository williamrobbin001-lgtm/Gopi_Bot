# CLAUDE-CODE-INSTRUCTIONS.md

Instructions for Claude Code. Implement the 10 features below into the **existing** Gopi_bot voice agent (OpenAI Realtime API, `gpt-realtime-2.1-mini`).

## Ground rules

- Work inside the existing structure: `main.py`, `bot/realtime_client.py`, `bot/dispatcher.py`, `bot/prompts.py`, `bot/config.py`, `bot/audio_io.py`, `bot/safety.py`, and `bot/tools/`. Follow the existing tool-registration pattern in `bot/tools/base.py` and `bot/tools/__init__.py`.
- Read each file before you edit it. Make targeted edits, not whole-file rewrites.
- **Do not build anything that isn't listed here.**
- **Out of scope, skip entirely:** echo cancellation, and long-session handling (session renewal, context compaction for long calls, reconnect logic).
- Put new settings in `bot/config.py`, with defaults and `.env` overrides. Never print or commit `.env`.
- Add or extend tests in `tests/` for each feature. Run `python -m pytest -q` after each feature, and keep the existing tests green.
- Implement in this order: 1, 2, 9, 4, 10, 3, 5, 6, 7, 8. Finish and test each feature before starting the next.

---

## 1. Smart turn detection

Goal: the bot does not jump in during mid-sentence pauses.

- In the session config sent from `realtime_client.py`, set turn detection to `semantic_vad` with `eagerness: "low"`. Enable `create_response` and `interrupt_response`.
- Enable input noise reduction with type `near_field`.
- Use whichever session-config shape `realtime_client.py` already uses (GA `session.audio.input.*` or the older top-level fields). Don't mix the two.
- Make eagerness configurable: `TURN_EAGERNESS` = low / medium / high / auto, default low.

Done when: a 1–2 second thinking pause mid-sentence does not trigger a reply, and the bot still replies promptly after a finished sentence.

## 2. Clean interruptions

Goal: stop instantly when interrupted, with no overlapping audio, no replay of old audio, and resume where it left off.

- On `input_audio_buffer.speech_started`:
  1. Immediately stop local playback and flush the output queue in `audio_io.py`.
  2. If a response is in progress, send `response.cancel`.
  3. Send `conversation.item.truncate` for the assistant item currently playing, with `content_index: 0` and `audio_end_ms` set to the milliseconds **actually played** to the speaker, not the milliseconds received. This requires tracking played milliseconds per item in `audio_io.py`.
- Track the active response ID. Drop any `response.output_audio.delta` / `response.audio.delta` events that arrive for a cancelled response, so there is no replay.
- Add a line to the system prompt: "If you are interrupted and the user asks you to continue, pick up from exactly where you were cut off. Do not restart from the beginning." The truncate step keeps the model's context aligned with what the user actually heard.

Done when: talking over the bot silences it in under ~200 ms, no stale audio plays afterward, and "go on" resumes from the cut-off point.

## 3. Long-term memory

Build three layers in a new `bot/memory/` package. Store the data in a `memory/` folder at the project root, and add `memory/` to `.gitignore`. **Build the session summary first.** It is the foundation.

1. **Short-term.** The current conversation stays in the Realtime context, as it does now. Also record each user and assistant transcript turn in memory (from the transcript events already received), so layer 2 can summarize it.
2. **Session summary (build first).**
   - When a call ends, including on Ctrl+C / KeyboardInterrupt (use `try/finally` in `main.py`), summarize the recorded transcript with one cheap text-model call using the existing API key.
   - Save the summary to `memory/sessions/<timestamp>.md`. If the summary call fails, save the last ~20 raw turns instead.
   - On boot, load the most recent 1–3 summaries and append them to the instructions under a heading "What you remember from previous calls". Keep this section to a few hundred words at most.
   - Summary content: who the caller is, what they worked on, open tasks, and decisions made.
3. **Persistent store.**
   - Keep facts in `memory/facts.md` (or `memory/facts.json`, whichever is simpler), grouped by category: preference, project, decision, person.
   - On boot, read the store and add it to the instructions under a heading "Known facts".
   - Add a `remember(fact, category)` tool that appends a fact and de-duplicates. Add a `forget(fact)` tool that removes one.
   - Add a prompt line: "When the user states a preference, a project detail, or a decision worth keeping, call `remember`."

Done when: the bot answers questions about the last call correctly when asked, without reciting it unprompted, a fact said in one call is known in the next, and the tests cover save, load, fallback, empty-memory boot, and `remember` / `forget`.

## 4. Personality

Goal: a consistent, defined persona.

- Add a `PERSONA` block at the top of the system instructions in `prompts.py`. It defines the name, tone (warm, direct, concise, conversational), speaking style (short spoken sentences, no markdown or lists read aloud), and how the bot refers to the user (Gopi).
- Put `PERSONA_NAME` and `VOICE` in `config.py`. Defaults: name "Gopi Bot" (placeholder, Gopi can rename it) and voice `marin` (alternative `cedar`).
- Every response path must use the same persona, including tool follow-ups, background-job updates, and handoff messages.

Done when: the tone and voice are the same across greetings, tool results, and errors.

## 5. Screen awareness

Goal: the bot can see the user's screen and refer to it.

- Add a `look_at_screen(question?)` tool in `bot/tools/`. If `computer.py` already has screenshot capture, reuse it. Otherwise use `mss` or `PIL.ImageGrab`.
- Downscale the capture (longest side about 1280 px, JPEG) and send it into the conversation as an `input_image` content item. Then let the model answer the question about it.
- Add a prompt line: call `look_at_screen` when the user says "this", "here", "on my screen", "what am I looking at", or when the task needs to see what's on screen.
- Screenshots are only taken when the tool is called. No continuous capture.

Done when: "what's on my screen?" produces an accurate description of the current screen.

## 6. Background jobs with spoken updates

Goal: long tasks run in the background while the conversation continues, with proactive spoken progress updates and a spoken "done" notice.

- Add a job manager (asyncio tasks) in a new `bot/jobs.py`, with tools `start_background_job(kind, args)`, `job_status(job_id?)`, and `cancel_job(job_id)`.
- Run slow tools as jobs: research, large file generation, and multi-step computer actions. Return "started" to the model right away.
- Progress updates: for jobs longer than ~30 seconds, push a short progress note at milestones.
- Completion: push the result as a conversation item, then `response.create`, so the bot says "That's done: …" out loud.
- Never talk over the user. If the user is speaking or a response is active, queue the update until the turn ends.
- Add a prompt line: before a slow tool, say one short sentence ("On it, give me a moment") and offer to keep chatting.

Done when: the user can keep talking during a research job and hears an unprompted spoken update and done notice.

## 7. Deep reasoning and research

- Add a `think_deeply(problem)` tool that calls a stronger reasoning text model (configurable `REASONING_MODEL`, high reasoning effort) and returns a concise answer the voice model can say aloud.
- Extend the existing research tool (`bot/tools/research.py`) with a "deep" mode: multiple searches, reading the top sources, and a synthesized answer with sources saved to a file in `output/`. Don't rebuild the research tool; extend it.
- Both run as background jobs (feature 6).
- Add a prompt line: use `think_deeply` for multi-step analysis, planning, math, or hard trade-offs. Use deep research for questions that need several sources.

Done when: a hard planning question gets a noticeably better, reasoned answer, and deep research produces a sourced summary file.

## 8. Handoff to a stronger model ("GPT 6 Luna")

Goal: when the current model can't handle a task, hand it off to the stronger model.

- In `config.py`, add `HANDOFF_MODEL = "PPT 6 Luna"`, the name as spoken by Gopi. **Confirm and set the exact API model ID before running.** Also add `HANDOFF_ENABLED = true`.
- Add a `handoff_to_stronger_model(task, context)` tool. It sends the task plus the relevant conversation context and memory to `HANDOFF_MODEL`, runs it as a background job (feature 6), and speaks the result.
- Trigger criteria, per section 2.1 of Gopi's spec: the task is beyond the current model, meaning work that would take a person more than a week alone, large multi-part builds, or problems the current model has failed on.
- Add a prompt line describing these criteria. The bot says it is handing the task off before it calls the tool.

Done when: an oversized task triggers the handoff with a spoken notice, and the result comes back as a spoken summary plus a saved file.

## 9. Hands-free start

Goal: no wake word and no push-to-talk.

- On launch, `main.py` connects, opens the mic, and listens continuously. Turn detection (feature 1) decides when the user is speaking.
- Remove or disable any push-to-talk key or wake-word gating if it exists.
- Greet briefly once on start in persona. Do not mention past sessions unless asked.

Done when: running `python main.py` and just talking works with no key presses.

## 10. Permission modes

Goal: a user-controlled on/off switch for confirmation before actions.

- Add `CONFIRM_ACTIONS` to `config.py`, default **on**. It can be overridden via `.env` and toggled at runtime.
- Add a `set_permission_mode(mode)` tool with modes `"ask"` (confirm) and `"auto"` (no confirmation). It is triggered by voice ("turn off confirmations", "ask me before doing things"). The bot says the new mode aloud.
- Gate risky tools in `bot/safety.py`: computer control, deleting or overwriting files, running commands, and anything that sends data externally. In `ask` mode, the bot describes the action and waits for a spoken yes before running it. In `auto` mode, it runs immediately.
- Destructive actions (deletes, system changes) still ask even in `auto` mode, unless Gopi explicitly changes that setting.

Done when: with confirmations on, the bot asks before acting; with them off, it acts directly; and toggling works by voice.

---

## Final check

- `python -m pytest -q` is all green.
- Run a manual voice test covering each feature's "Done when" line.
- Update `TODO.md` with anything left unfinished. Do not add features beyond this list.
