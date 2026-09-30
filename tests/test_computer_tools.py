"""Computer-access tools, safety check, and dispatcher. No API key or audio needed."""
import asyncio
import json
import sys

import pytest

from bot import config, safety
from bot.dispatcher import dispatch, redact
from bot.tools import HANDLERS, TOOLS, computer

IS_WINDOWS = sys.platform == "win32"


def call(name: str, **args) -> dict:
    return json.loads(asyncio.run(dispatch(name, json.dumps(args))))


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Keep test logs out of the real bot.log and reset remembered cwd."""
    monkeypatch.setattr(config, "LOG_FILE", tmp_path / "test-bot.log")
    monkeypatch.setattr(config, "CONFIRM_DESTRUCTIVE", True)
    monkeypatch.setattr(computer, "_last_cwd", None)


# --- registry -----------------------------------------------------------------

def test_registry_has_five_tools_with_schemas():
    names = {t["name"] for t in TOOLS}
    assert {"run_shell", "read_file", "write_file", "list_dir", "open_app"} <= names
    assert names == set(HANDLERS)
    for schema in TOOLS:
        assert schema["type"] == "function"
        assert schema["parameters"]["type"] == "object"


# --- run_shell ----------------------------------------------------------------

def test_run_shell_echo(tmp_path):
    r = call("run_shell", command="echo hello", cwd=str(tmp_path))
    assert r["ok"] and r["exit_code"] == 0
    assert "hello" in r["stdout"]


def test_run_shell_failure_returns_stderr(tmp_path):
    cmd = "Write-Error boom; exit 3" if IS_WINDOWS else "echo boom >&2; exit 3"
    r = call("run_shell", command=cmd, cwd=str(tmp_path))
    assert r["ok"] is False and r["exit_code"] == 3
    assert "boom" in r["stderr"]


def test_run_shell_timeout(tmp_path):
    cmd = "Start-Sleep -Seconds 20" if IS_WINDOWS else "sleep 20"
    r = call("run_shell", command=cmd, cwd=str(tmp_path), timeout_seconds=3)
    assert r["ok"] is False and "timed out" in r["error"]


def test_run_shell_remembers_cwd(tmp_path):
    call("run_shell", command="echo hi", cwd=str(tmp_path))
    r = call("run_shell", command="echo again")
    assert r["cwd"] == str(tmp_path)


def test_run_shell_destructive_needs_confirmation(tmp_path):
    victim = tmp_path / "keep.txt"
    victim.write_text("x")
    r = call("run_shell", command=f"Remove-Item '{victim}'", cwd=str(tmp_path))
    assert r["needs_confirmation"] is True and "action" in r
    assert victim.exists()


# --- read_file ----------------------------------------------------------------

def test_read_file_content(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello world", encoding="utf-8")
    r = call("read_file", path=str(f))
    assert r["ok"] and r["content"] == "hello world" and r["truncated"] is False


def test_read_file_truncates(tmp_path):
    f = tmp_path / "big.txt"
    f.write_text("x" * 5000)
    r = call("read_file", path=str(f), max_chars=100)
    assert len(r["content"]) == 100 and r["truncated"] and r["total_chars"] == 5000


def test_read_file_start_line(tmp_path):
    f = tmp_path / "lines.txt"
    f.write_text("one\ntwo\nthree\n")
    assert call("read_file", path=str(f), start_line=2)["content"] == "two\nthree\n"


def test_read_file_rejects_binary(tmp_path):
    f = tmp_path / "b.bin"
    f.write_bytes(b"\x00\x01\x02binary")
    r = call("read_file", path=str(f))
    assert r["ok"] is False and "binary" in r["error"]


def test_read_file_missing_is_calm_error(tmp_path):
    r = call("read_file", path=str(tmp_path / "nope.txt"))
    assert r["ok"] is False and "not found" in r["error"]


# --- write_file ---------------------------------------------------------------

def test_write_file_creates_with_parents(tmp_path):
    target = tmp_path / "sub" / "new.txt"
    r = call("write_file", path=str(target), content="hi")
    assert r["ok"] and target.read_text() == "hi" and r["bytes_written"] == 2


def test_write_file_create_refuses_existing(tmp_path):
    target = tmp_path / "x.txt"
    target.write_text("old")
    r = call("write_file", path=str(target), content="new")
    assert r["ok"] is False and "exists" in r["error"]
    assert target.read_text() == "old"


def test_write_file_append(tmp_path):
    target = tmp_path / "log.txt"
    target.write_text("a")
    assert call("write_file", path=str(target), content="b", mode="append")["ok"]
    assert target.read_text() == "ab"


def test_write_file_overwrite_needs_confirmation(tmp_path):
    target = tmp_path / "x.txt"
    target.write_text("old")
    r = call("write_file", path=str(target), content="new", mode="overwrite")
    assert r["needs_confirmation"] is True
    assert target.read_text() == "old"
    r = call("write_file", path=str(target), content="new", mode="overwrite", confirmed=True)
    assert r["ok"] and target.read_text() == "new"


def test_guardrail_off_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIRM_DESTRUCTIVE", False)
    target = tmp_path / "x.txt"
    target.write_text("old")
    assert call("write_file", path=str(target), content="new", mode="overwrite")["ok"]


# --- list_dir -----------------------------------------------------------------

def test_list_dir_folders_first_and_pattern(tmp_path):
    (tmp_path / "b.pdf").write_text("x")
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "zfolder").mkdir()
    (tmp_path / ".hidden").write_text("x")

    r = call("list_dir", path=str(tmp_path))
    assert [e["name"] for e in r["entries"]] == ["zfolder", "a.txt", "b.pdf"]
    assert r["total"] == 3 and r["truncated"] is False

    r = call("list_dir", path=str(tmp_path), pattern="*.pdf")
    assert [e["name"] for e in r["entries"]] == ["b.pdf"]

    r = call("list_dir", path=str(tmp_path), show_hidden=True)
    assert ".hidden" in [e["name"] for e in r["entries"]]


def test_list_dir_missing(tmp_path):
    assert call("list_dir", path=str(tmp_path / "missing"))["ok"] is False


# --- open_app (mocked: never launches anything) ---------------------------------

def test_open_app_mocked(monkeypatch):
    launched = []
    monkeypatch.setattr(computer, "_launch", lambda target: launched.append(target))
    r = call("open_app", target="notepad")
    assert r["ok"] and r["opened"] == "notepad" and launched == ["notepad"]


def test_open_app_reports_launch_error(monkeypatch):
    monkeypatch.setattr(computer, "_launch", lambda target: "not found")
    r = call("open_app", target="nosuchapp")
    assert r["ok"] is False and "not found" in r["error"]


# --- safety -------------------------------------------------------------------

@pytest.mark.parametrize(
    "command",
    [
        "Remove-Item x",
        "rm -rf y",
        "git push --force",
        "git push origin main -f",
        "git reset --hard HEAD~1",
        "del C:\\temp\\a.txt",
        "Stop-Process -Name chrome",
        "shutdown /s /t 0",
        "sudo apt remove foo",
    ],
)
def test_safety_flags_destructive(command):
    assert safety.shell_command_risk(command)


@pytest.mark.parametrize(
    "command",
    ["Get-ChildItem", "git status", "Get-Date | Format-Table", "echo hello 2>&1", "dir > $null"],
)
def test_safety_allows_safe(command):
    assert safety.shell_command_risk(command) is None


def test_safety_flags_redirect_onto_existing_file(tmp_path):
    (tmp_path / "out.txt").write_text("keep")
    assert safety.shell_command_risk("echo hi > out.txt", str(tmp_path))
    assert safety.shell_command_risk("echo hi > new.txt", str(tmp_path)) is None
    assert safety.shell_command_risk("echo hi >> out.txt", str(tmp_path)) is None


# --- dispatcher ---------------------------------------------------------------

def test_dispatch_unknown_tool():
    r = call("fly_to_moon")
    assert r["ok"] is False and "unknown tool" in r["error"] and "run_shell" in r["available"]


def test_dispatch_bad_json():
    r = json.loads(asyncio.run(dispatch("list_dir", "{not json")))
    assert r["ok"] is False and "invalid arguments JSON" in r["error"]


def test_dispatch_missing_args_lists_expected():
    r = call("read_file")
    assert r["ok"] is False and "path" in r["expected"]


def test_dispatch_handler_exception_is_ok_false(monkeypatch):
    def boom(**_):
        raise RuntimeError("kaboom")

    monkeypatch.setitem(HANDLERS, "boom", boom)
    r = call("boom")
    assert r["ok"] is False and "kaboom" in r["error"]


def test_dispatch_truncates(monkeypatch):
    monkeypatch.setattr(config, "MAX_TOOL_OUTPUT_CHARS", 50)
    monkeypatch.setitem(HANDLERS, "big", lambda: "y" * 500)
    out = asyncio.run(dispatch("big", "{}"))
    assert out.startswith("y" * 50) and "[truncated 450 chars]" in out


def test_dispatch_logs_one_json_line_per_call(tmp_path):
    call("list_dir", path=str(tmp_path))
    call("read_file", path=str(tmp_path / "nope"))
    lines = config.LOG_FILE.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    entry = json.loads(lines[0])
    assert entry["tool"] == "list_dir" and entry["ok"] is True and "duration_ms" in entry


def test_redact_hides_secrets():
    text = redact("key sk-abcdefghijklmnop and api_key=supersecret and Bearer xyz.123")
    assert "sk-abcdefghijklmnop" not in text and "supersecret" not in text and "xyz.123" not in text
