# TODO

Stage 1 (steps 1-4): nothing was cut.

## CLAUDE-CODE-INSTRUCTIONS.md features: left to do

All 10 features are implemented and covered by `pytest`. What's left is the
manual **voice** check of each "Done when" line, which needs Gopi at the mic
(headphones on):

- [ ] 1 Smart turn detection: pause 1-2 s mid-sentence, no reply; a finished sentence gets a prompt reply. If it feels slow, set `TURN_EAGERNESS=medium`.
- [ ] 2 Clean interruptions: talk over a long answer, silence in under ~200 ms, no stale audio; "go on" resumes from the cut-off point.
- [ ] 9 Hands-free start: `python main.py`, it greets you once briefly (no past-call recap), then just talk.
- [ ] 4 Personality: same tone and voice across greeting, tool results, and errors.
- [ ] 10 Permission modes: in ask mode "open Notepad" asks first; "turn off confirmations" asks once, then acts directly; deletes still ask.
- [ ] 3 Long-term memory: say "remember I prefer Word reports", hang up (Ctrl+C), restart; the greeting is short with no history, "what were we working on last time?" is answered correctly, and the fact is known.
- [ ] 5 Screen awareness: "what's on my screen?" gives an accurate description.
- [ ] 6 Background jobs: start deep research, keep chatting, hear an unprompted progress update and a "That's done" notice.
- [ ] 7 Deep reasoning and research: a hard planning question gets a reasoned answer; deep research saves `output/research-*.md` with sources.
- [ ] 8 Handoff: an oversized task gets "handing this to GPT 6 Luna", then a spoken summary and `output/handoff-*.md`.

## Known limits (by design / out of scope)

- Echo cancellation and long-session handling (renewal, compaction, reconnect) are out of scope. Use headphones.
- Facts saved with `remember` reach the instructions at the next call; within the current call the model already has them in context.
- `look_at_screen` captures the primary screen only.
