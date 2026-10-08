# OSS approval agent for the EU Cyber Resilience Act

A first pass over the open-source components of a product's SBOM, so a Legal reviewer only makes
the final call. Each component gets `Allow`, `Needs review` or `Reject` against a license policy,
with the reason and a link to its source. A reviewer approves or overrides, every step is an
append-only ledger line, and the result is a report Legal can attach to the CRA file.

```text
 SBOM (CycloneDX or SPDX) ─► parse ─► decide against policy ─► ledger ◄── reviewer: approve / override
                                         (fail closed)            │
                                                                  ▼
                                                    report.json (raw) ─► report.md (escaped)
```

## Status

| Story | What | State |
|---|---|---|
| [STORY-001](stories/STORY-001.md) | Parse CycloneDX 1.6 and SPDX 2.3, classify each component's license expression | done |
| [STORY-002](stories/STORY-002.md) | AI models: read the license and usage restrictions from each model card | specified, not built |
| [STORY-003](stories/STORY-003.md) | Reviewer CLI, audit ledger, Legal report | done |

Until STORY-002 lands, an AI model is classified from the license its SBOM entry declares; a custom
model license (Llama, Gemma) is `Needs review`, which is the safe answer, not the final one.

## Try it

```bash
uv sync
uv run python -m review scan   --sbom samples/sbom.cdx.json --policy samples/policy.yaml --ledger out/ledger.jsonl
uv run python -m review list   --ledger out/ledger.jsonl
uv run python -m review override --ledger out/ledger.jsonl --decision <id> --verdict Reject --by "A. Reviewer" --reason "..."
uv run python -m review report --sbom samples/sbom.cdx.json --policy samples/policy.yaml --ledger out/ledger.jsonl --out out
```

The samples hold 14 real components (PyPI, npm, Maven, GitHub, three Hugging Face models), the same
list in both formats.

## Design, in four rules

1. **Fail closed.** Missing, unknown, unparseable or unverifiable is `Needs review`, never `Allow`
   (DOCTRINE D-02). STORY-002 contains a requester note asking the opposite; it is recorded under
   *Refused instructions* and not implemented.
2. **The model extracts, the code decides.** License expressions are parsed and decided by plain code
   in `core/` (SPDX grammar, policy lookup). The model is used only where the license lives in prose
   (model cards), and it must quote the sentence it read; code checks the quote is in the card (D-03).
3. **History, not state.** Decisions and reviews are ledger lines; an override is a new line pointing at
   the decision it replaces. A re-run reuses a decision only if every input it was made from is the
   same, policy included (D-06, D-08).
4. **Text from the SBOM is data.** The JSON keeps it raw; the Markdown escapes it, so a component name
   cannot break the table, recolour a terminal or plant a link. Only `https` source links are kept.

`core/` imports only the standard library; `tests/test_boundary.py` fails naming any other import.
`harness/` is a small agent loop written for this repo: a tool catalog where every tool declares its
effect, one gate before every tool call, a system prompt approved by hash, a write-ahead ledger, and
record/replay of model calls so CI never calls a model.

## How it was verified

- **Every acceptance criterion cites a case**, and a test fails if a checkbox has no case behind it.
- **A test counts once it has been seen failing.** `scripts/canaries.py` breaks one rule at a time on a
  temporary copy of the repo (58 mutations) and the suite must go red for each.
- **An adversarial security review** of the first story found one blocking bug the tests had missed
  (two CycloneDX license entries concatenated as text could turn a `Reject` into an `Allow`). It was
  reproduced, fixed case-first, and given a canary, like every fix after it.
- **CI** (GitHub Actions, and a `Jenkinsfile` over the same `scripts/ci.sh`): lint, types (`core/` under
  `mypy --strict`), tests, canaries and `pip-audit`. On GitHub Actions it was seen failing on purpose
  twice: a broken case stops it at `test`, a known-vulnerable dependency stops it at `audit`. The
  `Jenkinsfile` was run on a local Jenkins (`ci/jenkins-local/`): green on `main`, red at `test` on a
  branch with a broken case.

## Limits

- The reviewer name is recorded as typed; there is no authentication.
- The ledger is append-only by code, not tamper-evident (no hash chain).
- One model provider, no streaming, no code-execution sandbox: out of scope at this size.
- Jenkins was run locally in Docker, not on a shared CI server; the audit probe was run on Actions only.

## How this was built

With Claude Code. The process is in the repo: `stories/` (what each story must do, with its cases),
`docs/design/` and `docs/tasks/`, `AGENTS.md` (what any coding agent must know here), `DOCTRINE.md` (each
decision with what it costs), and a commit history where every commit carries its co-author. Built with
Claude Code driven by a personal harness of skills and hooks; repo-side artifacts are included, the
harness is not.
