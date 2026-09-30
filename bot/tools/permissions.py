"""set_permission_mode: Gopi's spoken on/off switch for confirmations."""
from bot import config, safety
from bot.tools.base import CONFIRMED_PARAM, err, ok, tool

_SPOKEN = {
    "ask": "I'll ask before running commands, changing files, opening things, or sending data out.",
    "auto": "I'll act without asking first.",
}


@tool(
    "set_permission_mode",
    "Switch confirmations on or off when Gopi asks. mode='ask' (\"ask me before doing things\", "
    "\"turn confirmations on\") or mode='auto' (\"turn off confirmations\", \"just do it\"). "
    "Say the new mode aloud afterwards. Deletes and system changes still ask in auto mode.",
    {
        "type": "object",
        "properties": {
            # Literal, not safety.MODES: safety imports this package, so it may be mid-import.
            "mode": {"type": "string", "enum": ["ask", "auto"]},
            "confirmed": CONFIRMED_PARAM,
        },
        "required": ["mode"],
    },
)
def set_permission_mode(mode: str) -> str:
    mode = (mode or "").strip().lower()
    if mode not in safety.MODES:
        return err(f"unknown mode {mode!r}; use 'ask' or 'auto'")
    safety.set_mode(mode)
    note = _SPOKEN[mode]
    if mode == "auto" and config.CONFIRM_DESTRUCTIVE:
        note += " I'll still check with you before deleting things or changing system settings."
    return ok(mode=mode, say=note)
