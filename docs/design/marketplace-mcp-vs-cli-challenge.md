# Adversarial review: should marketplace assets ship as MCP servers or CLIs? (2026-10-10)

**The question.** Should assets (and the marketplace's own discovery and install) be command-line tools,
each with an enumerated catalog of actions, a gate and a ledger (the pattern of `harness/` in this repo),
instead of MCP servers? The argument for CLIs: MCP loads tool definitions into the context up front, and a
CLI is read only when it is used. The brief points the other way: its examples include "an MCP server for
controlling lab instruments", and its stretch goal is a small working MCP server.

**How the review was run.** Six reviewers worked in three opposing pairs:

- cost and scale vs simplify;
- security vs usefulness to the decision;
- rebuild vs defend-then-find-holes.

Two verifiers then tried to refute every claim:

- the code verifier ran the repo's validator and harness in scratch copies;
- the docs verifier read the primary sources (vendor docs, the MCP specification and schema, release notes,
  incident reports). Every source below was accessed on 2026-10-10.

## The answer

**The catalog, the gate and the ledger are the design, and the transport is a projection of them.**

- Each asset's manifest already enumerates its tools and their effects (`manifest.tools[]`). That list is
  the catalog.
- A CLI, an MCP `tools/list` and a `SKILL.md` can all be generated from it, and each carries the same
  definition digest.
- The gate runs behind the catalog, in a runtime the platform owns, so it applies whichever way the call
  arrives.
- The transport is then chosen per asset:
  - **CLI**: a stateless asset used on demand.
  - **Server**: an asset that holds state or drives hardware (a lab bench session, a long simulation job),
    or a client without a shell.

The context argument does not decide this in 2026: the three main agent hosts defer MCP tool definitions
by default (findings 1-2).

## Findings, verdicts and what changed

| # | Finding | Lenses | Verdict | Change |
|---|---|---|---|---|
| 1 | "MCP loads every tool definition up front" no longer holds for the main hosts. **Claude Code** defers MCP tools by default through tool search: only names and server instructions load at session start ([docs](https://code.claude.com/docs/en/mcp)). Deferral is off when the base URL is not first-party, when experimental betas are disabled, on Foundry, and on older Vertex models; an `auto` mode defers past 10% of the window. **Cursor** sends tool names only, −46.9% total tokens in an A/B test ([2026-01-06](https://cursor.com/blog/dynamic-context-discovery)). **Codex** has deferred MCP tools by default since June 2026 ([release rust-v0.142.2](https://github.com/openai/codex/releases/tag/rust-v0.142.2), PR #29486) | 2B, 3A, 3B, 1B | **CONFIRMED** (primary sources) | The design states the cost per client, with these numbers, instead of "MCP fills the context" |
| 2 | A CLI is not free either. The agent reads a discovery line, then the CLI's `--help` when it uses it. Measured on this repo: `--help` is 231-582 characters, a tool schema 284-400 | 3B | **CONFIRMED** (measured) | Same as 1 |
| 3 | The real risk axis is not CLI vs MCP. It is **a string handed to a shell vs a structured call handed to a gate**. Argument injection into pre-approved commands gives remote code execution ([Trail of Bits, 2025-10-22](https://blog.trailofbits.com/2025/10/22/prompt-injection-to-rce-in-ai-agents/): `go test -exec`, `git show --output`, `rg --pre`). This repo's harness is already structured and uses no MCP | 2A, 3B, 3A | **CONFIRMED** | A CLI asset is reached only through an allowlisted entry point that parses arguments into a catalog call, never through a general shell; credentials are not placed beside the shell |
| 4 | **Validator hole.** An asset relabelled `kind: skill` with `tools: []` was accepted (R5 only asked agents and MCP servers to list tools). At `internal` sensitivity its tier fell from 3 to 2, so the bench controller would have skipped the security and lab-safety sign-off | 1B | **CONFIRMED** (reproduced with the real validator) | **Fixed.** R5: every asset lists its tools, and a write on a system the policy names as physical (`physical_systems`) requires a declared `physical` tool. P3: such a write is tier 3 whatever the tools say. New rows in SB1-08 and SB1-15; four canaries, all killed |
| 5 | The harness could not express the manifest's `physical` effect: registering such a tool raised `ValueError` | 2A | **CONFIRMED** (reproduced) | **Fixed.** `physical` is an effect; the gate escalates it like `outward`. Test seen red, then green; one canary |
| 6 | There is no approve-then-run path. An escalated call is never executed, even after a human approves it. In MCP the human in the loop is only a SHOULD, and tool annotations MUST be treated as untrusted ([spec 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)). The annotations have no `physical` hint | 2A, 3A, 3B | **CONFIRMED** (code and spec) | **Not built; in the design.** Approval happens outside the agent's channel and is bound to the digest of that exact call; the runtime runs only the approved call |
| 7 | The reviewer identity (`--by`) in the review CLI is free text, so an agent with a shell can write any name | 3B | **CONFIRMED** (reproduced) | **Not built; named limit.** Identity comes from the login, not from an argument |
| 8 | A definition digest does not catch a change inside the implementation. postmark-mcp 1.0.16 added one line that BCC'd every email to an outside address ([The Register, 2025-09-29](https://www.theregister.com/2025/09/29/postmark_mcp_server_code_hijacked/)). No source says the tool definitions were unchanged; that part is inferred | 2A | **CONFIRMED** (the incident), **SUSPECTED** (definitions unchanged) | Design: the artifact digest covers what is installed; a remote server needs an attestation of what it runs; the definition digest alone is not enough |
| 9 | The install step of a local MCP server is a command line, which is a code-execution surface | 2A | accepted | No change: the manifest has no free-text command field, and R1 rejects any field the format does not define |
| 10 | The domain fits a server for stateful assets: a bench session, or a simulation job that runs for hours (MCP Tasks is still experimental) | 1B, 3A | accepted | Design: a table of consumers and the transport each one gets |
| 11 | One skill per asset costs about 20K tokens of listings at 200 assets, against a roughly constant cost with tool search. The larger cost is rebuilding state on every call. Code execution over MCP reported 150,000 → 2,000 tokens ([Anthropic, 2025-11-04](https://www.anthropic.com/engineering/code-execution-with-mcp)) | 1A | the source is **CONFIRMED**; the 20K is the lens's arithmetic, not measured | Discovery goes through one search entry point, not a listing of every asset |
| 12 | The design doc's list of kinds left out `eval-pack` | 1B | **CONFIRMED** | Fixed in the design doc |
| 13 | Skills distributed over MCP carry unsigned digests, so they are not a trust boundary | 3A | **SUSPECTED** (not reproduced) | Logged; no change |

## Trade-offs decided between pairs

- **CLI-first vs MCP-first.** Neither becomes doctrine. One catalog is generated into either transport, and
  each asset declares which one it ships. The governance (manifest, validator, tier, sign-off, gate,
  ledger) is the same either way, so the choice can change later without re-approving anything except
  the new artifact.
- **Every kind lists its tools (R5).** The rule could have been narrower ("only assets that write or
  reach the network"). It is not, because the tier is derived from the tools, and an asset that declares
  none would pick its own tier. The cost: a skill that is only a prompt has to declare its one `read`
  tool.
- **Build neither an MCP server nor a CLI generator before the panel.** The working piece stays the
  validator. The two holes this review found in code (findings 4 and 5) are fixed. The runtime pieces
  (findings 6 and 7) are presented as design, with their limits named.

## What the review cost

Six reviewers and two verifiers used about 2.2 M subagent tokens. These are aggregate counts with no
input/output split, so no dollar figure is claimed.
