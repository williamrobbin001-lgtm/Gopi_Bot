"""Permission modes: ask vs auto, destructive still asks, toggling via the tool."""
import asyncio
import json

import pytest

from bot import config, safety
from bot.dispatcher import dispatch
from bot.tools import computer, research


def call(name: str, **args) -> dict:
    return json.loads(asyncio.run(dispatch(name, json.dumps(args))))


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_FILE", tmp_path / "test-bot.log")
    monkeypatch.setattr(config, "CONFIRM_DESTRUCTIVE", True)
    monkeypatch.setattr(computer, "_launch", lambda target: None)
    monkeypatch.setattr(research.webbrowser, "open", lambda url: True)


def test_ask_mode_confirms_risky_actions(tmp_path):
    safety.set_mode("ask")
    for name, args in [
        ("run_shell", {"command": "echo hi", "cwd": str(tmp_path)}),
        ("write_file", {"path": str(tmp_path / "new.txt"), "content": "x"}),
        ("open_app", {"target": "notepad"}),
        ("open_url", {"url": "https://example.com"}),
    ]:
        r = call(name, **args)
        assert r.get("needs_confirmation") is True, name
    assert not (tmp_path / "new.txt").exists()


def test_ask_mode_runs_after_spoken_yes(tmp_path):
    safety.set_mode("ask")
    r = call("run_shell", command="echo hi", cwd=str(tmp_path), confirmed=True)
    assert r["ok"] and "hi" in r["stdout"]
    assert call("open_app", target="notepad", confirmed=True)["ok"]


def test_ask_mode_leaves_safe_tools_alone(tmp_path):
    safety.set_mode("ask")
    assert call("list_dir", path=str(tmp_path))["ok"]
    assert call("create_document", format="md", filename="n", content="x", folder=str(tmp_path))["ok"]


def test_auto_mode_acts_directly(tmp_path):
    safety.set_mode("auto")
    assert call("run_shell", command="echo hi", cwd=str(tmp_path))["ok"]
    assert call("write_file", path=str(tmp_path / "a.txt"), content="x")["ok"]
    assert call("open_app", target="notepad")["ok"]


def test_destructive_still_asks_in_auto_mode(tmp_path):
    safety.set_mode("auto")
    victim = tmp_path / "keep.txt"
    victim.write_text("x")
    r = call("run_shell", command=f"Remove-Item '{victim}'", cwd=str(tmp_path))
    assert r["needs_confirmation"] is True and victim.exists()


def test_destructive_setting_off_allows_in_auto(tmp_path, monkeypatch):
    safety.set_mode("auto")
    monkeypatch.setattr(config, "CONFIRM_DESTRUCTIVE", False)
    target = tmp_path / "x.txt"
    target.write_text("old")
    assert call("write_file", path=str(target), content="new", mode="overwrite")["ok"]


def test_toggle_by_tool():
    safety.set_mode("auto")
    r = call("set_permission_mode", mode="ask")
    assert r["ok"] and r["mode"] == "ask" and safety.get_mode() == "ask" and r["say"]
    # Switching to auto needs a spoken yes first...
    r = call("set_permission_mode", mode="auto")
    assert r["needs_confirmation"] is True and safety.get_mode() == "ask"
    # ...then it takes effect and says deletes still ask.
    r = call("set_permission_mode", mode="auto", confirmed=True)
    assert r["ok"] and safety.get_mode() == "auto" and "deleting" in r["say"]


def test_bad_mode():
    assert call("set_permission_mode", mode="yolo")["ok"] is False


def test_background_job_inherits_inner_tool_risk(tmp_path):
    safety.set_mode("ask")
    action = safety.confirmation_needed("start_background_job", {"kind": "run_shell", "args": {"command": "dir"}})
    assert action and "dir" in action
    assert safety.confirmation_needed("start_background_job", {"kind": "research", "args": {"question": "q"}}) is None
