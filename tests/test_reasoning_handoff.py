"""think_deeply, deep research, and the handoff: all background jobs, all mocked."""
import asyncio
import json
import time
from pathlib import Path

import httpx
import pytest

from bot import config, jobs, llm
from bot.dispatcher import dispatch
from bot.tools import handoff, reasoning, research, web_utils


@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_FILE", tmp_path / "test-bot.log")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "MEMORY_DIR", tmp_path / "memory")
    manager = jobs.JobManager()
    monkeypatch.setattr(jobs, "manager", manager)
    return manager


def run_job(manager, name: str, **args) -> tuple[dict, list[str]]:
    """Call a tool that starts a job; wait for it; return (tool result, spoken notes)."""

    async def scenario():
        notes: list[str] = []

        async def notify(note):
            notes.append(note)

        manager.attach(asyncio.get_running_loop(), notify)
        started = json.loads(await dispatch(name, json.dumps(args)))
        deadline = time.monotonic() + 10
        while any(j.status == "running" for j in manager.jobs.values()):
            assert time.monotonic() < deadline
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.05)
        return started, notes

    return asyncio.run(scenario())


# --- think_deeply ---------------------------------------------------------------------

def test_think_deeply_uses_reasoning_model_high_effort(setup, monkeypatch):
    seen = {}

    def fake(prompt, **kw):
        seen.update(kw, prompt=prompt)
        return "SPOKEN SUMMARY: Do plan B; it costs less and ships sooner.\n\n## Why\n- cheaper\n- faster"

    monkeypatch.setattr(llm, "complete", fake)
    started, notes = run_job(setup, "think_deeply", problem="Plan A or plan B for launch?")
    assert started["status"] == "started"
    assert seen["model"] == config.REASONING_MODEL and seen["reasoning_effort"] == "high"
    assert "Plan A or plan B" in seen["prompt"]
    assert "That's done:" in notes[-1] and "Do plan B" in notes[-1]


def test_think_deeply_failure_is_spoken_calmly(setup, monkeypatch):
    def broken(*a, **k):
        raise llm.LLMError("HTTP 500")

    monkeypatch.setattr(llm, "complete", broken)
    _, notes = run_job(setup, "think_deeply", problem="hard")
    assert "failed" in notes[-1] and "HTTP 500" in notes[-1]


def test_think_deeply_empty_problem():
    assert json.loads(reasoning.think_deeply("  "))["ok"] is False


def test_split_spoken():
    assert llm.split_spoken("SPOKEN SUMMARY: Hi there.\n\nBody") == ("Hi there.", "Body")
    spoken, body = llm.split_spoken("No marker here.\n\nMore.")
    assert spoken == "No marker here." and body.endswith("More.")


# --- deep research ----------------------------------------------------------------------

ARTICLE = ("<html><head><title>{t}</title></head><body><article>"
           + "<p>Realtime voice models reduce latency for spoken agents in many products today.</p>" * 6
           + "</article></body></html>")


def test_deep_research_writes_sourced_report(setup, monkeypatch):
    monkeypatch.setattr(config, "TAVILY_API_KEY", "tvly-test")
    web_utils.cache_clear()
    monkeypatch.setattr(web_utils, "RETRY_BACKOFF_SECONDS", 0)

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith(research.TAVILY_URL):
            q = json.loads(request.content)["query"]
            return httpx.Response(200, json={"results": [
                {"title": f"{q} A", "url": f"https://a.com/{len(q)}", "content": "snippet"},
                {"title": f"{q} B", "url": f"https://b.org/{len(q)}", "content": "snippet"},
            ]})
        return httpx.Response(200, text=ARTICLE.format(t=url), headers={"content-type": "text/html"})

    monkeypatch.setattr(web_utils, "_client", httpx.Client(transport=httpx.MockTransport(handler)))
    calls = []

    def fake(prompt, **kw):
        calls.append(kw)
        if "JSON array" in kw.get("instructions", ""):
            return '["voice latency 2026", "realtime model benchmarks"]'
        assert "[1]" in prompt and "untrusted" in kw["instructions"]
        return "SPOKEN SUMMARY: Latency is dropping fast, per four sources.\n\n## Summary\nFaster [1][2]."

    monkeypatch.setattr(llm, "complete", fake)
    started, notes = run_job(setup, "research", question="How fast are realtime voice models?", mode="deep")
    assert started["status"] == "started" and started["job_id"]
    result_note = notes[-1]
    assert "That's done:" in result_note and "Latency is dropping fast" in result_note
    reports = list((config.OUTPUT_DIR).glob("research-*.md"))
    assert len(reports) == 1
    text = reports[0].read_text(encoding="utf-8")
    assert "## Summary" in text and "## Sources" in text and "https://a.com/" in text
    assert len(calls) == 2  # one planning call, one synthesis call
    web_utils.cache_clear()


def test_deep_research_without_keys_fails_clearly(setup, monkeypatch):
    monkeypatch.setattr(config, "TAVILY_API_KEY", "")
    monkeypatch.setattr(config, "BRAVE_API_KEY", "")
    monkeypatch.setattr(llm, "complete", lambda *a, **k: '["q"]')
    _, notes = run_job(setup, "research", question="anything", mode="deep")
    assert "failed" in notes[-1] and "TAVILY_API_KEY" in notes[-1]


def test_quick_research_still_default(setup, monkeypatch):
    monkeypatch.setattr(config, "TAVILY_API_KEY", "")
    monkeypatch.setattr(config, "BRAVE_API_KEY", "")
    r = json.loads(research.research("q"))
    assert r["ok"] is False and "job_id" not in r  # quick mode answers inline


# --- handoff ------------------------------------------------------------------------------

def test_handoff_sends_task_context_memory_and_saves_file(setup, monkeypatch):
    from bot.memory import store

    store.add_fact("Gopi builds on Windows.", "project")
    seen = {}

    def fake(prompt, **kw):
        seen.update(kw, prompt=prompt)
        return "SPOKEN SUMMARY: The full build plan is ready, in six phases.\n\n# Plan\n1. Phase one"

    monkeypatch.setattr(llm, "complete", fake)
    started, notes = run_job(setup, "handoff_to_stronger_model",
                             task="Design a full home-automation platform", context="Gopi wants it local-only.")
    assert started["status"] == "started" and started["model"] == config.HANDOFF_MODEL
    assert seen["model"] == config.HANDOFF_MODEL_ID == "gpt-6-luna"
    for part in ("Design a full home-automation platform", "local-only", "Gopi builds on Windows."):
        assert part in seen["prompt"]
    assert "That's done:" in notes[-1] and "six phases" in notes[-1]
    [saved] = list(config.OUTPUT_DIR.glob("handoff-*.md"))
    assert "Phase one" in saved.read_text(encoding="utf-8")


def test_handoff_disabled(monkeypatch):
    monkeypatch.setattr(config, "HANDOFF_ENABLED", False)
    r = json.loads(handoff.handoff_to_stronger_model("big task", "ctx"))
    assert r["ok"] is False and "HANDOFF_ENABLED" in r["error"]


def test_handoff_asks_first_in_ask_mode():
    from bot import safety

    safety.set_mode("ask")
    action = safety.confirmation_needed("handoff_to_stronger_model", {"task": "t", "context": "c"})
    assert action and config.HANDOFF_MODEL in action


def test_handoff_error_mentions_model_id(setup, monkeypatch):
    def broken(*a, **k):
        raise llm.LLMError("gpt-6-luna returned HTTP 404: model not found")

    monkeypatch.setattr(llm, "complete", broken)
    _, notes = run_job(setup, "handoff_to_stronger_model", task="t", context="c")
    assert "failed" in notes[-1] and "gpt-6-luna" in notes[-1]


def test_prompt_names_handoff_model():
    from bot import prompts

    assert "{handoff}" not in prompts.SYSTEM_PROMPT
    assert f"Hand off to {config.HANDOFF_MODEL}" in prompts.SYSTEM_PROMPT
