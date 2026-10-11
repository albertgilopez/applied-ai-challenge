# KeysBench

A monthly measurement of frontier models for a software engineering team, built so the number can be
trusted before anyone decides with it. Specification: [STORY-004](../stories/STORY-004.md). Design:
[docs/design/STORY-004.md](../docs/design/STORY-004.md). Adversarial reviews of the design and of the
code: [design](../docs/design/STORY-004-challenge.md), [code](../docs/design/STORY-004-code-challenge.md).

## What it measures

The unit is a **contestant**: a configuration, a model and an effort. The same four models run in three
configurations:

| Configuration | What the model works through |
|---|---|
| **B** | the API, called from this repository's agent loop, with three file tools and no code execution |
| **A0** | Claude Code (the CLI, as shipped) with its file tools, no code execution |
| **A** | Claude Code with its file tools and Python |

Six tasks, two kinds:

| Task | Track | What it asks |
|---|---|---|
| KB-01 | history | Fix the crash on deeply nested license expressions |
| KB-02 | history | Fix two SBOM parsing gaps |
| KB-03 | domain | Write the KX-100 driver's measurement function from the manual |
| KB-04 | domain | Uncertainty budget (GUM, first order) for a KX-100 reading |
| KB-05 | domain | Decline a request the manual says the meter cannot meet, quoting the limit |
| KB-06 | domain | Review a small driver change with one planted defect (scored by a judge) |

History tasks are real fixes from this repository's own history, rebuilt from the parent commit with the
fix's tests hidden. Domain tasks use a fictitious instrument, the KX-100, with its own manual.

For each contestant the report gives pass rates with task-clustered intervals, pass^k, cost per pass,
latency, the tasks every contestant solved and the cheapest that did, the failure modes, the paired
differences between configurations (A0 − B, A − A0, A − B), and for each pair of contestants how many
tasks telling them apart would take and what that would cost. With six tasks it ranks nobody.

## Why the number can be trusted

- **Every grader is seen failing before it is trusted.** `check-graders` runs each task's untouched
  environment, its reference solution, a plausible wrong answer and a set of reward hacks through the
  grader, and requires 1 for the solution and 0 for everything else. The hacks include a planted
  `conftest.py`, a fake `pytest.py`, an exit before the report, an object equal to everything, and the
  four that a code review found passing an earlier layout (reading the hidden tests, importing the
  benchmark's own solution, reading the simulator's oracle, forging the result line).
- **Contestant code never runs next to the tests.** It runs in a container with no network, a read-only
  root, a non-root user and only the code under test mounted; expected values stay on the host.
- **The judge (KB-06 only) cannot decide alone.** Its quote must be in the review and point at the
  planted line, checked by code; it is never the contestant's model; its verdict is frozen with the
  digests of what it decided from.
- **Spend is counted, never estimated after the fact.** Each call reserves its worst case before it is
  made; every attempt's line carries what it cost; a stopped run resumes without paying twice.
- **Each guard has a mutation that must break the suite** (`scripts/canaries.py`).

## Running it

Requirements: the repository's virtual environment, and Docker (contestant code is graded in a
container).

```bash
# 1. Trust the graders (offline; the KB-06 judge calls are replayed from recordings)
python -m keysbench check-graders

# 2. Pilot, into the same output the grid will use: every contestant on the smallest task, and one cheap
#    contestant across every task as the reference for task size
python -m keysbench run --plan keysbench/plans/2026-10-pilot-a.yaml --out keysbench/results/2026-10 --live
python -m keysbench run --plan keysbench/plans/2026-10-pilot-b.yaml --out keysbench/results/2026-10 --live

# 3. Cost of the grid at every reduction step, from what the pilot measured
python -m keysbench project --plan keysbench/plans/2026-10.yaml --ledger keysbench/results/2026-10/ledger.jsonl

# 4. The grid (resumes from the pilot; refuses if the projection is above the cap)
python -m keysbench run --plan keysbench/plans/2026-10.yaml --out keysbench/results/2026-10 --live

# 5. Score (offline, same bytes every time)
python -m keysbench score --plan keysbench/plans/2026-10.yaml \
  --ledger keysbench/results/2026-10/ledger.jsonl --out keysbench/results/2026-10
```

`--live` needs `ANTHROPIC_API_KEY`. Configurations A and A0 need the Claude Code CLI pinned in the plan,
installed in its own prefix. Without `--live`, `run` replays the committed recordings and makes no call.

The plan (`keysbench/plans/2026-10.yaml`) holds the cap, the attempts per contestant, and the reduction
order decided before the run: if the projection is above the cap, a decided step is applied by setting
`applied_step`, and the report states it.

## Limits

They are printed in every report; the main ones: six tasks give wide intervals (this is an instrument,
not a verdict); one provider family; A and A0 run the CLI restricted and audited, not sandboxed (the
audit is detection); the offline measure is the gate before the contract metric, not the metric itself.
