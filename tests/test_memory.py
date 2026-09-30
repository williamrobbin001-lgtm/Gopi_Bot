"""Long-term memory: session summary save/load/fallback, fact store, remember/forget."""
import asyncio
import json
from datetime import datetime

import pytest

from bot import config, llm, prompts
from bot.dispatcher import dispatch
from bot.memory import Transcript, memory_section, recent_summaries_section, save_session, store


@pytest.fixture(autouse=True)
def memory_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MEMORY_DIR", tmp_path / "memory")
    monkeypatch.setattr(config, "LOG_FILE", tmp_path / "test-bot.log")
    return tmp_path / "memory"


def call(name: str, **args) -> dict:
    return json.loads(asyncio.run(dispatch(name, json.dumps(args))))


def sample_transcript() -> Transcript:
    t = Transcript()
    t.add("user", "Let's plan the Stage 5 test for my voice bot.")
    t.add("assistant", "Sure. I'll draft the checklist.")
    t.add("user", "  ")  # empty turns are ignored
    return t


# --- session summary ------------------------------------------------------------------

def test_save_session_uses_summary(monkeypatch, memory_dir):
    seen = {}

    def fake_complete(prompt, **kw):
        seen.update(kw, prompt=prompt)
        return "## Caller\n- Gopi\n## Worked on\n- Stage 5 plan\n## Open tasks\n- run tests\n## Decisions\n- none"

    monkeypatch.setattr(llm, "complete", fake_complete)
    path = save_session(sample_transcript(), now=datetime(2026, 9, 30, 9, 15, 0))
    assert path == memory_dir / "sessions" / "2026-09-30_09-15-00.md"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Call on 2026-09-30 09:15") and "Stage 5 plan" in text
    assert seen["model"] == config.SUMMARY_MODEL and "Gopi: Let's plan" in seen["prompt"]


def test_save_session_falls_back_to_raw_turns(monkeypatch):
    def broken(*a, **k):
        raise llm.LLMError("HTTP 500")

    monkeypatch.setattr(llm, "complete", broken)
    t = Transcript()
    for i in range(30):
        t.add("user", f"turn {i}")
    text = save_session(t).read_text(encoding="utf-8")
    assert "summary unavailable" in text
    assert "turn 29" in text and "turn 10" in text and "turn 9\n" not in text  # last 20 only


def test_empty_call_saves_nothing(monkeypatch, memory_dir):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("no call for empty transcript"))
    assert save_session(Transcript()) is None
    assert not (memory_dir / "sessions").exists()


def test_load_recent_summaries_newest_first_capped(memory_dir):
    folder = memory_dir / "sessions"
    folder.mkdir(parents=True)
    for day in range(1, 6):
        (folder / f"2026-09-0{day}_10-00-00.md").write_text(f"# Call on day {day}\n\n## Worked on\n- task {day}\n")
    section = recent_summaries_section(count=3, max_words=300)
    assert section.startswith("### Previous calls")
    assert section.index("day 5") < section.index("day 4") < section.index("day 3")
    assert "day 2" not in section
    long = recent_summaries_section(count=1, max_words=5)
    assert long.endswith("...") and len(long.split()) < 20


def test_empty_memory_boot():
    assert recent_summaries_section() == "" and store.facts_section() == ""
    assert memory_section() == ""
    assert prompts.build_instructions(memory_section()) == prompts.SYSTEM_PROMPT


def test_boot_instructions_include_memory(memory_dir):
    (memory_dir / "sessions").mkdir(parents=True)
    (memory_dir / "sessions" / "2026-09-29_10-00-00.md").write_text("# Call\n\n## Open tasks\n- finish Stage 5\n")
    store.add_fact("Gopi prefers Word reports.", "preference")
    text = prompts.build_instructions(memory_section())
    assert "Previous calls" in text and "finish Stage 5" in text
    assert "## Known facts" in text and "(preference) Gopi prefers Word reports." in text


# --- Fix 2: memory is private context, never recited at startup ---------------------------

def test_memory_block_wrapped_with_do_not_recite_rules(memory_dir):
    (memory_dir / "sessions").mkdir(parents=True)
    (memory_dir / "sessions" / "2026-09-29_10-00-00.md").write_text("# Call\n\n## Worked on\n- AI governance research\n")
    store.add_fact("Gopi's project is named Gopi Project.", "project")
    section = memory_section()
    rules = (
        "This is private background memory. Do not recite, list, or summarize it unprompted.",
        "Use it silently to answer questions and personalize replies.",
        "Only talk about past sessions when Gopi asks about them",
    )
    for rule in rules:
        assert rule in section
    # Memory content sits inside the private block, after the rules.
    start, end = section.index("<private_memory>"), section.index("</private_memory>")
    assert start < section.index("AI governance research") < end
    assert start < section.index("Gopi Project") < end
    assert section.index(rules[0]) < start
    assert section in prompts.build_instructions(section)


def test_greeting_contains_no_memory(memory_dir):
    import asyncio

    from bot.realtime_client import RealtimeClient

    (memory_dir / "sessions").mkdir(parents=True)
    (memory_dir / "sessions" / "2026-09-29_10-00-00.md").write_text("# Call\n\n## Worked on\n- SECRET_TOPIC_X\n")
    store.add_fact("FACT_MARKER_Y", "project")

    class Quiet:
        def play(self, *a): pass
        def clear(self): return None

    client = RealtimeClient(mic=None, speaker=Quiet(), instructions=prompts.build_instructions(memory_section()))
    client.sent = []

    async def fake_send(event):
        client.sent.append(event)

    client.send = fake_send

    async def scenario():
        await client._handle({"type": "session.updated"})
        while client._tasks:
            await asyncio.gather(*list(client._tasks))

    asyncio.run(scenario())
    greeting_events = json.dumps(client.sent)
    assert [e["type"] for e in client.sent] == ["conversation.item.create", "response.create"]
    assert "SECRET_TOPIC_X" not in greeting_events and "FACT_MARKER_Y" not in greeting_events
    assert "instructions" not in client.sent[1]  # no per-response override carrying memory
    assert "Do not mention previous calls" in prompts.GREETING_PROMPT
    assert "SECRET_TOPIC_X" in client.instructions  # still available to answer questions


def test_raw_transcript_fallback_is_condensed(memory_dir, monkeypatch):
    def broken(*a, **k):
        raise llm.LLMError("down")

    monkeypatch.setattr(llm, "complete", broken)
    t = Transcript()
    for i in range(20):
        t.add("user", f"turn{i} " + "word " * 80)
    save_session(t)
    section = recent_summaries_section()
    assert "turn19" in section and "turn14" in section and "turn13" not in section  # last 6 only
    assert "Last few lines" in section and "Raw transcript" not in section
    assert len(section.split()) < 6 * 30 + 40  # each turn cut to ~25 words


def test_oversized_summaries_trimmed(memory_dir):
    folder = memory_dir / "sessions"
    folder.mkdir(parents=True)
    for day in range(1, 4):
        (folder / f"2026-09-0{day}_10-00-00.md").write_text("# Call\n\n" + "longword " * 1000)
    assert len(recent_summaries_section().split()) <= config.MEMORY_MAX_WORDS + 20


# --- fact store + tools ------------------------------------------------------------------

def test_remember_dedupes_and_persists(memory_dir):
    assert call("remember", fact="Gopi uses Windows 10.", category="project")["saved"] is True
    again = call("remember", fact="gopi uses windows 10", category="preference")
    assert again["ok"] and again["saved"] is False
    data = json.loads((memory_dir / "facts.json").read_text(encoding="utf-8"))
    assert data["project"] == ["Gopi uses Windows 10."] and data["preference"] == []


def test_remember_rejects_bad_category():
    r = call("remember", fact="x", category="gossip")
    assert r["ok"] is False and "category" in r["error"]


def test_forget_exact_and_partial():
    store.add_fact("Gopi's manager is Priya.", "person")
    store.add_fact("Reports go on the desktop.", "preference")
    assert call("forget", fact="reports go on the desktop")["forgot"] == "Reports go on the desktop."
    assert call("forget", fact="manager")["forgot"] == "Gopi's manager is Priya."
    assert call("forget", fact="nothing like this")["ok"] is False
    assert store.facts_section() == ""


def test_forget_ambiguous_partial_asks():
    store.add_fact("Likes tea in the morning.", "preference")
    store.add_fact("Likes tea after lunch.", "preference")
    assert call("forget", fact="likes tea")["ok"] is False


def test_corrupt_facts_file_is_ignored(memory_dir):
    memory_dir.mkdir()
    (memory_dir / "facts.json").write_text("{not json")
    assert store.load_facts() == {c: [] for c in store.CATEGORIES}


# --- transcript capture from Realtime events ----------------------------------------------

def test_client_records_both_sides():
    from bot.realtime_client import RealtimeClient

    class Quiet:
        def play(self, *a): pass
        def clear(self): return None

    client = RealtimeClient(mic=None, speaker=Quiet())

    async def scenario():
        await client._handle({"type": "conversation.item.input_audio_transcription.completed", "transcript": "hello there"})
        await client._handle({"type": "response.output_audio_transcript.done", "transcript": "Hi Gopi!"})

    asyncio.run(scenario())
    assert client.transcript.turns == [("user", "hello there"), ("assistant", "Hi Gopi!")]


def test_llm_output_text_parsing():
    data = {"output": [{"type": "reasoning"}, {"type": "message", "content": [
        {"type": "output_text", "text": "Hello "}, {"type": "output_text", "text": "world"}]}]}
    assert llm.output_text(data) == "Hello world"
