"""Run any tool from the terminal, no voice or API key needed.

    python tools_cli.py list
    python tools_cli.py run_shell "{\"command\": \"Get-Date\"}"
    python tools_cli.py list_dir "{\"path\": \"~/Desktop\"}"

Uses the same dispatch() as the voice loop, including the confirmation guardrail.
"""
import asyncio
import json
import sys

from bot.dispatcher import dispatch
from bot.tools import TOOLS


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return 1
    if argv[1] == "list":
        for schema in TOOLS:
            params = schema["parameters"]
            required = set(params.get("required", []))
            args = ", ".join(
                name if name in required else f"{name}?" for name in params["properties"]
            )
            print(f"{schema['name']}({args})")
        return 0
    name, arguments = argv[1], (argv[2] if len(argv) > 2 else "{}")
    result = asyncio.run(dispatch(name, arguments))
    try:
        print(json.dumps(json.loads(result), indent=2, ensure_ascii=False))
    except ValueError:  # truncated output is no longer valid JSON
        print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
