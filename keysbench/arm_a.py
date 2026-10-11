"""Configurations A and A0 (STORY-004 DR-14): the Claude Code CLI as a black box.

A runs the CLI with file tools and Python; A0 with file tools only. The CLI cannot be trusted with the
machine, so it is confined and audited, and the report says this is detection, not isolation:

- **Confined.** Restricted mode (user, project and local settings ignored; file tools limited to the
  working directory), bare mode, the named tools only, a settings file that allows `python` and nothing
  else, no MCP servers, no session saved, stdin closed, a temporary workspace, and an environment built
  from scratch: no user credential names, and `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` so the API key never
  reaches the contestant's processes (measured in T0: without it, Python saw the key).
- **Audited.** Every tool input in the transcript is checked: a path outside the workspace, absolute or
  through `..`, makes the attempt `invalid`. Python can still build a path at run time; the audit cannot
  see that, and the report says so.
- **Measured.** Cost is priced from the usage of each model message in the transcript, once per message
  (the CLI repeats a message's usage on every content block), with the CLI's own estimate kept beside it.
  Latency is the CLI's API time.
- **Replayable.** CI cannot replay a CLI. A live attempt stores its transcript and the editable files it
  left; offline, those files are written into a fresh workspace and graded again, and the transcript is
  audited again.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from harness.storage import JSONObject
from harness.usage import call_cost

HERE = Path(__file__).resolve().parent
SETTINGS = {"A": HERE / "arm_a" / "settings-A.json", "A0": HERE / "arm_a" / "settings-A0.json"}
TOOLS = {"A": "Read,Edit,Write,Glob,Grep,Bash", "A0": "Read,Edit,Write,Glob,Grep"}
HARNESS = {"A": "claude-code-cli", "A0": "claude-code-cli-no-exec"}

# What the CLI needs to start, on Windows and Linux. Nothing that names a credential or a user setting.
_KEEP = (
    "PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR",
    "USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOME", "LANG", "LC_ALL",
)  # fmt: skip

PATH_KEYS = ("file_path", "path", "notebook_path")
_WINDOWS_ABS = re.compile(r"[A-Za-z]:[\\/][^\s'\"`;|&<>()]*")
_POSIX_ABS = re.compile(r"(?<![\w.:/\\-])/(?!/)[^\s'\"`;|&<>()]+")
_DOTDOT = re.compile(r"[^\s'\"`;|&<>()]*\.\.(?:[\\/][^\s'\"`;|&<>()]*)?")


def command(
    config: str,
    *,
    model: str,
    effort: str,
    instruction: str,
    remaining_usd: float,
    cli: str,
    settings: Path,
    max_turns: int | None = None,
) -> list[str]:
    if cli.lower().endswith((".cmd", ".bat")) and "\n" in instruction:
        # cmd.exe ends a command line at the first newline: every flag after the prompt (model, budget,
        # tools, settings) would silently never reach the CLI (review finding 3B F1, reproduced).
        raise ValueError(f"a multi-line prompt cannot go through {cli}: a newline ends cmd.exe's command line")
    return [
        cli, "--restricted", "--bare", "-p", instruction,
        "--model", model, "--effort", effort,
        "--output-format", "stream-json", "--verbose",
        "--max-budget-usd", f"{remaining_usd:.4f}",
        "--settings", str(settings), "--strict-mcp-config",
        "--no-session-persistence",
        "--tools", TOOLS[config],
        *(["--max-turns", str(max_turns)] if max_turns else []),
    ]  # fmt: skip


def cli_env(api_key: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k.upper() in _KEEP}
    env["ANTHROPIC_API_KEY"] = api_key
    env["CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"] = "1"
    return env


def _parse(lines: list[str]) -> list[JSONObject]:
    out = []
    for raw in lines:
        raw = raw.strip()
        if raw:
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                out.append(obj)
    return out


def _tool_inputs(events: list[JSONObject]) -> list[tuple[str, JSONObject]]:
    found = []
    for e in events:
        if e.get("type") == "assistant":
            for block in (e.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    found.append((str(block.get("name")), block.get("input") or {}))
    return found


def _inside(raw: str, workspace: Path) -> bool:
    root = workspace.resolve()
    text = raw.replace("\\\\", "\\")
    if PureWindowsPath(text).drive and os.name != "nt":
        return False  # a Windows path on another OS is never this workspace
    path = Path(text)
    target = path.resolve() if path.is_absolute() or PureWindowsPath(text).drive else (root / text).resolve()
    return target == root or root in target.parents


def _command_paths(cmd: str) -> list[str]:
    found = _WINDOWS_ABS.findall(cmd) + _POSIX_ABS.findall(cmd)
    found += [t for t in _DOTDOT.findall(cmd) if ".." in PurePosixPath(t.replace("\\", "/")).parts]
    return found


def audit(lines: list[str], workspace: Path) -> list[str]:
    """Every tool input that reaches outside the workspace. Any finding makes the attempt `invalid`."""
    findings = []
    for name, inp in _tool_inputs(_parse(lines)):
        for key in PATH_KEYS:
            value = inp.get(key)
            if isinstance(value, str) and value and not _inside(value, workspace):
                findings.append(f"{name}.{key} outside the workspace: {value[:200]}")
        cmd = inp.get("command")
        if isinstance(cmd, str):
            for p in _command_paths(cmd):
                if not _inside(p, workspace):
                    findings.append(f"{name}.command reaches outside the workspace: {p[:200]}")
    return findings


def summarise(lines: list[str], *, model: str) -> dict[str, Any]:
    events = _parse(lines)
    init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), {})
    result = next((e for e in reversed(events) if e.get("type") == "result"), None)
    usages: dict[str, JSONObject] = {}
    last_stop = None
    for e in events:
        if e.get("type") == "assistant":
            msg = e.get("message") or {}
            msg_id = str(msg.get("id"))
            u = msg.get("usage")
            # A message can appear more than once with a partial usage first: keep the largest output.
            if isinstance(u, dict) and (
                msg_id not in usages or (u.get("output_tokens") or 0) > (usages[msg_id].get("output_tokens") or 0)
            ):
                usages[msg_id] = u
            last_stop = msg.get("stop_reason") or last_stop
    costs = [call_cost(u, model) for u in usages.values()]
    cost = None if not costs or any(c is None for c in costs) else sum(c for c in costs if c is not None)
    summary: dict[str, Any] = {
        "cli_version": init.get("claude_code_version"),
        "calls": len(usages),
        "cost_usd": cost,
        "cli_cost_usd": None if result is None else result.get("total_cost_usd"),
        "latency_s": None if result is None else (result.get("duration_api_ms") or 0) / 1000,
        "wall_s": None if result is None else (result.get("duration_ms") or 0) / 1000,
        "num_turns": None if result is None else result.get("num_turns"),
        "permission_denials": [] if result is None else result.get("permission_denials") or [],
    }
    if result is None:
        summary["outcome"] = "error"
    elif result.get("subtype") == "error_max_budget_usd":
        summary["outcome"] = "budget_stopped"
    elif result.get("is_error") or str(result.get("subtype", "")).startswith("error"):
        summary["outcome"] = "error"
    elif (result.get("stop_reason") or last_stop) == "refusal":
        summary["outcome"] = "refused"
    elif (result.get("stop_reason") or last_stop) == "max_tokens":
        summary["outcome"] = "truncated"
    else:
        summary["outcome"] = None  # ran to the end: the grader decides
    return summary


def close_partial(lines: list[str], *, reason: str) -> list[str]:
    """A transcript the CLI did not finish, closed with an error result line so it is scored as `error`
    and the messages it already sent are still priced."""
    end = {"type": "result", "subtype": f"error_{reason}", "is_error": True, "total_cost_usd": None}
    return [*lines, json.dumps(end)]


def _kill_tree(proc: subprocess.Popen[bytes]) -> None:
    """Kill the CLI and everything it started. Killing only the CLI leaves its children holding the output
    pipe, and the wait for that pipe has no limit (verifier finding: a 2 s timeout took 12 s)."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, check=False)
    else:
        os.killpg(proc.pid, signal.SIGKILL)


def run_cli(cmd: list[str], workspace: Path, env: dict[str, str], timeout_s: int) -> list[str]:
    proc = subprocess.Popen(
        cmd,
        cwd=workspace,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=os.name != "nt",
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    try:
        out, _ = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        out, _ = proc.communicate()
        # The run spent money until it was killed: keep what it wrote, so that spend is counted.
        return close_partial(out.decode("utf-8", errors="replace").splitlines(), reason="timeout")
    return out.decode("utf-8", errors="replace").splitlines()


# ── workspace-independent transcripts ────────────────────────────────────────────────────────────────

PLACEHOLDER = "<W>"
_AFTER_PLACEHOLDER = re.compile(r"<W>[^\s'\"`;|&<>()]*")


def _map_strings(value: Any, fn: Any) -> Any:
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, list):
        return [_map_strings(v, fn) for v in value]
    if isinstance(value, dict):
        return {k: _map_strings(v, fn) for k, v in value.items()}
    return value


def to_placeholder(lines: list[str], root: str) -> list[str]:
    """Replace the live workspace's path with `<W>` (and `\\` after it with `/`) in every string of the
    transcript. The real CLI uses absolute paths, so without this a stored attempt audits as `invalid` in any
    other workspace, and a Windows recording can never be read on Linux (review finding 3B F2)."""
    forms = sorted({root, root.replace("\\", "/")}, key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(f) for f in forms), re.IGNORECASE if os.name == "nt" or ":" in root else 0)

    def fix(s: str) -> str:
        s = pattern.sub(PLACEHOLDER, s)
        return _AFTER_PLACEHOLDER.sub(lambda m: m.group(0).replace("\\", "/"), s)

    out = []
    for raw in lines:
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            out.append(fix(raw))
            continue
        out.append(json.dumps(_map_strings(obj, fix), ensure_ascii=False))
    return out


def from_placeholder(lines: list[str], root: str) -> list[str]:
    target = root.replace("\\", "/")
    out = []
    for raw in lines:
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            out.append(raw.replace(PLACEHOLDER, target))
            continue
        out.append(json.dumps(_map_strings(obj, lambda s: s.replace(PLACEHOLDER, target)), ensure_ascii=False))
    return out


# ── what a live attempt leaves for offline replay ────────────────────────────────────────────────────


def _safe_rel(rel: str) -> str:
    p = PurePosixPath(rel.replace("\\", "/"))
    if not rel or p.is_absolute() or PureWindowsPath(rel).drive or ".." in p.parts:
        raise ValueError(f"unsafe stored path {rel!r}")
    return p.as_posix()


def store_attempt(store: Path, lines: list[str], workspace: Path, editable: tuple[str, ...]) -> None:
    if store.exists():
        shutil.rmtree(store)
    (store / "files").mkdir(parents=True)
    root = workspace.resolve()
    lines = to_placeholder(to_placeholder(lines, str(root)), str(workspace))
    (store / "transcript.jsonl").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    kept = []
    for rel in editable:
        src = workspace / _safe_rel(rel)
        if src.is_file() and not src.is_symlink():
            target = store / "files" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(src.read_bytes())
            kept.append(rel)
    (store / "manifest.json").write_bytes(json.dumps({"files": kept}, indent=1).encode("utf-8"))


def restore_attempt(store: Path, workspace: Path) -> list[str]:
    manifest = json.loads((store / "manifest.json").read_text("utf-8"))
    for rel in manifest["files"]:
        rel = _safe_rel(rel)
        target = workspace / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((store / "files" / rel).read_bytes())
    lines = (store / "transcript.jsonl").read_text("utf-8").splitlines()
    return from_placeholder(lines, workspace.resolve().as_posix())
