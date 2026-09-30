"""One-shot text-model calls (OpenAI Responses API) for summaries, reasoning, and handoff.

Synchronous on purpose: callers run it in a worker thread (tools, jobs) or at
shutdown, never on the asyncio loop.
"""
import httpx

from bot import config

RESPONSES_URL = "https://api.openai.com/v1/responses"


class LLMError(Exception):
    """A readable failure (missing key, HTTP error, empty answer)."""


def complete(
    prompt: str,
    *,
    model: str,
    instructions: str | None = None,
    reasoning_effort: str | None = None,
    timeout: float = 120,
) -> str:
    if not config.OPENAI_API_KEY:
        raise LLMError("OPENAI_API_KEY is not set in .env")
    body: dict = {"model": model, "input": prompt}
    if instructions:
        body["instructions"] = instructions
    if reasoning_effort:
        body["reasoning"] = {"effort": reasoning_effort}
    try:
        r = httpx.post(
            RESPONSES_URL,
            json=body,
            headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
            timeout=timeout,
        )
    except httpx.TimeoutException:
        raise LLMError(f"{model} took longer than {int(timeout)} s") from None
    except httpx.HTTPError as e:
        raise LLMError(f"couldn't reach the OpenAI API: {type(e).__name__}") from None
    if r.status_code != 200:
        try:
            message = r.json().get("error", {}).get("message", "")
        except ValueError:
            message = ""
        raise LLMError(f"{model} returned HTTP {r.status_code}: {message[:200]}".rstrip(": "))
    text = output_text(r.json())
    if not text:
        raise LLMError(f"{model} returned an empty answer")
    return text


SPOKEN_MARKER = "SPOKEN SUMMARY:"
SPOKEN_INSTRUCTION = (
    f'Begin your reply with one line "{SPOKEN_MARKER} <2-3 plain sentences Gopi can hear '
    'spoken aloud, no markdown or URLs>", then a blank line, then the full answer.'
)


def split_spoken(text: str) -> tuple[str, str]:
    """(spoken summary, full body) from a reply that follows SPOKEN_INSTRUCTION."""
    stripped = text.strip()
    if stripped.upper().startswith(SPOKEN_MARKER):
        first, _, rest = stripped.partition("\n")
        return first[len(SPOKEN_MARKER):].strip(), rest.strip() or first[len(SPOKEN_MARKER):].strip()
    # No marker: speak the first paragraph, keep everything as the body.
    return stripped.split("\n\n", 1)[0][:600], stripped


def output_text(data: dict) -> str:
    """Concatenate the output_text parts of a Responses API result."""
    if isinstance(data.get("output_text"), str):
        return data["output_text"].strip()
    parts = [
        c.get("text", "")
        for item in data.get("output", [])
        if item.get("type") == "message"
        for c in item.get("content", [])
        if c.get("type") == "output_text"
    ]
    return "".join(parts).strip()
