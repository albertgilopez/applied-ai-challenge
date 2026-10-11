"""Contestants (STORY-004): the same task, model and effort through different harnesses.

Configuration B, the baseline, is this repo's `harness/` loop with three tools (list, read, write) on a
temporary workspace and no code execution. Every path is relative to the workspace and goes through the
gate's one resolver, so the tool reads and writes exactly the path the gate allowed, and the prompt
never names the temporary directory (a recording made on one machine replays on another).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from harness.catalog import Catalog, tool
from harness.gate import Gate
from harness.ledger import Ledger
from harness.loop import Agent, RunResult
from harness.prompts import PromptRegistry
from harness.providers import Provider

HERE = Path(__file__).resolve().parent
PROMPT_ID = "keysbench-contestant-b"
PROMPT = (HERE / "prompts" / "contestant.md").read_text("utf-8")
APPROVALS = HERE / "prompts" / "approved.jsonl"
HARNESS = "repo-harness"
HARNESS_VERSION = "1"  # bump when the loop, the tools or the prompt change what a contestant can do
MAX_FILE_BYTES = 200_000


@dataclass(frozen=True)
class ContestantRun:
    run: RunResult | None
    error: str | None = None


def b_catalog(gate: Gate, workspace: Path) -> Catalog:
    catalog = Catalog()

    @tool(catalog, effect="read", path_args=(), description="List every file in the project directory.")
    def list_files() -> str:
        files = sorted(
            p.relative_to(workspace).as_posix()
            for p in workspace.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
        )
        return "\n".join(files)

    @tool(catalog, effect="read", path_args=("path",), description="Read a text file (path relative, with /).")
    def read_file(path: str) -> str:
        target = gate.resolve(path)
        if target is None or not target.is_file():
            raise FileNotFoundError(path)
        return target.read_text("utf-8", errors="replace")[:MAX_FILE_BYTES]

    @tool(
        catalog,
        effect="write",
        path_args=("path",),
        description="Write the complete content of a text file (path relative, with /). Creates it if needed.",
    )
    def write_file(path: str, content: str) -> str:
        target = gate.resolve(path)
        if target is None:
            raise PermissionError(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8"))  # bytes: no newline translation on Windows
        return f"wrote {path} ({len(content)} characters)"

    return catalog


def run_b(
    *,
    workspace: Path,
    instruction: str,
    model: str,
    effort: str,
    provider: Provider,
    ledger_path: Path,
    max_steps: int,
    max_tokens: int,
    registry: PromptRegistry | None = None,
) -> RunResult:
    gate = Gate(read_roots=["."], write_roots=["."], base=workspace)
    agent = Agent(
        provider=provider,
        model=model,
        system=PROMPT,
        prompt_id=PROMPT_ID,
        registry=registry or PromptRegistry(APPROVALS),
        catalog=b_catalog(gate, workspace),
        gate=gate,
        ledger=Ledger(ledger_path),
        max_steps=max_steps,
        max_tokens=max_tokens,
        effort=effort,
        cache=True,
    )
    return agent.run(instruction)
