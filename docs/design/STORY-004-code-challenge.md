# STORY-004 — adversarial review of the code (2026-10-11)

The design review (`STORY-004-challenge.md`) ran before there was code. This one ran on the implemented
KeysBench (T1–T11, at `6b69152`): six lenses in three opposed pairs, each finding then given to a
verifier whose job was to **refute** it by reproducing it in a scratch directory, never by reading the
author's notes. Only what was reproduced (CONFIRMED) was changed, test first, each change with a
mutation seen failing.

| Pair | Lens | Its counterweight |
|---|---|---|
| 1 | **1A** scale, cost and performance at full size | **1B** what can be removed, merged or deferred |
| 2 | **2A** security and integrity (confinement, reward hacking, the measure gamed) | **2B** usefulness to the person who will decide with it |
| 3 | **3A** throw it away and rebuild on the 2026 state of the art | **3B** defend it, then find its holes |

## Findings and what was done

Verdicts: **C** confirmed (reproduced), **S** suspected (plausible, not reproduced), **R** refuted.

| # | Finding | Lens | Verdict | Change | Commit |
|---|---|---|---|---|---|
| 1 | The `.cmd` shim of the CLI cuts the multi-line prompt at the first newline: 19 arguments sent, 4 received (no model, no budget, no tools) | 3B | C | The CLI's executable is called directly; a `.cmd` with a multi-line prompt is refused | `a3b2ff7` |
| 2 | A stored A attempt holds absolute paths, so its replay audits as `invalid` | 3B, 2A | C | Workspace path stored as `<W>`, mapped back on restore | `a3b2ff7` |
| 3 | A CLI timeout did not stop the CLI's children (a 2 s limit took 12 s) | 3B (verifier) | C | The whole process tree is killed | `a3b2ff7` |
| 4 | S4-17's "inside" row used a relative path the CLI never writes | 3B (verifier) | C | Case amended to an absolute path | `a3b2ff7` |
| 5 | The design promised `blockReadsOutsideWorkingDirectories` and `dontAsk`; the code had neither | 3B | C | The setting added (key path from the CLI binary); `dontAsk` dropped from the design (the environment scrub forces mode `default`) | `a3b2ff7` |
| 6 | Hidden tests sat next to contestant code: KB-04 passed by parsing the reference values | 2A | C | Contestant code runs in a container that mounts only the code under test | `1513951` |
| 7 | KB-03: the driver read the simulator's oracle from the shared process, or forged the result line and exited | 2A | C | Simulator stays in the test process; the driver gets its session over a pipe | `1513951` |
| 8 | Walking up from the interpreter reached the benchmark's own solution | 2A | C | Same container: nothing of the repository is mounted | `1513951` |
| 9 | The judge's budget stop escaped the attempt: no ledger line, spend lost | 3B | C | Caught; the attempt is `budget_stopped` with its spend | `e5bbc46` |
| 10 | Tool errors carried the temporary path and the OS locale, so replay missed | 3B | C | Errors name the relative path only | `5debd8b` |
| 11 | The streamed request id was always empty | 3B | C | Read from the stream | `5debd8b` |
| 12 | An attempt that errored after a 0.41 USD call recorded 0 and was never retried | 1A | C | Spend on every row; an error is retried once; `retry-after` honoured; one live run per output directory | `441aecb` |
| 13 | The first CLI attempt was handed the whole remaining cap and no turn limit | 1A | C (code read + CLI docs) | B's bound: `--max-turns`, a per-attempt budget, one turn of headroom | `441aecb` |
| 14 | A message repeated in the CLI transcript was priced from its first, possibly partial, usage | 1A | S | Priced from its largest usage (cheap, no downside) | `441aecb` |
| 15 | The canary stage took 30 of CI's 45 minutes, before containers added ~1 s per call | 1A | C (CI log) | Each mutation runs the tests that cover its file; each selection's clean run must pass first | `441aecb` |
| 16 | A canary on the judge's quote check survived in CI | 1A (CI) | C | A test that isolates that check | `1513951` |
| 17 | The reduction order's step 2 could not be expressed (k per model only) | advisor, 1B | C | Steps as data in the plan; undecided steps can be projected, not applied | `6021b21` |
| 18 | A one-task pilot priced every task like the smallest | 1A | C (arithmetic) | Projection scaled by task size measured on a reference contestant; `keysbench project` | `6021b21` |
| 19 | The report never said what the tasks and configurations were; statistics unexplained | 2B | C | Legend, track column, glosses | `6021b21` |
| 20 | No answer: the first thing a reader met was a 72-row table | 2B | C | An Answer section computed from the results, and a task × contestant table | `6021b21` |
| 21 | The sample-size cost priced the whole grid, about 20× the pair being compared | 2B | C (2122 vs 105.6 USD) | Per pair: discordance, tasks for 5/10/15 points, cost for the two | `6021b21` |
| 22 | `not_run` claimed a "protocol written" that did not exist | 2B | C | Claim removed from the plan and the spec | `6021b21` |
| 23 | No A − B row (the product against the API loop) | 2B | C | Added | `6021b21` |
| 24 | After a budget stop the run went on, so a cheaper attempt could still run | 1B | C | The rest of the run is recorded as stopped without a call | `6021b21` |
| 25 | Stored A attempts were not checked for keys | 2A | C | Keys redacted on the way in | `6021b21` |
| 26 | The audit missed `$HOME`, `%USERPROFILE%`, UNC, `cd -` and glob prefixes | 2A | S, then C (7 of 9 forms reproduced) | Audit widened; it remains detection | `6021b21` |
| 27 | A review could close the judge's `<review>` block; device names passed the gate; a quote of the whole limits block passed KB-05 | 2A | C | Neutralised; refused; a new test and hack | `6021b21` |
| 28 | Two copies of the path rule had drifted | 1B | C | One `relative_path()` | `025882c` |
| 29 | A second copy of the judge's `max_tokens` | 1B | C | The reservation reads the request | `025882c` |
| 30 | Rebuild on Inspect AI with `inspect_swe`, or on Harbor | 3A | — | Not adopted; see below | — |
| 31 | Two report tables repeat the per-task rows (Per task and Cells) | 1B | C | Kept: Cells carries pass^k, Wilson and saturation, which Per task does not | — |

## Trade-offs decided

- **Containers for grading, not for the agent phase.** The grading container is a few dozen lines and
  closes findings 6–8 completely. Containerising the CLI agent phase as well would need the network for
  the API, the CLI installed in the image, and the transcript audit redone inside it: a larger change
  whose benefit is defence in depth on top of the CLI's own permission rules. The report states the limit
  instead: the audit of A and A0 is detection, and Python can build a path the transcript does not show.
- **Not rebuilt on a framework (3A).** Inspect AI and Harbor would bring a sandbox and a runner, but the
  three properties this benchmark rests on have no equivalent there: a grader seen failing before it is
  trusted, a judge verdict frozen with its digests, and an unpriced cost kept as unknown rather than zero.
  Inspect also scores a cost limit as incorrect, where here a stop is not an attempt. The lens's own
  strongest point, that `docker run --network none` is a few dozen lines, is what was adopted.
- **The live run before the repository is public.** Once the solutions are on GitHub, an A contestant
  with a network could fetch them.
- **Step 4 of the reduction order is not mine to decide.** It is in the plan as a recommendation, with
  `decided: false`, so the runner can project it and cannot apply it.

## Cost of the review

Agent tokens, aggregated per agent with no input/output split (so no dollar figure is derived): the six
lenses 346k (1A), 324k (1B), 292k (2A), 274k (2B), 297k (3A), 325k (3B); the two verifiers that ran,
277k and 295k. About 2.43 million in all. The suite went from 482 to about 570 tests and from 47 s to
about 170 s, almost all of it the grading container.

## Found by the live run, after the review

The review read the code; the live grid read what the code did with real model output. Five instrument
errors came from it, none from a model, each fixed with a test first, the affected attempts voided (the
ledger keeps the original lines) and re-scored or rerun:

| # | What the run showed | Cause | Fix |
|---|---|---|---|
| L1 | Every A0 and A edit denied in the pilot | the environment scrub forces permission mode `default` and no rule allowed `Edit` | `Edit(./**)`, `Write(./**)` and a governed workspace rule (`aedc4cc`) |
| L2 | A Haiku attempt in A `invalid` for `# mean of noise ~ 0` | any tilde read as the home directory | only `~/` or a `~` that ends a command (`253fb1a`) |
| L3 | KB-06: 14 of 21 reviews that named the defect failed | a code check required the planted line's text (`/ 20`) in the quote | removed; the judge decides, code checks the quote is in the review (`7dad93a`) |
| L4 | KB-05: Sonnet, Opus and Fable quoted the manual's explanatory sentence and failed | the key held only the two limit lines | the key holds the sentence and its clauses; alternative right answers score 1 in `check-graders` (`7dad93a`) |
| L5 | Haiku in A `invalid` for `2%/sqrt(N)` in a comment; a URL written into a `.py` file not seen | Python read as shell text; written files not audited | Python is read by its single-token string literals, written `.py` files included, task literals excluded; 76 stored attempts re-audited: one verdict changed, no new invalid (`2306437`) |

L5 matters beyond the false positive: the repository went public before configuration A ran, and
without it a contestant could have fetched a published solution from a script it wrote.

**L6, configuration A not run.** The CLI with Python was granted Python by rule (`Bash(python *)`) and
denied it by matcher: the matcher splits a command on newlines and operators and needs every part to
match a rule, so heredocs, multi-line `python -c` and the shell around them (`cat > t.py`, `rm`, `cd ... &&`)
were refused. 56 denials in 13 attempts; 6 of the 13 reached the turn cap. A read as "Python makes the
models worse" (A − B −67 points on the preview), which was the harness, not the models. The 13 attempts
are voided, A is in the plan's `not_run` with this reason, and the fix is the CLI in a container with
egress only to the API, not a wider allow list on the host (`rm` behind an after-the-fact audit). The same
look found that the CLI's turn cap was recorded as `error` and retried at a cost, while B grades what its
step cap leaves: the CLI now does the same.

**Open, written as a limit.** The audit is the fifth patch of the day and the A attempts showed two more
false-positive kinds (`https://x` as test data in a URL-parsing task, `/.git/*` as a filter argument). The
design change is that the audit flags and each flag is judged on its quoted evidence, verdict frozen in the
ledger. With A not run, A0 has no audit finding, so no result here depends on it.
