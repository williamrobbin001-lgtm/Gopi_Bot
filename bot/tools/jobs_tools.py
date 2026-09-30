"""start_background_job / job_status / cancel_job."""
import json

from bot.jobs import manager
from bot.tools.base import CONFIRMED_PARAM, err, ok, tool

_NOT_JOBS = {"start_background_job", "job_status", "cancel_job"}
_SELF_BACKGROUNDING = {"think_deeply", "handoff_to_stronger_model"}


def _starts_own_job(kind: str, args: dict) -> bool:
    return kind in _SELF_BACKGROUNDING or (kind == "research" and args.get("mode") == "deep")


@tool(
    "start_background_job",
    "Run a slow tool in the background so the conversation can continue: e.g. research, "
    "create_document for a large file, or a long run_shell. kind is the tool name and args "
    "its arguments. Returns a job_id right away; you'll get a progress note and a 'finished' "
    "note to speak later. Before starting, say one short sentence like 'On it, give me a "
    "moment' and offer to keep chatting.",
    {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "description": "Tool to run, e.g. 'research'."},
            "args": {"type": "object", "description": "That tool's arguments."},
            "confirmed": CONFIRMED_PARAM,
        },
        "required": ["kind", "args"],
    },
)
def start_background_job(kind: str, args: dict | None = None) -> str:
    from bot.dispatcher import dispatch  # lazy: dispatcher imports the tool registry
    from bot.tools import HANDLERS

    try:
        if kind in _NOT_JOBS or kind not in HANDLERS:
            return err(f"unknown job kind {kind!r}; use a tool name like 'research'")
        args = dict(args or {})
        if _starts_own_job(kind, args):
            # These tools already run as exactly one background job; wrapping them would
            # create a second job that "finishes" instantly. Hand straight over.
            args.pop("confirmed", None)
            return HANDLERS[kind](**args)
        # This call already passed the permission check for the inner tool (bot/safety.py).
        inner = json.dumps({**args, "confirmed": True})
        label = f"{kind} " + ", ".join(f"{k}={str(v)[:40]}" for k, v in args.items())
        job = manager.start(kind, label.strip(), lambda: dispatch(kind, inner))
        return ok(job_id=job.id, status="started",
                  note="The job has STARTED, not finished. Say you're on it; the result comes later.")
    except Exception as e:
        return err(f"{type(e).__name__}: {e}")


@tool(
    "job_status",
    "Check background jobs: one by job_id, or all of them if omitted.",
    {"type": "object", "properties": {"job_id": {"type": "string"}}},
)
def job_status(job_id: str | None = None) -> str:
    jobs = manager.status(job_id)
    if job_id and not jobs:
        return err(f"no job {job_id}")
    return ok(jobs=jobs)


@tool(
    "cancel_job",
    "Cancel a running background job when Gopi asks to stop it.",
    {"type": "object", "properties": {"job_id": {"type": "string"}}, "required": ["job_id"]},
)
def cancel_job(job_id: str) -> str:
    if manager.cancel(job_id):
        return ok(cancelled=job_id)
    return err(f"{job_id} isn't a running job")
