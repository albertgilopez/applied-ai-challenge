"""Configurations A and A0 (STORY-004 DR-14): the Claude Code CLI as a black box.

A runs the CLI with file tools and Python; A0 with file tools only. The CLI cannot be trusted with the
machine, so it is confined and audited, and the report says this is detection, not isolation:

- **Confined.** Restricted mode (user, project and local settings ignored; file tools limited to the
  working directory), bare mode, the named tools only, a settings file that allows `python` and nothing
  else, no MCP servers, no session saved, stdin closed, a temporary workspace, and an environment built
  from scratch: no user credential names, and `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` so the API key never
  reaches the contestant's processes (measured in T0: without it, Python saw the key).
- **Audited.** Every tool input in the transcript is checked: a path outside the workspace, absolute or
  through `..`, or a network address makes the attempt `invalid`. Shell text is read as shell; Python (a
  `-c` argument, a heredoc, a `.py` file written or edited) is read by its single-token string literals,
  leaving out those the task's own code already has. Python can still build a path or an address at run
  time; the audit cannot see that, and the report says so.
- **Measured.** Cost is priced from the usage of each model message in the transcript, once per message
  (the CLI repeats a message's usage on every content block), with the CLI's own estimate kept beside it.
  Latency is the CLI's API time.
- **Replayable.** CI cannot replay a CLI. A live attempt stores its transcript and the editable files it
  left; offline, those files are written into a fresh workspace and graded again, and the transcript is
  audited again.
"""

from __future__ import annotations

import ast
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import textwrap
import tokenize
import warnings
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from harness.gate import relative_path
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
# Forms that name a place outside the workspace without spelling its path (review lens 2A F3): the home
# directory and other per-user variables, a UNC share, `cd -`. Only named variables: a bare `%x%` also
# appears in a Python format string, and flagging it would make a legitimate attempt `invalid`.
_ELSEWHERE = re.compile(
    r"\$\{?(?:HOME|USERPROFILE|APPDATA|LOCALAPPDATA|TMPDIR|TEMP|TMP|OLDPWD)\b\}?"
    r"|%(?:USERPROFILE|HOMEPATH|HOMEDRIVE|APPDATA|LOCALAPPDATA|TEMP|TMP|PUBLIC|PROGRAMDATA|ONEDRIVE)%"
    r"|\$env:\w+"
    # `~/...`, or a `~` that ends a command (`cd ~`, `ls ~ && ...`); not any tilde in the text: the pilot's
    # Haiku attempt in A was marked invalid for "# mean of noise ~ 0" in a Python comment.
    r"|(?<![\w~])~(?=[/\\]|\s*(?:$|[;&|]))"
    r"|(?<![\w:\\])\\\\[\w.$-]+\\"
    r"|\bcd\s+-(?=[\s;&|]|$)",
    re.IGNORECASE,
)
# Tools whose pattern is a path pattern (not a search text): its fixed prefix must stay inside.
GLOB_KEYS = {"Glob": "pattern", "Grep": "glob"}


# The rule B's prompt gives its contestant (paths are relative to the project directory), said to the CLI:
# without it the models in the pilot put scratch files in /tmp, which the audit reads as reaching outside.
WORKSPACE_RULE_ID = "keysbench-arm-a-workspace-rule"
WORKSPACE_RULE = (HERE / "prompts" / "arm_a_workspace_rule.md").read_text("utf-8").strip()
APPROVALS = HERE / "prompts" / "approved.jsonl"


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
        "--append-system-prompt", WORKSPACE_RULE,
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


_NULL_DEVICES = {"/dev/null"}  # a sink: nothing is read from it


def _command_paths(cmd: str) -> list[str]:
    found = [p for p in _WINDOWS_ABS.findall(cmd) + _POSIX_ABS.findall(cmd) if p not in _NULL_DEVICES]
    found += [t for t in _DOTDOT.findall(cmd) if ".." in PurePosixPath(t.replace("\\", "/")).parts]
    return found


# A network address. A command that names one makes the attempt invalid (b31a919); the same holds for one
# written into a Python file that the contestant can then run.
_URL = re.compile(r"\b(?:https?|ftp|wss?)://[^\s'\"`<>()]+", re.IGNORECASE)
# Python inside a shell command: `python -c '<code>'` / `python -c "<code>"`, and a heredoc that is fed to
# python (`python - <<'EOF'`) or written to a `.py` file that is then run (`cat > t.py <<'EOF'`, the live
# Haiku attempt in A).
_PY_C = re.compile(r"\bpython[\w.]*(?:\s+-[A-Za-z]+)*?\s+-c\s+(?P<q>['\"])(?P<code>.*?)(?<!\\)(?P=q)", re.DOTALL)
_HEREDOC = re.compile(
    r"(?P<head>[^\n]*?)<<-?\s*(?P<q>['\"]?)(?P<tag>\w+)(?P=q)[^\n]*\n(?P<code>.*?)\n\s*(?P=tag)\b", re.DOTALL
)
_PY_TARGET = re.compile(r"\bpython[\w.]*\b|>\s*['\"]?[^\s'\"<>|;&]+\.py\b")


def _unescape_double_quoted(code: str) -> str:
    """What bash hands to python from a double-quoted argument: `\\"`, `\\\\`, `\\$` and `\\``` lose the backslash."""
    return re.sub(r"\\([\"\\$`])", r"\1", code)


def _python_in_command(cmd: str) -> tuple[str, list[str]]:
    """The shell part of a command and the Python sources it runs. In Python a place can only be named in a
    string literal; comments and operators cannot name one. Auditing the source as shell text read
    `2%/sqrt(N)` in a comment as the path `/sqrt` (live run, 2026-10-11), so the source is taken out of the
    shell text and audited by its literals."""
    sources: list[str] = []

    def take_c(m: re.Match[str]) -> str:
        code = m.group("code")
        sources.append(_unescape_double_quoted(code) if m.group("q") == '"' else code)
        return m.group(0)[: m.start("code") - m.start(0)] + m.group(0)[m.end("code") - m.start(0) :]

    def take_heredoc(m: re.Match[str]) -> str:
        if not _PY_TARGET.search(m.group("head")):
            return m.group(0)  # a heredoc that is not Python stays shell text
        sources.append(m.group("code"))
        return m.group(0)[: m.start("code") - m.start(0)] + m.group(0)[m.end("code") - m.start(0) :]

    shell = _HEREDOC.sub(take_heredoc, cmd)
    shell = _PY_C.sub(take_c, shell)
    return shell, sources


def _literals(source: str) -> list[tuple[str, bool]] | None:
    """Every string constant in a Python source as `(value, is_fstring_part)`, or None if not even one token
    can be read. An f-string part is a fragment of text, not a value handed to a call (`f"{lo}..{hi}"` gave
    the part `..`). An `Edit` hands over a fragment (indented, cut mid-block) that `ast` refuses, so the
    tokenizer, which reads fragments, is the fallback."""
    with warnings.catch_warnings():  # `'C:\Windows'` warns of an invalid escape; it is still a literal
        warnings.simplefilter("ignore", SyntaxWarning)
        warnings.simplefilter("ignore", DeprecationWarning)
        try:
            tree: ast.Module | None = ast.parse(textwrap.dedent(source))
        except (SyntaxError, ValueError):
            tree = None
        if tree is not None:
            parts = {id(v) for n in ast.walk(tree) if isinstance(n, ast.JoinedStr) for v in n.values}
            return [
                (n.value, id(n) in parts)
                for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
            ]
        found: list[tuple[str, bool]] = []
        read_any = False
        try:
            for tok in tokenize.generate_tokens(io.StringIO(source).readline):
                read_any = True
                if tok.type == tokenize.STRING:
                    try:
                        value = ast.literal_eval(tok.string)
                    except (SyntaxError, ValueError):
                        value = None  # an f-string before Python 3.12: its parts are not values
                    if isinstance(value, str):
                        found.append((value, False))
                elif tok.type == getattr(tokenize, "FSTRING_MIDDLE", -1):
                    found.append((tok.string, True))
        except (tokenize.TokenError, SyntaxError):
            pass
        return found if read_any else None


def environment_literals(environment: Path) -> frozenset[str]:
    """The string literals the task's own code already has. Rewriting one of them is not reaching anywhere:
    KB-01/02's `purl.py` and `sbom.py` name URLs, and an attempt that edits them must stay valid (the
    complement of the finding, ai-first anti-pattern 6.bis)."""
    found: set[str] = set()
    if environment.is_dir():
        for path in environment.rglob("*.py"):
            found.update(value for value, _ in _literals(path.read_text("utf-8", errors="replace")) or [])
    return frozenset(found)


def _one_token(text: str) -> bool:
    """A literal that is one token. Only such a literal can be a path or an address handed to a call; a
    docstring or a message is prose (re-auditing the stored attempts, `σ/√3.` in the docstrings of a valid A0
    attempt read as paths)."""
    stripped = text.strip()
    return bool(stripped) and not any(c.isspace() for c in stripped)


def _source_findings(where: str, source: str, workspace: Path, known: frozenset[str]) -> list[str]:
    lits = _literals(source)
    if lits is None:  # not even one token: audit it as text, as before
        whole, parts = [source], []
    else:
        fresh = [(value, part) for value, part in lits if value not in known and _one_token(value)]
        whole = [value for value, part in fresh if not part]
        parts = [value for value, part in fresh if part]
    findings = []
    for text in whole + parts:  # an address is an address, in a whole literal or in an f-string part
        for m in _URL.finditer(text):
            findings.append(f"{where} names a network address: {m.group(0)[:200]}")
    for text in whole:
        for m in _ELSEWHERE.finditer(text):
            findings.append(f"{where} names a place outside the workspace: {m.group(0)[:200]}")
        for p in _command_paths(_URL.sub(" ", text)):
            if not _inside(p, workspace):
                findings.append(f"{where} reaches outside the workspace: {p[:200]}")
    return findings


def _glob_prefix(pattern: str) -> str:
    """The part of a glob before its first wildcard: the directory it starts from."""
    cut = min((i for i, ch in enumerate(pattern) if ch in "*?[{"), default=len(pattern))
    return pattern[:cut]


def audit(lines: list[str], workspace: Path, known: frozenset[str] = frozenset()) -> list[str]:
    """Every tool input that reaches outside the workspace or names a network address. Any finding makes the
    attempt `invalid`. Shell tokens and the string literals of Python the contestant runs or writes are
    audited; `known` are the literals the task's own code already has. Detection only: Python can build a
    path or an address at run time that no transcript shows."""
    findings = []
    for name, inp in _tool_inputs(_parse(lines)):
        glob_key = GLOB_KEYS.get(name)
        glob = inp.get(glob_key) if glob_key else None
        if isinstance(glob, str) and glob:
            prefix = _glob_prefix(glob)
            if prefix and (_ELSEWHERE.search(prefix) or not _inside(prefix, workspace)):
                findings.append(f"{name}.{glob_key} reaches outside the workspace: {glob[:200]}")
        for key in PATH_KEYS:
            value = inp.get(key)
            if isinstance(value, str) and value and not _inside(value, workspace):
                findings.append(f"{name}.{key} outside the workspace: {value[:200]}")
        cmd = inp.get("command")
        if isinstance(cmd, str):
            shell, sources = _python_in_command(cmd)
            for m in _ELSEWHERE.finditer(shell):
                findings.append(f"{name}.command names a place outside the workspace: {m.group(0)[:200]}")
            for p in _command_paths(_URL.sub(" ", shell)):
                if not _inside(p, workspace):
                    findings.append(f"{name}.command reaches outside the workspace: {p[:200]}")
            for m in _URL.finditer(shell):
                findings.append(f"{name}.command names a network address: {m.group(0)[:200]}")
            for source in sources:
                findings += _source_findings(f"{name}.command (python)", source, workspace, known)
        target = inp.get("file_path")
        if isinstance(target, str) and target.lower().endswith(".py"):
            for key in ("content", "new_string"):
                text = inp.get(key)
                if isinstance(text, str) and text:
                    findings += _source_findings(f"{name}.{key}", text, workspace, known)
            for edit in inp.get("edits") or []:  # MultiEdit
                if isinstance(edit, dict) and isinstance(edit.get("new_string"), str):
                    findings += _source_findings(f"{name}.edits", edit["new_string"], workspace, known)
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
    p = relative_path(rel)
    if p is None:
        raise ValueError(f"unsafe stored path {rel!r}")
    return p.as_posix()


# Key formats that must never reach a committed recording (a format check: the question is syntactic).
_KEY_PATTERNS = re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}")


def redact(text: str, secrets: tuple[str, ...] = ()) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "<redacted>")
    return _KEY_PATTERNS.sub("<redacted>", text)


def store_attempt(
    store: Path, lines: list[str], workspace: Path, editable: tuple[str, ...], *, secrets: tuple[str, ...] = ()
) -> None:
    """Store what the attempt left: its transcript (workspace path replaced by `<W>`) and the editable files.
    Both are committed as a recording, so keys are redacted on the way in: the CLI's environment is
    scrubbed, but what the contestant printed or wrote is stored as it was (review lens 2A F5)."""
    if store.exists():
        shutil.rmtree(store)
    (store / "files").mkdir(parents=True)
    root = workspace.resolve()
    lines = [redact(ln, secrets) for ln in to_placeholder(to_placeholder(lines, str(root)), str(workspace))]
    (store / "transcript.jsonl").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    kept = []
    for rel in editable:
        src = workspace / _safe_rel(rel)
        if src.is_file() and not src.is_symlink():
            target = store / "files" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            raw = src.read_bytes()
            try:
                target.write_bytes(redact(raw.decode("utf-8"), secrets).encode("utf-8"))
            except UnicodeDecodeError:
                target.write_bytes(raw)
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
