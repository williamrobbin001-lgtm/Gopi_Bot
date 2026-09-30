"""handoff_to_stronger_model: send an oversized task to HANDOFF_MODEL as a background job.

The result is saved to a file in the output folder and summarized aloud.
"""
import json

from bot import config, jobs, llm
from bot.memory import memory_section
from bot.tools.base import CONFIRMED_PARAM, err, ok, tool

HANDOFF_INSTRUCTIONS = (
    "You are taking over a task that Gopi's voice assistant handed off because it is too "
    "large or hard for it. Do the task as completely as you can: produce the actual "
    "deliverable (plan, design, code, analysis), not advice about how to do it. "
    + llm.SPOKEN_INSTRUCTION
    + " The full answer is Markdown and will be saved to a file for Gopi."
)


def run_handoff(task: str, context: str) -> str:
    """Blocking: ask the stronger model, save its deliverable, return the spoken summary."""
    from bot.tools.files import create_document  # lazy: avoids import cycles at registration

    remembered = memory_section()
    prompt = "\n\n".join(
        part for part in (
            f"# Task\n{task}",
            f"# Conversation context\n{context}" if context.strip() else "",
            f"# What the assistant remembers about Gopi\n{remembered}" if remembered else "",
        ) if part
    )
    try:
        jobs.report_progress(f"{config.HANDOFF_MODEL} is working on it")
        answer = llm.complete(
            prompt,
            model=config.HANDOFF_MODEL_ID,
            instructions=HANDOFF_INSTRUCTIONS,
            reasoning_effort="high",
            timeout=max(60, config.JOB_TIMEOUT_SECONDS - 60),
        )
    except llm.LLMError as e:
        return err(f"handoff to {config.HANDOFF_MODEL} ({config.HANDOFF_MODEL_ID}) failed: {e}")
    spoken, body = llm.split_spoken(answer)
    saved = json.loads(create_document(
        format="md", filename=f"handoff {task[:60]}", title=task[:120],
        content=f"_Handled by {config.HANDOFF_MODEL} ({config.HANDOFF_MODEL_ID})._\n\n{body}\n",
    ))
    if not saved.get("ok"):
        return err(f"answer received but not saved: {saved.get('error')}", spoken_summary=spoken)
    return ok(spoken_summary=spoken, path=saved["path"], model=config.HANDOFF_MODEL)


@tool(
    "handoff_to_stronger_model",
    f"Hand a task to {config.HANDOFF_MODEL}, a much stronger model, when it is beyond you: work "
    "that would take a person more than a week alone, large multi-part builds, or a problem "
    "you've already failed on. Say you're handing it off before calling. Runs in the "
    "background; the result is saved to a file and you'll get a summary to speak. Put the "
    "relevant conversation (goals, constraints, what was tried) in context.",
    {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "The task, stated completely."},
            "context": {"type": "string", "description": "Relevant conversation context."},
            "confirmed": CONFIRMED_PARAM,
        },
        "required": ["task", "context"],
    },
)
def handoff_to_stronger_model(task: str, context: str = "") -> str:
    if not config.HANDOFF_ENABLED:
        return err("handoff is turned off (HANDOFF_ENABLED=false in .env)")
    task = (task or "").strip()
    if not task:
        return err("state the task to hand off")
    try:
        job = jobs.manager.start_sync(
            "handoff", f"{config.HANDOFF_MODEL}: {task[:60]}", lambda: run_handoff(task, context or "")
        )
        return ok(job_id=job.id, status="started", model=config.HANDOFF_MODEL,
                  note=f"Tell Gopi {config.HANDOFF_MODEL} is on it and you'll report back.")
    except Exception as e:
        return err(f"{type(e).__name__}: {e}")
