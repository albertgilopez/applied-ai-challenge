"""STORY-004 T9: configurations A and A0, the Claude Code CLI as a black box (S4-01 A, S4-04 invalid, S4-17).

No CLI runs here: the command is built and inspected, and transcripts are written by hand in the
stream-json shape the CLI produced in the T0 smoke run (2.1.296, Windows).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from keysbench import arm_a


def line(obj: dict) -> str:
    return json.dumps(obj)


def assistant(msg_id: str, blocks: list[dict], usage: dict | None = None) -> dict:
    return {
        "type": "assistant",
        "message": {
            "id": msg_id,
            "model": "claude-haiku-5-5",
            "content": blocks,
            "usage": usage
            or {
                "input_tokens": 10,
                "output_tokens": 100,
                "cache_read_input_tokens": 1000,
                "cache_creation_input_tokens": 500,
                "cache_creation": {"ephemeral_5m_input_tokens": 500, "ephemeral_1h_input_tokens": 0},
                "inference_geo": "global",
            },
        },
    }


def tool_use(name: str, inp: dict, n: int = 1) -> dict:
    return {"type": "tool_use", "id": f"tu{n}", "name": name, "input": inp}


def result(**kw) -> dict:
    base = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "total_cost_usd": 0.0009,
        "duration_ms": 9000,
        "duration_api_ms": 7000,
        "num_turns": 3,
        "permission_denials": [],
        "usage": {},
    }
    return {**base, **kw}


def transcript(*objs: dict) -> list[str]:
    init = {"type": "system", "subtype": "init", "model": "claude-haiku-5-5", "claude_code_version": "2.1.296"}
    return [line(init), *(line(o) for o in objs)]


# ── S4-01 (A) and S4-17: the command ─────────────────────────────────────────────────────────────────


def test_s4_01_and_s4_17_the_command_for_a(tmp_path):
    cmd = arm_a.command("A", model="claude-haiku-5-5", effort="high", instruction="do it", remaining_usd=1.5,
                        cli="claude", settings=tmp_path / "s.json")  # fmt: skip
    for flag in ("--restricted", "--bare", "--tools", "--settings", "--no-session-persistence", "--strict-mcp-config"):
        assert flag in cmd
    assert cmd[cmd.index("--effort") + 1] == "high" and cmd[cmd.index("--model") + 1] == "claude-haiku-5-5"
    assert "Bash" in cmd[cmd.index("--tools") + 1].split(",")
    assert cmd[cmd.index("--max-budget-usd") + 1] == "1.5000"


def test_s4_17_a0_has_no_bash(tmp_path):
    cmd = arm_a.command("A0", model="claude-haiku-5-5", effort="high", instruction="x", remaining_usd=1.0,
                        cli="claude", settings=tmp_path / "s.json")  # fmt: skip
    assert "Bash" not in cmd[cmd.index("--tools") + 1].split(",")


def test_the_environment_holds_the_key_scrub_and_no_user_credentials(monkeypatch):
    monkeypatch.setenv("CREDENTIALS_FILE", "C:/secrets/.env")
    monkeypatch.setenv("PROJECTS_ROOT", "C:/somewhere")
    env = arm_a.cli_env(api_key="sk-ant-test")
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-test"
    assert env["CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"] == "1"
    assert "CREDENTIALS_FILE" not in env and "PROJECTS_ROOT" not in env


# ── S4-17 and S4-04: the audit ───────────────────────────────────────────────────────────────────────


@pytest.fixture
def w(tmp_path):
    ws = tmp_path / "w"
    ws.mkdir()
    (ws / "driver.py").write_text("x = 1\n", encoding="utf-8")
    return ws


@pytest.mark.parametrize(
    ("tool", "inp", "invalid"),
    [
        ("Read", {"file_path": "C:/elsewhere/solution.py"}, True),
        ("Read", {"file_path": "/etc/hosts"}, True),
        ("Bash", {"command": "python -c \"open('/etc/hosts').read()\""}, True),
        ("Bash", {"command": "python -c \"open('C:\\\\Windows\\\\win.ini').read()\""}, True),
        ("Read", {"file_path": "../KB-01/solution/core/license_expr.py"}, True),  # S4-04 row 3
        ("Bash", {"command": "cat ../secret.txt"}, True),
        ("Edit", {"file_path": "driver.py", "old_string": "1", "new_string": "2"}, False),
        ("Bash", {"command": "python -m pytest -q"}, False),
        ("Glob", {"pattern": "**/*.py"}, False),
    ],
)
def test_s4_17_the_audit_marks_any_access_outside_the_workspace(w, tool, inp, invalid):
    findings = arm_a.audit(transcript(assistant("m1", [tool_use(tool, inp)]), result()), w)
    assert bool(findings) is invalid, findings


def test_an_absolute_path_inside_the_workspace_is_allowed(w):
    inside = str((w / "driver.py").resolve())
    findings = arm_a.audit(transcript(assistant("m1", [tool_use("Read", {"file_path": inside})]), result()), w)
    assert findings == []


# ── usage and cost from the transcript ───────────────────────────────────────────────────────────────


def test_cost_is_priced_once_per_message_from_its_own_usage(w):
    # The CLI repeats a message's usage on every content block of that message; it is one call.
    msgs = [assistant("m1", [tool_use("Read", {"file_path": "driver.py"})]),
            assistant("m1", [{"type": "text", "text": "reading"}]),
            assistant("m2", [{"type": "text", "text": "done"}])]  # fmt: skip
    summary = arm_a.summarise(transcript(*msgs, result()), model="claude-haiku-5-5")
    per_call = (10 * 0.10 + 500 * 0.125 + 1000 * 0.01 + 100 * 0.50) / 1e6
    assert summary["calls"] == 2
    assert summary["cost_usd"] == pytest.approx(2 * per_call)
    assert summary["cli_cost_usd"] == 0.0009
    assert summary["latency_s"] == 7.0


@pytest.mark.parametrize(
    ("res", "outcome"),
    [
        (result(subtype="error_max_budget_usd", is_error=True), "budget_stopped"),
        (result(subtype="error_max_turns", is_error=True), "error"),
        (result(stop_reason="refusal"), "refused"),
        (result(stop_reason="max_tokens"), "truncated"),
        (result(), None),
    ],
)
def test_the_result_line_maps_to_an_outcome(res, outcome):
    assert arm_a.summarise(transcript(res), model="claude-haiku-5-5")["outcome"] == outcome


def test_a_transcript_without_a_result_line_is_an_error():
    assert arm_a.summarise(transcript(), model="claude-haiku-5-5")["outcome"] == "error"


# ── offline: the stored files are graded again ───────────────────────────────────────────────────────


def test_store_and_restore_editable_files(tmp_path, w):
    (w / "driver.py").write_text("x = 2\n", encoding="utf-8")
    (w / "scratch.txt").write_text("not declared\n", encoding="utf-8")
    store = tmp_path / "store"
    arm_a.store_attempt(store, transcript(result()), w, editable=("driver.py", "missing.py"))
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    (fresh / "driver.py").write_text("x = 1\n", encoding="utf-8")
    lines = arm_a.restore_attempt(store, fresh)
    assert (fresh / "driver.py").read_text("utf-8") == "x = 2\n"
    assert not (fresh / "scratch.txt").exists()
    assert json.loads(lines[-1])["type"] == "result"


def test_a_stored_path_cannot_escape_on_restore(tmp_path):
    store = tmp_path / "store"
    (store / "files").mkdir(parents=True)
    (store / "transcript.jsonl").write_text(line(result()) + "\n", encoding="utf-8")
    (store / "manifest.json").write_text(json.dumps({"files": ["../evil.py"]}), encoding="utf-8")
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    with pytest.raises(ValueError):
        arm_a.restore_attempt(store, fresh)


def test_settings_files_allow_python_for_a_and_nothing_for_a0():
    a = json.loads(Path(arm_a.SETTINGS["A"]).read_text("utf-8"))
    a0 = json.loads(Path(arm_a.SETTINGS["A0"]).read_text("utf-8"))
    assert a["permissions"]["allow"] == ["Bash(python *)"] and a["env"] == {}
    assert a0["permissions"]["allow"] == [] and a0["env"] == {}
