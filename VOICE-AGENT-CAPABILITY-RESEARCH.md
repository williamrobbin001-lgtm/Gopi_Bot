# Voice-agent capability research → Gopi's speech-to-speech bot
_Research date: Sep 30, 2026. Target stack: Python on Windows, OpenAI Realtime API (`gpt-realtime-2.1-mini`) over WebSocket, local tools (PowerShell, files, apps, docs, web search/scrape)._

Legend: ✅ shipped · ◐ partial / limited / platform-specific · ❌ not offered · ? unverified. Numbers in [brackets] → Sources.

## 1. Comparison (consumer products + the builder APIs behind them)

| Capability | ChatGPT Voice (GPT-Live) | OpenAI Realtime API (builder) | Grok voice (app) / xAI Voice Agent API | Gemini Live | Perplexity voice / Comet | Rabbit OS3 |
|---|---|---|---|---|---|---|
| Full-duplex, barge-in | ✅ listens & speaks at once [1] | ✅ VAD auto-cancels; WS client must truncate [3] | ✅ app; API "barge-in support" [8][9] | ✅ interrupt anytime [12] | ✅ gpt-realtime-1.5 under the hood [15][16] | ◐ r1 push-to-talk; web voice undocumented [19] |
| Smart turn detection | ✅ waits through pauses [2] | ✅ `semantic_vad` + `eagerness` [4] | ◐ API `server_vad` only; `idle_timeout_ms` check-ins [10] | ✅ (VAD; Live API) [13] | ✅ (inherits OpenAI VAD) [15] | ? |
| Long-term memory | ✅ ChatGPT memory [1] | ❌ DIY (inject into instructions) | ✅ app memory (EU/UK uneven) [11] | ✅ past-chat memory + Connected Apps [12] | ◐ in-session / cross-tab context [15] | ✅ one continuous conversation + memory [19] |
| Tool use while talking | ✅ delegates Work/Codex tasks, reports back [2] | ✅ function calling, remote MCP, native async-friendly model [5][6][7] | ✅ API: web/X/file search, MCP, custom fns, parallel calls [10] | ✅ Connected Apps (Google) [12] | ✅ browser actions by voice [15] | ✅ shell/files/apps on up to 5 PCs [19][20] |
| Filler / preambles during tools | ✅ keeps talking while work runs [2] | ✅ preambles by default on realtime-2.x [6] | ? | ? | ? | ◐ progress notifications [19] |
| Vision: camera / screen | ◐ Live: no video/screen share (Advanced mode has it on mobile); macOS "appshot" screen context in desktop voice [1][2] | ✅ image input (incl. 2.1-mini) [3][5] | ◐ Grok Vision camera in voice (iOS, 2025) [14] | ✅ live camera + full screen share (Android) [12] | ✅ Comet "screen awareness" [15] | ◐ DLAM reads screen only as fallback [20] |
| Files (read/create) | ✅ docs/files in chat [1] | DIY tools | ◐ API file_search [10] | ◐ | ✅ summarize PDFs/tabs [16] | ✅ local files + generates docs/decks [19][21] |
| Research depth / citations | ✅ web search [1] | DIY | ✅ web + X search [10] | ✅ Search | ✅ core strength (search w/ citations) | ✅ multi-step research tasks [21] |
| Voices / emotion control | ✅ multiple voices | ✅ 10 voices, prompt-steered tone [3] | ✅ 6 app voices + speed; API 26+ voices, speech tags, cloning [8][9] | ✅ voices; Live API "affective dialog" (not on 3.1 Flash Live) [13] | ✅ improved expressiveness [16] | ◐ r1 "magic voice" |
| Wake word / hands-free | ❌ app/hotkey [2] | DIY | ❌ tap | ✅ "Hey Google, let's talk" [12] | ✅ "Hey Plex" on Galaxy S26; Action Button [16] | ◐ r1 button; Telegram/SMS channels [19] |
| Background tasks / proactive | ✅ spoken progress/blocked/done updates [2] | DIY (`idle_timeout_ms` for check-ins) [18] | ◐ API idle check-ins [10] | ◐ Astra "proactive" = research prototype, not shipped [12b] | ❌ | ✅ background + scheduled tasks [21] |
| Device / app control | ✅ desktop (Work/Codex permissions) [2] | DIY tools | ❌ app | ✅ Android apps via Connected Apps [12] | ✅ browser; Samsung apps [16] | ✅ terminal + DLAM mouse/keyboard [20] |
| Safety / permissions | ✅ inherits task permissions [2] | ◐ MCP `require_approval`; DIY for functions [7] | ? | ✅ follows Gemini permissions [12] | ? | ✅ Ask-every-time / Ask-new / Full-access modes [20] |
| Phone calling | ❌ | ✅ SIP [5] | ✅ Twilio demo agent [9] | ❌ | ❌ | ❌ |

Not added (no clearly distinct capability found in the time available): Alexa+, Siri, Claude voice, Sesame, Hume EVI.

## 2. Prioritized capabilities for Gopi's bot

### v1 — fits inside the 1-hour window (≈30 min total)
1. **Semantic turn detection + noise reduction — v1 (~3 min).** Who has it: ChatGPT, Realtime API, Gemini. How: in `session.update` set `audio.input.turn_detection = {"type":"semantic_vad","eagerness":"low","create_response":true,"interrupt_response":true}` and `audio.input.noise_reduction = {"type":"far_field"}` (`near_field` for a headset) [4][18]. Fall back to `server_vad` with `silence_duration_ms≈600` if semantic_vad feels sluggish.
2. **Real barge-in (stop audio + truncate) — v1 (~10 min).** Everyone ships this; on WebSocket it's the client's job. How: on `input_audio_buffer.speech_started` → clear the local playback queue immediately, compute ms of the current assistant item actually played, send `conversation.item.truncate {item_id, content_index:0, audio_end_ms}` (and `response.cancel` if a response is still streaming) [3]. **Use headphones** (or mute mic while speaking) — without echo cancellation the bot hears itself and interrupts itself.
3. **Preambles + low reasoning effort — v1 (~3 min).** Who: ChatGPT keeps talking while work runs; realtime-2.x preambles. How: `reasoning.effort:"low"` (raise per need) and an instruction block: "Before any tool call that may take >1s, say one short sentence of what you're doing; skip it for instant answers; never read raw tool output aloud — summarize" [6].
4. **Non-blocking tools — v1 (~7 min).** Who: ChatGPT/Rabbit keep conversing while tasks run; gpt-realtime handles long-running calls without breaking flow [7b]. How: on `response.function_call_arguments.done` dispatch the tool with `asyncio.create_task` / `run_in_executor` so the WS receive loop keeps pumping audio; when done send `conversation.item.create {type:"function_call_output", call_id, output}` then `response.create`. Truncate large outputs (e.g., 4 KB) before sending. (Note: the explicit `async: true` tool flag is documented for GPT-6 Astra+ on the Responses side, not claimed for 2.1-mini [7c].)
5. **Tiny long-term memory — v1 (~7 min).** Who: ChatGPT, Grok, Gemini, Rabbit. How: `memory.json` (list of facts). Load it into `instructions` at session start ("Known about Gopi: …"); add a `remember(fact)` tool that appends + saves; instruction: "Only store durable preferences/facts when asked or clearly useful."
6. **Persona & voice — v1 (~2 min).** Who: all (Grok especially). How: choose `voice:"marin"` or `"cedar"` (OpenAI's recommended) [3]; 5-line persona (name, tone: concise, witty, confident; speak ≤2 sentences unless asked; confirm destructive actions explicitly by restating the command).

### Later (post-v1)
- **Screen awareness (`look_at_screen` tool) — Later (~20 min).** Grab screen with `mss`, downscale to ~1280px JPEG, send `conversation.item.create` with `{"type":"input_image","image_url":"data:image/jpeg;base64,…"}` then `response.create`; 2.1-mini accepts image input ($0.80/1M image tokens) [5]. Webcam variant with OpenCV (~15 min more). (Gemini Live, Comet, ChatGPT appshots, Grok Vision.)
- **Deep-research tool (async) — Later (~45 min).** Delegate to a text model (Responses API + web search) in a background task; speak "started", then announce a cited summary + write a .md report when done. (Perplexity, ChatGPT, Rabbit.)
- **Background jobs + proactive announcements — Later (~45 min).** Job queue for long shell/doc tasks; on completion inject a system/user item and `response.create` ("Tell Gopi the build finished"). Optional `idle_timeout_ms` check-ins [18]. (ChatGPT desktop voice, Rabbit.)
- **Hotkey push-to-talk / wake word — Later (~30–60 min).** Global hotkey (`keyboard` lib) first; wake word via openWakeWord/Porcupine later. (Gemini "Hey Google", Perplexity "Hey Plex".)
- **Permission modes — Later (~20 min).** Rabbit-style Ask-every-time / Ask-for-new / Full-access in config; allow-list of safe PowerShell verbs; confirmation by voice + log to bot.log [20].
- **Long-session hygiene — Later (~30 min).** Realtime sessions cap at 60 min [3b]: auto-reconnect with a running summary; `truncation` with `retention_ratio≈0.8` and `token_limits.post_instructions` to keep cost down [18b]; summarize-to-memory on exit.
- **Remote MCP tools — Later (~15 min each).** Add `{"type":"mcp","server_url":…,"require_approval":"always"}` in `session.tools` (executed by OpenAI, so only for internet-reachable servers) [7].
- **Live captions / transcript UI — Later (~20 min).** Enable input transcription + show `response.output_audio_transcript.delta` in a small window; helps debugging mishears.
- **Codex delegation tool — Later (~20 min).** `run_codex(task)` → `codex exec --json` in a repo; speak a summary (see earlier Codex research).
- **Phone calling — Later (hours).** Realtime SIP or Twilio bridge [5].
- **Multi-language — Later (~5 min).** Instruction: reply in the user's language; ignore fillers for language switching [6].

## 3. Caveats
- Consumer feature sets change weekly; several rows rely on vendor docs/marketing, not hands-on tests. xAI's app "Companions" 3D avatars were announced as being retired (Jul 2026); personalities remain [8b].
- Gemini/Astra "proactive responses" and "multimodal memory" are prototype/in-progress, not broadly shipped [12b]. Comet iOS voice was announced for March 2026; the Feb changelog says desktop + Android.
- 2.1-mini is a distilled model: fine for turn-taking and simple tools; delegate hard reasoning (deep research, coding) to a stronger model/tool.
- Image input and preambles are documented for gpt-realtime-2/2.x; confirm preamble behavior on 2.1-mini in a quick test.

## Sources
1. ChatGPT Voice (help): https://help.openai.com/en/articles/20001274
2. ChatGPT Voice in Chat/Work/Codex: https://learn.chatgpt.com/docs/features/voice
3. Realtime conversations (image input, interruption/truncation): https://developers.openai.com/api/docs/guides/realtime-conversations — 3b. 60-min session cap: same page ("maximum duration of a Realtime session is 60 minutes")
4. Realtime VAD (server_vad / semantic_vad, eagerness): https://developers.openai.com/api/docs/guides/realtime-vad
5. gpt-realtime-2.1-mini model page (image input, WS/WebRTC/SIP, pricing): https://developers.openai.com/api/docs/models/gpt-realtime-2.1-mini ; SIP guide: https://developers.openai.com/api/docs/guides/realtime-sip
6. Realtime prompting (reasoning effort, preambles, language): https://developers.openai.com/api/docs/guides/realtime-models-prompting
7. Realtime remote MCP: https://developers.openai.com/api/docs/guides/realtime-mcp — 7b. gpt-realtime announcement (async function calling): https://openai.com/index/introducing-gpt-realtime/ — 7c. Async tool calling guide: https://developers.openai.com/api/docs/guides/async-tool-calling
8. Grok voice mode guide (voices, speed, companions retirement) (third-party): https://felloai.com/grok-voice-mode/ — 8b. r/LoveGrok thread: https://www.reddit.com/r/LoveGrok/comments/1v6x3bu/
9. xAI Voice API page: https://x.ai/api/voice
10. xAI Voice docs: https://docs.x.ai/developers/model-capabilities/audio/voice ; Pipecat Grok Realtime (turn_detection, idle_timeout_ms, tools): https://docs.pipecat.ai/api-reference/server/services/s2s/grok ; xAI function calling (parallel): https://docs.x.ai/developers/tools/function-calling
11. Grok memory (third-party): https://plurality.network/blogs/does-grok-ai-have-persistent-memory/
12. Gemini Live help: https://support.google.com/gemini/answer/15274899 ; Android camera/screen: https://www.android.com/articles/gemini-on-android/ — 12b. Project Astra: https://deepmind.google/models/project-astra/
13. Gemini Live API guide (VAD, proactive audio, affective dialog): https://ai.google.dev/gemini-api/docs/live-guide
14. Grok Vision (TechCrunch, Apr 2025): https://techcrunch.com/2025/04/22/xais-grok-chatbot-can-now-see-the-world-around-it/
15. Comet Voice Mode changelog: https://www.perplexity.ai/changelog/comet-voice-mode-improvements
16. Perplexity Feb 27 2026 changelog (Hey Plex, Galaxy S26, gpt-realtime-1.5): https://www.perplexity.ai/en-GB/changelog/what-we-shipped---february-27-2026
18. Realtime API reference (noise_reduction, idle_timeout_ms): https://developers.openai.com/api/reference/resources/realtime — 18b. Realtime costs/truncation: https://developers.openai.com/api/docs/guides/realtime-costs
19. Rabbit OS3 launch: https://www.rabbit.tech/newsroom/rabbitos-3-launch ; OS3 FAQ: https://www.rabbit.tech/support/article/rabbitos-3
20. Rabbit terms (permission modes, DLAM as HID): https://www.rabbit.tech/terms-of-use ; rabbit agent: https://www.rabbit.tech/support/article/rabbit-agent
21. Rabbit OS3 launch video: https://www.youtube.com/watch?v=erZ-M5NM4A8
