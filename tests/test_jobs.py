"""Background jobs: start/status/cancel, progress + completion notes, never over Gopi."""
import asyncio
import json
import time

import pytest

from bot import config, jobs
from bot.dispatcher import dispatch
from bot.realtime_client import RealtimeClient


@pytest.fixture(autouse=True)
def fresh_manager(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_FILE", tmp_path / "test-bot.log")
    manager = jobs.JobManager()
    monkeypatch.setattr(jobs, "manager", manager)
    import bot.tools.jobs_tools as jt
    monkeypatch.setattr(jt, "manager", manager)
    return manager


def attach_collector(manager) -> list[str]:
    notes: list[str] = []

    async def notify(note: str) -> None:
        notes.append(note)

    manager.attach(asyncio.get_running_loop(), notify)
    return notes


async def call(name: str, **args) -> dict:
    return json.loads(await dispatch(name, json.dumps(args)))


async def wait_jobs(manager, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while any(j.status == "running" for j in manager.jobs.values()):
        assert time.monotonic() < deadline, "job did not finish"
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.05)


def test_start_background_job_returns_immediately_then_announces(fresh_manager, tmp_path):
    async def scenario():
        notes = attach_collector(fresh_manager)
        r = await call("start_background_job", kind="list_dir", args={"path": str(tmp_path)})
        assert r["ok"] and r["status"] == "started" and r["job_id"] == "job-1"
        await wait_jobs(fresh_manager)
        return notes

    notes = asyncio.run(scenario())
    assert len(notes) == 1 and "finished" in notes[0] and "That's done:" in notes[0]
    assert fresh_manager.jobs["job-1"].status == "done"


def test_unknown_kind_rejected(fresh_manager):
    async def scenario():
        attach_collector(fresh_manager)
        return await call("start_background_job", kind="launch_rocket", args={})

    assert asyncio.run(scenario())["ok"] is False


def test_failed_job_says_what_went_wrong(fresh_manager, tmp_path):
    async def scenario():
        notes = attach_collector(fresh_manager)
        await call("start_background_job", kind="read_file", args={"path": str(tmp_path / "nope.txt")})
        await wait_jobs(fresh_manager)
        return notes

    notes = asyncio.run(scenario())
    assert "failed" in notes[0] and 'Do not say "done"' in notes[0] and "reason" in notes[0]


def test_status_and_cancel(fresh_manager):
    async def scenario():
        attach_collector(fresh_manager)
        job = fresh_manager.start("slow", "slow thing", lambda: asyncio.sleep(30, result="late"))
        await asyncio.sleep(0.05)
        running = await call("job_status", job_id=job.id)
        cancelled = await call("cancel_job", job_id=job.id)
        await asyncio.sleep(0.05)
        again = await call("cancel_job", job_id=job.id)
        everything = await call("job_status")
        return running, cancelled, again, everything

    running, cancelled, again, everything = asyncio.run(scenario())
    assert running["jobs"][0]["status"] == "running"
    assert cancelled["ok"] and again["ok"] is False
    assert everything["jobs"][0]["status"] == "cancelled"


def test_progress_note_after_threshold(fresh_manager, monkeypatch):
    monkeypatch.setattr(config, "JOB_PROGRESS_AFTER_SECONDS", 0.1)

    def work() -> str:
        jobs.report_progress("searched 3 queries")
        time.sleep(0.4)
        return "all done"

    async def scenario():
        notes = attach_collector(fresh_manager)
        fresh_manager.start_sync("deep", "deep research", work)
        await wait_jobs(fresh_manager)
        return notes

    notes = asyncio.run(scenario())
    assert "Progress" in notes[0] and "searched 3 queries" in notes[0]
    assert "finished" in notes[-1] and "all done" in notes[-1]


def test_no_progress_note_for_quick_jobs(fresh_manager):
    async def scenario():
        notes = attach_collector(fresh_manager)
        fresh_manager.start_sync("quick", "quick", lambda: "fine")
        await wait_jobs(fresh_manager)
        return notes

    notes = asyncio.run(scenario())
    assert len(notes) == 1 and "finished" in notes[0]


def test_job_timeout(fresh_manager, monkeypatch):
    monkeypatch.setattr(config, "JOB_TIMEOUT_SECONDS", 0.1)

    async def scenario():
        notes = attach_collector(fresh_manager)
        fresh_manager.start("slow", "slow", lambda: asyncio.sleep(5))
        await wait_jobs(fresh_manager)
        return notes

    notes = asyncio.run(scenario())
    assert "failed" in notes[0] and "timed out" in notes[0]


# --- the client never talks over Gopi ------------------------------------------------------

class Quiet:
    def play(self, *a): pass
    def clear(self): return None


def make_client(monkeypatch):
    import bot.realtime_client as rc
    monkeypatch.setattr(rc, "QUIET_BEFORE_UPDATE_SECONDS", 0.1)
    client = RealtimeClient(mic=None, speaker=Quiet())
    client.sent = []

    async def fake_send(event):
        client.sent.append(event)

    client.send = fake_send
    return client


def test_update_waits_while_gopi_speaks(monkeypatch):
    client = make_client(monkeypatch)

    async def scenario():
        deliverer = asyncio.create_task(client._deliver_updates())
        await client._handle({"type": "input_audio_buffer.speech_started"})
        await client.notify("Background job job-1 finished.")
        await asyncio.sleep(0.4)
        held = list(client.sent)
        await client._handle({"type": "input_audio_buffer.speech_stopped"})
        await asyncio.sleep(0.4)
        deliverer.cancel()
        return held

    held = asyncio.run(scenario())
    assert held == []  # nothing said while Gopi was talking
    assert [e["type"] for e in client.sent] == ["conversation.item.create", "response.create"]
    assert "job-1 finished" in client.sent[0]["item"]["content"][0]["text"]


def test_update_waits_for_active_response(monkeypatch):
    client = make_client(monkeypatch)

    async def scenario():
        deliverer = asyncio.create_task(client._deliver_updates())
        await client._handle({"type": "response.created", "response": {"id": "r1"}})
        await client.notify("Progress note")
        await asyncio.sleep(0.3)
        held = list(client.sent)
        await client._handle({"type": "response.done", "response": {"id": "r1", "status": "completed"}})
        await asyncio.sleep(0.3)
        deliverer.cancel()
        return held

    held = asyncio.run(scenario())
    assert held == [] and client.sent[-1] == {"type": "response.create"}


# --- Fix 1: never two response.create calls at once ------------------------------------------

def creates(client) -> int:
    return sum(e["type"] == "response.create" for e in client.sent)


def test_tool_followup_and_job_notice_never_overlap(monkeypatch):
    """The bot.log race: a tool follow-up and a job notice both wanted to speak."""
    client = make_client(monkeypatch)

    async def scenario():
        deliverer = asyncio.create_task(client._deliver_updates())
        await client.notify("Background job job-1 finished.")
        followup = asyncio.create_task(client._create_response())
        await asyncio.sleep(0.4)
        first = creates(client)  # only one may go out before the server answers
        await client._handle({"type": "response.created", "response": {"id": "r1"}})
        await asyncio.sleep(0.2)
        during = creates(client)
        await client._handle({"type": "response.done", "response": {"id": "r1", "status": "completed"}})
        await asyncio.sleep(0.4)
        deliverer.cancel()
        await followup
        return first, during

    first, during = asyncio.run(scenario())
    assert first == 1 and during == 1
    assert creates(client) == 2  # the second one only after response.done


def test_rejected_create_releases_the_gate(monkeypatch):
    client = make_client(monkeypatch)

    async def scenario():
        await client._create_response()
        await client._handle({"type": "error", "error": {"code": "conversation_already_has_active_response"}})
        await asyncio.wait_for(client._create_response(), 1)  # must not hang

    asyncio.run(scenario())
    assert creates(client) == 2


def test_job_crash_logs_traceback(fresh_manager, caplog):
    def explode() -> str:
        raise ValueError("bad page bytes")

    async def scenario():
        notes = attach_collector(fresh_manager)
        fresh_manager.start_sync("deep_research", "deep", explode)
        await wait_jobs(fresh_manager)
        return notes

    notes = asyncio.run(scenario())
    assert "Traceback" in caplog.text and "bad page bytes" in caplog.text
    assert "failed" in notes[0] and "bad page bytes" in notes[0]
