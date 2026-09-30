"""think_deeply: hand hard thinking to a strong reasoning text model, as a background job."""
from bot import config, jobs, llm
from bot.tools.base import err, ok, tool

THINK_INSTRUCTIONS = (
    "You are the deep-reasoning engine behind Gopi's voice assistant. Think the problem "
    "through carefully, then answer for the ear: " + llm.SPOKEN_INSTRUCTION + " Keep the "
    "full answer under 250 words: the recommendation first, then the key reasons or steps."
)


def solve(problem: str) -> str:
    """Blocking: ask REASONING_MODEL (high effort) and return a JSON result."""
    try:
        jobs.report_progress("thinking it through")
        answer = llm.complete(
            problem,
            model=config.REASONING_MODEL,
            instructions=THINK_INSTRUCTIONS,
            reasoning_effort="high",
            timeout=max(60, config.JOB_TIMEOUT_SECONDS - 30),
        )
        spoken, full = llm.split_spoken(answer)
        return ok(spoken_answer=spoken, full_answer=full, model=config.REASONING_MODEL)
    except llm.LLMError as e:
        return err(f"deep thinking failed: {e}")


@tool(
    "think_deeply",
    "Hand a hard problem to a strong reasoning model: multi-step analysis, planning, math, "
    "or hard trade-offs. Runs in the background; you'll get the answer as a note to speak. "
    "Put everything relevant into problem (goal, constraints, numbers, what Gopi said).",
    {
        "type": "object",
        "properties": {"problem": {"type": "string", "description": "The full problem with context."}},
        "required": ["problem"],
    },
)
def think_deeply(problem: str) -> str:
    problem = (problem or "").strip()
    if not problem:
        return err("describe the problem to think about")
    try:
        job = jobs.manager.start_sync("think_deeply", f"thinking: {problem[:60]}", lambda: solve(problem))
        return ok(job_id=job.id, status="started", note="Tell Gopi you're thinking it through.")
    except Exception as e:
        return err(f"{type(e).__name__}: {e}")
