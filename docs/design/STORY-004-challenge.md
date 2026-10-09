# Adversarial review of the STORY-004 design (2026-10-09)

The first design of KeysBench (`docs/design/STORY-004.md` at `f120929`) was reviewed before any code
was written, because a design line is cheaper to change than a module.

**How.** Six reviewers in parallel, each a fresh agent with read-only access to the repo, current
documentation and the web, in three pairs chosen to pull against each other so that findings could
not only pile up:

| Pair | Lens | Its counterweight |
|---|---|---|
| 1 | scale, cost and performance at monthly, organisation-wide size | simplify: what can be cut before Sunday |
| 2 | security and integrity of the measurement (reward hacking included) | usefulness to the decision and to the panel |
| 3 | throw it away and rebuild with what exists in 2026 | defend the design, then find its internal contradictions |

Every factual claim was then given to a **verifier** whose job was to refute it by reproducing it
(scratch copies, real `harness/` classes, mock transports, no model calls). Verdicts: CONFIRMED,
SUSPECTED, REFUTED. Only confirmed findings changed the design; trade-offs between pairs were decided
by the author and are written below with the reason.

## Findings, verdicts and what changed

| # | Finding | Lenses | Verdict | Change |
|---|---|---|---|---|
| 1 | The gate resolves a relative path against the process directory, so workspace-relative tool calls were denied; absolute temp paths would make every recording unreplayable | 3, 2 | **CONFIRMED** (reproduced: `deny` for `src/a.py`) | gate takes a `base`; tools take relative paths only (DR-12) |
| 2 | Three attempts send the same first request; replay keeps the last recording, so they replay as three copies of attempt 3 | 1, 3 | **CONFIRMED** (reproduced: `['sample #3' ×3]`) | one recording per attempt (DR-12, S4-12) |
| 3 | A pytest grader that trusts the exit code passes a planted `conftest.py`, an `os._exit(0)` at import and a `pytest.py` that shadows pytest; with the code imported in-process, an object equal to everything and a patched test runner also pass | 2 | **CONFIRMED** (exit code 0 in all five) | declared files only, `python -I -B -m pytest --noconftest`, junit with expected ids, contestant code in a subprocess, the hacks as solutions that must score 0 (DR-6, DR-7, D-10) |
| 4 | The grader command had `-B` after `-m pytest`: pytest rejects it, so even the reference would score 0 | verifier | **CONFIRMED** (exit code 4) | `-B` moved to Python |
| 5 | The judge's quote was checked against the diff it is given, so a review that never found the defect could pass | 2, 3 | **CONFIRMED** | the quote must be in the contestant's review and point at the planted line (DR-8, S4-07) |
| 6 | KB-05's quote only had to be a substring of the manual: a one-character quote passed | 2 | **CONFIRMED** | the quote must contain a declared limit line; an irrelevant-quote hack must score 0 |
| 7 | `--bare` does not skip settings files: the user `env` block (naming credential files) and a broad `Bash(python *)` allowance would reach configuration A, and Python can read outside the workspace, including the solutions | 2, 3 | **CONFIRMED** (CLI help and docs; key names of the user settings checked, values not read) | `--restricted`, `--tools`, a settings file allowing Python only, no session persistence, transcript audit → `invalid` (DR-14) |
| 8 | Wilson over 21 pooled attempts treats attempts of one task as independent; task-clustered, the interval is about twice as wide ([0.20, 1.0] vs [0.45, 0.83]) | 1, 3 | **CONFIRMED** (computed, plus a cluster bootstrap) | Wilson per cell only; task-clustered intervals per contestant (DR-10, D-11) |
| 9 | Saturation removed tasks from one configuration's averages, which biased the harness delta; in a worked example it flipped its sign | 1, 3 | **CONFIRMED** | saturation flags and feeds the commodity list, never removes (DR-9) |
| 10 | "A − B" mixed what the product scaffold adds with being allowed to run code | 2, 3 | **CONFIRMED** | configuration A0 (CLI, file tools only); deltas A0 − B and A − A0, paired, with intervals |
| 11 | At effort `high` thinking counts toward `max_tokens`; 4,000 would cut attempts short, and the SDK refuses non-streaming calls above 21,333 tokens | 1 | **CONFIRMED** (SDK source, mock transport, provider docs) | streaming, 32,000, a `truncated` outcome (DR-5) |
| 12 | The budget rule was stated three ways (per attempt, per call, and a case comment that called one call an attempt); the true worst case of one Fable attempt was 2.40 USD, not 0.20, and the worst case of the grid was above the cap | 1, 3 | **CONFIRMED** (computed) | per-call reservation, a projection from a measured pilot before the grid, attempts in rounds (DR-11, S4-11) |
| 13 | A replayed attempt would report ~0 s, because the attempt latency was the wall clock around the loop | 3 | **CONFIRMED** (reproduced: 0.406 s live, 0.0 replayed) | attempt latency = sum of recorded call latencies; wall time separate (DR-4) |
| 14 | The judge was said to run both during the attempt and during scoring | 1 | **CONFIRMED** (that it was in two places); SUSPECTED (that this broke the purity rule, which binds `core/` only) | the judge runs during the attempt only; scoring makes no call (DR-8, S4-08) |
| 15 | The SDK's retries were inside the measured latency, and only the last request id was kept | 1 | not verified separately; accepted as low-cost | `max_retries=0`, the runner retries, each try is a call line |
| 16 | Arm B sent no cache control, so its growing history was paid in full each step while the CLI caches | 1 | **CONFIRMED** (SDK accepts top-level `cache_control`) | top-level `cache_control` in B and the judge |
| 17 | The SDK exposes the request id without a raw-response call | 1 | **CONFIRMED** (mock transport; dropped by `model_dump`) | read `_request_id` before dumping |
| 18 | Real fix commits in this repo, made after the models' training cutoff, can be tasks: their new tests fail on the parent tree and pass on the fix | 3 | **CONFIRMED** for 4 commits (one of `9e92220`'s new tests already passes on the parent and is dropped) | KB-01 and KB-02 come from `341fb07` and `9e92220` via `extract.py`, the monthly-feed pipeline in miniature |
| 19 | Nothing in the report answered the requester's question in her terms; "no ranking" would be heard as "nothing to show" | 2 | accepted (a judgement, not a fact) | a decision memo first: per-task results, commodity list with the cheapest passing contestant, failure modes, and the tasks and cost a decision-grade month needs (S4-19) |
| 20 | A container runner exists for this (Harbor, the Terminal-Bench 2.0 harness), with network isolation and Codex/Cursor integrations | 3 | **CONFIRMED** (facts); not adopted | needs Python ≥ 3.12, its cost path breaks "unpriced, never 0", never run here; the task layout follows its format |
| 21 | The run had no resume: an interruption would pay twice | 1 | accepted | resume from the ledger (DR-15, S4-18) |
| 22 | Results did not record which ledger and recordings they came from | 2 | accepted | digests in `results.json` (DR-13) |

## Trade-offs decided between pairs

- **Simplify vs scale.** Seven tasks became six: the timeout task and the binary-block task went (they
  needed the simulator's timing and block machinery), two real-history tasks came in. Eight new modules
  became four. Kept for scale: per-call cost and latency, digests, resume, rounds.
- **Security vs usefulness.** Configuration A stays (it is what an organisation buys), confined and
  audited rather than dropped. The audit is labelled detection, not isolation.
- **Rebuild vs defend.** The repo's harness stays for the baseline (it is the thesis of challenge A and
  is already tested); the task format moves to the container runner's layout so the rebuild stays open.
- **Not built, presented instead:** the "moat" as a measured delta with and without the organisation's
  own context; cost per accepted change in the real pilot as the contract metric; a monthly diff and a
  scheduled pipeline.

## What the review cost

Six reviewers and three verifiers, about 2.7 M subagent tokens in total (aggregate counts reported by the
tool, without an input/output split, so no dollar figure is claimed). No model call was billed to the
benchmark's API key.
