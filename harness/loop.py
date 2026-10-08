"""The agent loop.

model call → for each tool_use: gate → (run | deny | escalate) → ledger → next
model call, until the model stops, the step budget runs out, or the loop stops
making progress (the same call repeated). Every step is written to the ledger
before the next one starts.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Callable

from harness.catalog import Catalog
from harness.gate import Gate
from harness.ledger import Ledger
from harness.prompts import PromptRegistry, digest
from harness.usage import Usage, cost_usd

# (tool name, args, gate reason) -> what the human decided, as text for the model
Escalation = Callable[[str, dict, str], str]

REPEAT_LIMIT = 3


@dataclass
class RunResult:
    text: str
    stop_reason: str
    steps: int
    usage: Usage
    cost_usd: float | None
    latency_s: float
    tool_calls: list[dict] = field(default_factory=list)


class Agent:
    def __init__(self, *, provider, model: str, system: str, prompt_id: str,
                 registry: PromptRegistry, catalog: Catalog, gate: Gate, ledger: Ledger,
                 env: str = "dev", max_steps: int = 8, max_tokens: int = 2048,
                 on_escalate: Escalation | None = None) -> None:
        self.provider, self.model, self.system = provider, model, system
        self.prompt_id, self.registry = prompt_id, registry
        self.catalog, self.gate, self.ledger = catalog, gate, ledger
        self.env, self.max_steps, self.max_tokens = env, max_steps, max_tokens
        self.on_escalate = on_escalate

    def _run_tool(self, call: dict) -> tuple[dict, dict]:
        name, args = call["name"], call.get("input") or {}
        t = self.catalog.get(name)
        decision = self.gate.decide(t, args)
        if decision.verdict == "allow":
            try:
                output, is_error = str(t.fn(**args)), False
            except Exception as exc:  # the model sees the failure; the loop goes on
                output, is_error = f"tool failed: {type(exc).__name__}: {exc}", True
        elif decision.verdict == "escalate":
            human = self.on_escalate(name, args, decision.reason) if self.on_escalate else None
            output, is_error = f"escalated to a human, not executed: {human or 'no reviewer available'}", True
        else:
            output, is_error = f"denied: {decision.reason}", True

        record = {"tool": name, "args": args, "verdict": decision.verdict,
                  "reason": decision.reason, "is_error": is_error}
        self.ledger.append({"kind": "tool", **record, "output": output[:2000]})
        block = {"type": "tool_result", "tool_use_id": call["id"], "content": output, "is_error": is_error}
        return block, record

    def run(self, user: str) -> RunResult:
        approved = self.registry.require(self.prompt_id, self.system, self.env)
        self.ledger.append({"kind": "run_start", "model": self.model, "env": self.env,
                            "prompt_id": self.prompt_id, "prompt_sha256": digest(self.system),
                            "prompt_approved": approved})
        started = time.monotonic()
        messages: list[dict] = [{"role": "user", "content": user}]
        usage, calls, seen = Usage(), [], {}
        text, stop = "", "max_steps"

        for step in range(1, self.max_steps + 1):
            response = self.provider.create(
                model=self.model, max_tokens=self.max_tokens, system=self.system,
                messages=messages, tools=self.catalog.schemas(),
            )
            usage.add(response.get("usage"))
            self.ledger.append({"kind": "model_call", "step": step,
                                "stop_reason": response.get("stop_reason"),
                                "usage": response.get("usage")})
            content = response.get("content") or []
            text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
            uses = [b for b in content if b.get("type") == "tool_use"]
            if response.get("stop_reason") != "tool_use" or not uses:
                stop = response.get("stop_reason") or "end_turn"
                break

            key = json.dumps([(u["name"], u.get("input")) for u in uses], sort_keys=True)
            seen[key] = seen.get(key, 0) + 1
            if seen[key] >= REPEAT_LIMIT:
                stop = "no_progress"
                break

            messages.append({"role": "assistant", "content": content})
            results = []
            for call in uses:
                block, record = self._run_tool(call)
                results.append(block)
                calls.append(record)
            messages.append({"role": "user", "content": results})

        latency = time.monotonic() - started
        cost = cost_usd(usage, self.model)
        self.ledger.append({"kind": "run_end", "stop_reason": stop, "steps": step,
                            "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
                            "cache_creation_input_tokens": usage.cache_creation_input_tokens,
                            "cache_read_input_tokens": usage.cache_read_input_tokens,
                            "cost_usd": cost, "latency_s": round(latency, 3)})
        return RunResult(text=text, stop_reason=stop, steps=step, usage=usage,
                         cost_usd=cost, latency_s=latency, tool_calls=calls)
