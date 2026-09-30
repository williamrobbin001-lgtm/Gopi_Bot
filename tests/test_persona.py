"""Persona: one name, tone, and voice across every response path."""
from bot import config, prompts
from bot.realtime_client import session_config


def test_persona_block_is_first_and_named():
    instructions = prompts.build_instructions()
    assert instructions.startswith("PERSONA\n")
    assert f"Your name is {config.PERSONA_NAME}" in instructions
    for trait in ("warm", "direct", "concise", "conversational", "Gopi", "markdown"):
        assert trait in instructions


def test_persona_covers_every_response_path():
    for path in ("greetings", "tool results", "errors", "background-job updates", "handoff"):
        assert path in prompts.PERSONA


def test_session_uses_configured_voice_and_persona():
    cfg = session_config()
    assert cfg["audio"]["output"]["voice"] == config.VOICE
    assert cfg["instructions"].startswith(prompts.PERSONA)


def test_memory_is_appended_after_persona_and_rules():
    text = prompts.build_instructions("## Known facts\n- likes tea")
    assert text.startswith(prompts.PERSONA) and text.rstrip().endswith("- likes tea")
    assert prompts.build_instructions("   ") == prompts.SYSTEM_PROMPT


def test_defaults_when_env_unset(monkeypatch):
    import importlib

    for var in ("PERSONA_NAME", "VOICE", "REALTIME_VOICE"):
        monkeypatch.setenv(var, "")
    fresh = importlib.reload(config)
    try:
        assert fresh.PERSONA_NAME == "Gopi Bot" and fresh.VOICE == "marin"
    finally:
        monkeypatch.undo()
        importlib.reload(config)
