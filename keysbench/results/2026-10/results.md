# keysbench-2026.10

Tasks: 6 · Ranking: none: n \<= 8 tasks · Prices checked on 2026-10-09 (global) · Last attempt: 2026-10-11T10:49:16Z

## Decision memo

### Answer

- **6 tasks** (4 domain, 2 history). No ranking: the scorer defines none for 8 tasks or fewer.
- **A0: 3 of 4 contestants passed every attempt of every task.** Among them, cost per pass runs from 0.0018 USD (claude-haiku-5-5) to 0.1356 USD (claude-fable-5-1), 77 times as much for the same result. Misses: claude-sonnet-5-5 passed KB-05 2 of 3 times.
- **B: 5 of 7 contestants passed every attempt of every task.** Among them, cost per pass runs from 0.0031 USD (claude-haiku-5-5) to 0.1614 USD (google/gemini-3.1-pro-preview), 51 times as much for the same result. Misses: claude-fable-5-1 passed KB-05 1 of 3 times; qwen/qwen3-coder-next passed KB-01 1 of 3 times; qwen/qwen3-coder-next passed KB-05 2 of 3 times.
- **Solved by every A0 contestant:** KB-01, KB-02, KB-03, KB-04, KB-06; the cheapest that did each is in the Commodity table.
- **Solved by every B contestant:** KB-02, KB-03, KB-04, KB-06; the cheapest that did each is in the Commodity table.
- **Hardest pair to tell apart:** A0 · claude-fable-5-1 and A0 · claude-haiku-5-5, level over 6 tasks; a 15-point difference could not occur at their measured discordance.

### At a glance: passes / attempts

| task | A0 · claude-fable-5-1 | A0 · claude-haiku-5-5 | A0 · claude-opus-5-5 | A0 · claude-sonnet-5-5 | B · claude-fable-5-1 | B · claude-haiku-5-5 | B · claude-opus-5-5 | B · claude-sonnet-5-5 | B · google/gemini-3.1-pro-preview | B · openai/gpt-5.6-sol | B · qwen/qwen3-coder-next |
|---|---|---|---|---|---|---|---|---|---|---|---|
| KB-01 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 1 / 3 |
| KB-02 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 |
| KB-03 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 |
| KB-04 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 |
| KB-05 | 3 / 3 | 3 / 3 | 3 / 3 | 2 / 3 | 1 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 2 / 3 |
| KB-06 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 |

### Reading this

| task | track | what it asks |
|---|---|---|
| KB-01 | history | Fix the crash on deeply nested license expressions |
| KB-02 | history | Fix two SBOM parsing gaps: the product's sub-components, and documents in two formats |
| KB-03 | domain | Write the KX-100 driver's measurement function from the manual |
| KB-04 | domain | Uncertainty budget (GUM, first order) for a KX-100 reading |
| KB-05 | domain | Decline a request the manual says the meter cannot meet, quoting the limit |
| KB-06 | domain | Review a small driver change with one planted defect |

Configurations (B has every model; the CLI configurations, Anthropic's, have Anthropic's models):

- B: the API called directly from this repository's agent loop, with three file tools (list, read, write) and no code execution
- A0: Claude Code (the CLI, as shipped) with its file tools, no code execution

Terms:

- pass rate: passes / attempts in one cell (one task, one contestant)
- pass^k: the chance that all k attempts pass, the reliability of a contestant on a task
- task-clustered 95 % interval: a t interval over per-task pass rates: the task, not the attempt, is the independent unit, so the interval is as wide as the number of tasks makes it
- cost per pass: everything the contestant's attempts cost (USD, measured usage at list prices) / passes
- discordance: the chance that one attempt of each of two contestants disagree on a task; it sets how many tasks a difference between them needs to be detected

### Per task

| task | track | config | model | effort | passes / attempts | cost per pass (USD) | p95 latency (s) |
|---|---|---|---|---|---|---|---|
| KB-01 | history | A0 | claude-fable-5-1 | high | 3 / 3 | 0.1293 | 54.7 |
| KB-01 | history | A0 | claude-haiku-5-5 | high | 3 / 3 | 0.0018 | 30.8 |
| KB-01 | history | A0 | claude-opus-5-5 | high | 3 / 3 | 0.0382 | 36.0 |
| KB-01 | history | A0 | claude-sonnet-5-5 | high | 3 / 3 | 0.0177 | 16.6 |
| KB-01 | history | B | claude-fable-5-1 | high | 3 / 3 | 0.3170 | 60.0 |
| KB-01 | history | B | claude-haiku-5-5 | high | 3 / 3 | 0.0039 | 24.1 |
| KB-01 | history | B | claude-opus-5-5 | high | 3 / 3 | 0.1195 | 37.7 |
| KB-01 | history | B | claude-sonnet-5-5 | high | 3 / 3 | 0.0593 | 25.0 |
| KB-01 | history | B | google/gemini-3.1-pro-preview | high | 3 / 3 | 0.5179 | 695.1 |
| KB-01 | history | B | openai/gpt-5.6-sol | high | 3 / 3 | 0.0380 | 34.7 |
| KB-01 | history | B | qwen/qwen3-coder-next | high | 1 / 3 | 0.0241 | 121.3 |
| KB-02 | history | A0 | claude-fable-5-1 | high | 3 / 3 | 0.1085 | 30.4 |
| KB-02 | history | A0 | claude-haiku-5-5 | high | 3 / 3 | 0.0012 | 21.6 |
| KB-02 | history | A0 | claude-opus-5-5 | high | 3 / 3 | 0.0483 | 31.6 |
| KB-02 | history | A0 | claude-sonnet-5-5 | high | 3 / 3 | 0.0186 | 11.4 |
| KB-02 | history | B | claude-fable-5-1 | high | 3 / 3 | 0.3548 | 53.3 |
| KB-02 | history | B | claude-haiku-5-5 | high | 3 / 3 | 0.0040 | 19.6 |
| KB-02 | history | B | claude-opus-5-5 | high | 3 / 3 | 0.1384 | 38.2 |
| KB-02 | history | B | claude-sonnet-5-5 | high | 3 / 3 | 0.0642 | 24.3 |
| KB-02 | history | B | google/gemini-3.1-pro-preview | high | 3 / 3 | 0.0910 | 72.3 |
| KB-02 | history | B | openai/gpt-5.6-sol | high | 3 / 3 | 0.0451 | 28.5 |
| KB-02 | history | B | qwen/qwen3-coder-next | high | 3 / 3 | 0.0046 | 76.2 |
| KB-03 | domain | A0 | claude-fable-5-1 | high | 3 / 3 | 0.2139 | 59.3 |
| KB-03 | domain | A0 | claude-haiku-5-5 | high | 3 / 3 | 0.0031 | 50.1 |
| KB-03 | domain | A0 | claude-opus-5-5 | high | 3 / 3 | 0.0873 | 57.6 |
| KB-03 | domain | A0 | claude-sonnet-5-5 | high | 3 / 3 | 0.0345 | 25.8 |
| KB-03 | domain | B | claude-fable-5-1 | high | 3 / 3 | 0.2546 | 32.0 |
| KB-03 | domain | B | claude-haiku-5-5 | high | 3 / 3 | 0.0038 | 19.2 |
| KB-03 | domain | B | claude-opus-5-5 | high | 3 / 3 | 0.1145 | 31.4 |
| KB-03 | domain | B | claude-sonnet-5-5 | high | 3 / 3 | 0.0482 | 13.9 |
| KB-03 | domain | B | google/gemini-3.1-pro-preview | high | 3 / 3 | 0.1757 | 143.8 |
| KB-03 | domain | B | openai/gpt-5.6-sol | high | 3 / 3 | 0.0262 | 16.5 |
| KB-03 | domain | B | qwen/qwen3-coder-next | high | 3 / 3 | 0.0022 | 18.3 |
| KB-04 | domain | A0 | claude-fable-5-1 | high | 3 / 3 | 0.1176 | 38.2 |
| KB-04 | domain | A0 | claude-haiku-5-5 | high | 3 / 3 | 0.0017 | 35.7 |
| KB-04 | domain | A0 | claude-opus-5-5 | high | 3 / 3 | 0.0436 | 42.7 |
| KB-04 | domain | A0 | claude-sonnet-5-5 | high | 3 / 3 | 0.0216 | 14.4 |
| KB-04 | domain | B | claude-fable-5-1 | high | 3 / 3 | 0.2111 | 31.6 |
| KB-04 | domain | B | claude-haiku-5-5 | high | 3 / 3 | 0.0031 | 20.9 |
| KB-04 | domain | B | claude-opus-5-5 | high | 3 / 3 | 0.0953 | 32.8 |
| KB-04 | domain | B | claude-sonnet-5-5 | high | 3 / 3 | 0.0354 | 17.8 |
| KB-04 | domain | B | google/gemini-3.1-pro-preview | high | 3 / 3 | 0.0974 | 59.2 |
| KB-04 | domain | B | openai/gpt-5.6-sol | high | 3 / 3 | 0.0279 | 35.2 |
| KB-04 | domain | B | qwen/qwen3-coder-next | high | 3 / 3 | 0.0019 | 27.9 |
| KB-05 | domain | A0 | claude-fable-5-1 | high | 3 / 3 | 0.0949 | 21.7 |
| KB-05 | domain | A0 | claude-haiku-5-5 | high | 3 / 3 | 0.0009 | 10.3 |
| KB-05 | domain | A0 | claude-opus-5-5 | high | 3 / 3 | 0.0304 | 12.9 |
| KB-05 | domain | A0 | claude-sonnet-5-5 | high | 2 / 3 | 0.0262 | 8.6 |
| KB-05 | domain | B | claude-fable-5-1 | high | 1 / 3 | 0.3025 | 13.0 |
| KB-05 | domain | B | claude-haiku-5-5 | high | 3 / 3 | 0.0010 | 6.7 |
| KB-05 | domain | B | claude-opus-5-5 | high | 3 / 3 | 0.0250 | 14.3 |
| KB-05 | domain | B | claude-sonnet-5-5 | high | 3 / 3 | 0.0144 | 8.5 |
| KB-05 | domain | B | google/gemini-3.1-pro-preview | high | 3 / 3 | 0.0481 | 47.0 |
| KB-05 | domain | B | openai/gpt-5.6-sol | high | 3 / 3 | 0.0078 | 7.6 |
| KB-05 | domain | B | qwen/qwen3-coder-next | high | 2 / 3 | 0.0011 | 7.8 |
| KB-06 | domain | A0 | claude-fable-5-1 | high | 3 / 3 | 0.1496 | 66.8 |
| KB-06 | domain | A0 | claude-haiku-5-5 | high | 3 / 3 | 0.0018 | 53.3 |
| KB-06 | domain | A0 | claude-opus-5-5 | high | 3 / 3 | 0.0522 | 50.4 |
| KB-06 | domain | A0 | claude-sonnet-5-5 | high | 3 / 3 | 0.0254 | 27.5 |
| KB-06 | domain | B | claude-fable-5-1 | high | 3 / 3 | 0.2033 | 31.7 |
| KB-06 | domain | B | claude-haiku-5-5 | high | 3 / 3 | 0.0031 | 20.6 |
| KB-06 | domain | B | claude-opus-5-5 | high | 3 / 3 | 0.0860 | 30.9 |
| KB-06 | domain | B | claude-sonnet-5-5 | high | 3 / 3 | 0.0374 | 18.2 |
| KB-06 | domain | B | google/gemini-3.1-pro-preview | high | 3 / 3 | 0.0382 | 34.0 |
| KB-06 | domain | B | openai/gpt-5.6-sol | high | 3 / 3 | 0.0193 | 19.3 |
| KB-06 | domain | B | qwen/qwen3-coder-next | high | 3 / 3 | 0.0016 | 20.8 |

### Commodity: tasks every contestant of a configuration solved, and the cheapest that did

| task | config | cheapest passing model | cost per pass (USD) |
|---|---|---|---|
| KB-01 | A0 | claude-haiku-5-5 | 0.0018 |
| KB-02 | A0 | claude-haiku-5-5 | 0.0012 |
| KB-03 | A0 | claude-haiku-5-5 | 0.0031 |
| KB-04 | A0 | claude-haiku-5-5 | 0.0017 |
| KB-06 | A0 | claude-haiku-5-5 | 0.0018 |
| KB-02 | B | claude-haiku-5-5 | 0.0040 |
| KB-03 | B | qwen/qwen3-coder-next | 0.0022 |
| KB-04 | B | qwen/qwen3-coder-next | 0.0019 |
| KB-06 | B | qwen/qwen3-coder-next | 0.0016 |

### Failure modes

| mode | task | config | model | count |
|---|---|---|---|---|
| limit set below what the report allows | KB-01 | B | qwen/qwen3-coder-next | 2 |
| quote does not support the decision | KB-05 | A0 | claude-sonnet-5-5 | 1 |
| quote does not support the decision | KB-05 | B | claude-fable-5-1 | 2 |
| quote not in the manual | KB-05 | B | qwen/qwen3-coder-next | 1 |

### What a decision would need

- Measured discordance between contestants: 0.0652
- Tasks needed to detect a 15-point difference: —
- Estimated cost of such a month at this run's prices (USD): —
- measured discordance 0.0652 over 162 contestant-task pairs is below 0.15: a 15-point paired difference, alpha 0.05 two-sided, power 0.8 cannot occur

Per pair of contestants in a configuration, the closest first (the hardest decision):

| config | x | y | tasks | mean difference | discordance | tasks for 5 points | tasks for 10 points | tasks for 15 points | a month for the two at 15 points (USD) |
|---|---|---|---|---|---|---|---|---|---|
| A0 | claude-fable-5-1 | claude-haiku-5-5 | 6 | +0.00 | 0.00 | — | — | — | — |
| A0 | claude-fable-5-1 | claude-opus-5-5 | 6 | +0.00 | 0.00 | — | — | — | — |
| A0 | claude-haiku-5-5 | claude-opus-5-5 | 6 | +0.00 | 0.00 | — | — | — | — |
| B | claude-haiku-5-5 | claude-opus-5-5 | 6 | +0.00 | 0.00 | — | — | — | — |
| B | claude-haiku-5-5 | claude-sonnet-5-5 | 6 | +0.00 | 0.00 | — | — | — | — |
| B | claude-haiku-5-5 | google/gemini-3.1-pro-preview | 6 | +0.00 | 0.00 | — | — | — | — |
| B | claude-haiku-5-5 | openai/gpt-5.6-sol | 6 | +0.00 | 0.00 | — | — | — | — |
| B | claude-opus-5-5 | claude-sonnet-5-5 | 6 | +0.00 | 0.00 | — | — | — | — |
| B | claude-opus-5-5 | google/gemini-3.1-pro-preview | 6 | +0.00 | 0.00 | — | — | — | — |
| B | claude-opus-5-5 | openai/gpt-5.6-sol | 6 | +0.00 | 0.00 | — | — | — | — |
| B | claude-sonnet-5-5 | google/gemini-3.1-pro-preview | 6 | +0.00 | 0.00 | — | — | — | — |
| B | claude-sonnet-5-5 | openai/gpt-5.6-sol | 6 | +0.00 | 0.00 | — | — | — | — |
| B | google/gemini-3.1-pro-preview | openai/gpt-5.6-sol | 6 | +0.00 | 0.00 | — | — | — | — |
| A0 | claude-fable-5-1 | claude-sonnet-5-5 | 6 | +0.06 | 0.06 | 173 | — | — | — |
| A0 | claude-haiku-5-5 | claude-sonnet-5-5 | 6 | +0.06 | 0.06 | 173 | — | — | — |
| A0 | claude-opus-5-5 | claude-sonnet-5-5 | 6 | +0.06 | 0.06 | 173 | — | — | — |
| B | claude-fable-5-1 | qwen/qwen3-coder-next | 6 | +0.06 | 0.20 | 638 | 158 | 69 | 50.40 |
| B | claude-fable-5-1 | claude-haiku-5-5 | 6 | -0.11 | 0.11 | 347 | 85 | — | — |
| B | claude-fable-5-1 | claude-opus-5-5 | 6 | -0.11 | 0.11 | 347 | 85 | — | — |
| B | claude-fable-5-1 | claude-sonnet-5-5 | 6 | -0.11 | 0.11 | 347 | 85 | — | — |
| B | claude-fable-5-1 | google/gemini-3.1-pro-preview | 6 | -0.11 | 0.11 | 347 | 85 | — | — |
| B | claude-fable-5-1 | openai/gpt-5.6-sol | 6 | -0.11 | 0.11 | 347 | 85 | — | — |
| B | claude-haiku-5-5 | qwen/qwen3-coder-next | 6 | +0.17 | 0.17 | 521 | 129 | 56 | 1.06 |
| B | claude-opus-5-5 | qwen/qwen3-coder-next | 6 | +0.17 | 0.17 | 521 | 129 | 56 | 16.74 |
| B | claude-sonnet-5-5 | qwen/qwen3-coder-next | 6 | +0.17 | 0.17 | 521 | 129 | 56 | 7.78 |
| B | google/gemini-3.1-pro-preview | qwen/qwen3-coder-next | 6 | +0.17 | 0.17 | 521 | 129 | 56 | 27.65 |
| B | openai/gpt-5.6-sol | qwen/qwen3-coder-next | 6 | +0.17 | 0.17 | 521 | 129 | 56 | 5.14 |

## By contestant

Ordered by name; intervals are clustered by task (the task is the independent unit).

| config | model | effort | tasks | mean task pass rate | 95 % (task-clustered) | cost per pass (USD) | median latency (s) | p95 latency (s) |
|---|---|---|---|---|---|---|---|---|
| A0 | claude-fable-5-1 | high | 6 | 1.00 | [1.00, 1.00] | 0.1356 | 38.2 | 66.8 |
| A0 | claude-haiku-5-5 | high | 6 | 1.00 | [1.00, 1.00] | 0.0018 | 30.8 | 53.3 |
| A0 | claude-opus-5-5 | high | 6 | 1.00 | [1.00, 1.00] | 0.0500 | 34.7 | 57.6 |
| A0 | claude-sonnet-5-5 | high | 6 | 0.94 | [0.80, 1.00] | 0.0239 | 13.8 | 27.5 |
| B | claude-fable-5-1 | high | 6 | 0.89 | [0.60, 1.00] | 0.2703 | 31.6 | 60.0 |
| B | claude-haiku-5-5 | high | 6 | 1.00 | [1.00, 1.00] | 0.0031 | 18.0 | 24.1 |
| B | claude-opus-5-5 | high | 6 | 1.00 | [1.00, 1.00] | 0.0965 | 30.1 | 38.2 |
| B | claude-sonnet-5-5 | high | 6 | 1.00 | [1.00, 1.00] | 0.0431 | 16.1 | 25.0 |
| B | google/gemini-3.1-pro-preview | high | 6 | 1.00 | [1.00, 1.00] | 0.1614 | 54.2 | 695.1 |
| B | openai/gpt-5.6-sol | high | 6 | 1.00 | [1.00, 1.00] | 0.0274 | 19.3 | 35.2 |
| B | qwen/qwen3-coder-next | high | 6 | 0.83 | [0.54, 1.00] | 0.0038 | 20.8 | 121.3 |

## What the scaffold adds (A0 − B) and what running code adds (A − A0)

| model | effort | difference | mean paired difference | 95 % (task-clustered) | tasks |
|---|---|---|---|---|---|
| claude-fable-5-1 | high | A0-B | 0.11 | [-0.17, 0.40] | 6 |
| claude-haiku-5-5 | high | A0-B | 0.00 | [0.00, 0.00] | 6 |
| claude-opus-5-5 | high | A0-B | 0.00 | [0.00, 0.00] | 6 |
| claude-sonnet-5-5 | high | A0-B | -0.06 | [-0.20, 0.09] | 6 |

A − A0: not measured this month (a configuration it needs did not run; see Not run).

## Attempts per contestant

No reduction applied: every contestant got the planned attempts.

| config | claude-haiku-5-5 | claude-sonnet-5-5 | claude-opus-5-5 | claude-fable-5-1 | openai/gpt-5.6-sol | google/gemini-3.1-pro-preview | qwen/qwen3-coder-next |
|---|---|---|---|---|---|---|---|
| B | 3 | 3 | 3 | 3 | 3 | 3 | 3 |
| A0 | 3 | 3 | 3 | 3 | 0 | 0 | 0 |

## Voided attempts

Recorded, paid for, and left out of every figure above; run again after the fix.

- 33: KB-05 grader fixed in 7dad93a (limit lines + explanatory sentence); task version changed
- 33: KB-06 judge rule changed in 7dad93a (lexical pointer check removed); re-scored offline from the recordings
- 3: OpenRouter adapter fixes (dfe5ad3): cache writes were not priced (GPT-5.6 Sol 11 % under the charge) and the recordings sat under a path with the provider prefix as a folder.
- 1: audit false positive: a tilde in a Python comment ('noise \~ 0') read as the home directory. Fixed in the audit pattern.
- 1: audit read Python in a heredoc as shell text (/sqrt); fixed in 2306437, re-scored offline
- 8: instrument bug found by the pilot: the CLI was not allowed to edit files (permission mode default, no Edit rule), so every edit was denied; scratch in /tmp read as invalid. Fixed in aedc4cc.
- 13: not run this month: the restricted CLI granted Python by rule (Bash(python \*)) and denied it by matcher; heredocs, multi-line python -c, cat/rm/cd were refused: 56 denials in 13 attempts, 6 of 13 at the turn cap. A safe fix is the CLI in a container, not a wider allow list on the host
- 1: pilot attempt on an earlier version of KB-05 (before the hack-manual-quote-not-a-limit variant was added, aedc4cc): another digest, not the task the grid ran

## Not run

- codex-cli: not run: OpenAI's model is measured in configuration B (GPT-5.6 Sol); its own harness, the Codex CLI, needs an OpenAI account set up for this run, which was not
- claude-code-cli-with-python (configuration A): not run this month: the restricted CLI granted Python by rule (Bash(python \*)) and denied it by matcher. Heredocs, multi-line python -c and the shell idioms around them (cat \> file, rm, cd) were refused: 56 denials in 13 attempts, 6 of 13 at the turn cap. The 13 attempts are voided in the ledger. A wider allow list would put rm on the host with only an after-the-fact audit behind it; the fix is the CLI in a container
- cursor-agent: not run: its headless agent reports no per-call token usage, so cost per pass could not be measured on the same basis

## Cells

| task | config | model | passes / attempts | Wilson 95 % | pass^k | saturated | invalid | cost (USD) |
|---|---|---|---|---|---|---|---|---|
| KB-01 | A0 | claude-fable-5-1 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.3879 |
| KB-01 | A0 | claude-haiku-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.0055 |
| KB-01 | A0 | claude-opus-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.1147 |
| KB-01 | A0 | claude-sonnet-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.0531 |
| KB-01 | B | claude-fable-5-1 | 3 / 3 | [0.44, 1.00] | 1.00 | no | 0 | 0.9511 |
| KB-01 | B | claude-haiku-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | no | 0 | 0.0118 |
| KB-01 | B | claude-opus-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | no | 0 | 0.3585 |
| KB-01 | B | claude-sonnet-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | no | 0 | 0.1778 |
| KB-01 | B | google/gemini-3.1-pro-preview | 3 / 3 | [0.44, 1.00] | 1.00 | no | 0 | 1.5538 |
| KB-01 | B | openai/gpt-5.6-sol | 3 / 3 | [0.44, 1.00] | 1.00 | no | 0 | 0.1140 |
| KB-01 | B | qwen/qwen3-coder-next | 1 / 3 | [0.06, 0.79] | 0.00 | no | 0 | 0.0241 |
| KB-02 | A0 | claude-fable-5-1 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.3255 |
| KB-02 | A0 | claude-haiku-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.0037 |
| KB-02 | A0 | claude-opus-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.1448 |
| KB-02 | A0 | claude-sonnet-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.0559 |
| KB-02 | B | claude-fable-5-1 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 1.0645 |
| KB-02 | B | claude-haiku-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.0119 |
| KB-02 | B | claude-opus-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.4153 |
| KB-02 | B | claude-sonnet-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.1927 |
| KB-02 | B | google/gemini-3.1-pro-preview | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.2731 |
| KB-02 | B | openai/gpt-5.6-sol | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.1354 |
| KB-02 | B | qwen/qwen3-coder-next | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.0139 |
| KB-03 | A0 | claude-fable-5-1 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.6416 |
| KB-03 | A0 | claude-haiku-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.0094 |
| KB-03 | A0 | claude-opus-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.2620 |
| KB-03 | A0 | claude-sonnet-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.1036 |
| KB-03 | B | claude-fable-5-1 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.7638 |
| KB-03 | B | claude-haiku-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.0114 |
| KB-03 | B | claude-opus-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.3436 |
| KB-03 | B | claude-sonnet-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.1446 |
| KB-03 | B | google/gemini-3.1-pro-preview | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.5271 |
| KB-03 | B | openai/gpt-5.6-sol | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.0786 |
| KB-03 | B | qwen/qwen3-coder-next | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.0065 |
| KB-04 | A0 | claude-fable-5-1 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.3527 |
| KB-04 | A0 | claude-haiku-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.0052 |
| KB-04 | A0 | claude-opus-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.1309 |
| KB-04 | A0 | claude-sonnet-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.0648 |
| KB-04 | B | claude-fable-5-1 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.6333 |
| KB-04 | B | claude-haiku-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.0092 |
| KB-04 | B | claude-opus-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.2860 |
| KB-04 | B | claude-sonnet-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.1061 |
| KB-04 | B | google/gemini-3.1-pro-preview | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.2921 |
| KB-04 | B | openai/gpt-5.6-sol | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.0838 |
| KB-04 | B | qwen/qwen3-coder-next | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.0058 |
| KB-05 | A0 | claude-fable-5-1 | 3 / 3 | [0.44, 1.00] | 1.00 | no | 0 | 0.2847 |
| KB-05 | A0 | claude-haiku-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | no | 0 | 0.0027 |
| KB-05 | A0 | claude-opus-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | no | 0 | 0.0911 |
| KB-05 | A0 | claude-sonnet-5-5 | 2 / 3 | [0.21, 0.94] | 0.00 | no | 0 | 0.0523 |
| KB-05 | B | claude-fable-5-1 | 1 / 3 | [0.06, 0.79] | 0.00 | no | 0 | 0.3025 |
| KB-05 | B | claude-haiku-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | no | 0 | 0.0031 |
| KB-05 | B | claude-opus-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | no | 0 | 0.0749 |
| KB-05 | B | claude-sonnet-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | no | 0 | 0.0433 |
| KB-05 | B | google/gemini-3.1-pro-preview | 3 / 3 | [0.44, 1.00] | 1.00 | no | 0 | 0.1444 |
| KB-05 | B | openai/gpt-5.6-sol | 3 / 3 | [0.44, 1.00] | 1.00 | no | 0 | 0.0234 |
| KB-05 | B | qwen/qwen3-coder-next | 2 / 3 | [0.21, 0.94] | 0.00 | no | 0 | 0.0023 |
| KB-06 | A0 | claude-fable-5-1 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.4488 |
| KB-06 | A0 | claude-haiku-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.0053 |
| KB-06 | A0 | claude-opus-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.1567 |
| KB-06 | A0 | claude-sonnet-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.0761 |
| KB-06 | B | claude-fable-5-1 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.6099 |
| KB-06 | B | claude-haiku-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.0092 |
| KB-06 | B | claude-opus-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.2581 |
| KB-06 | B | claude-sonnet-5-5 | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.1122 |
| KB-06 | B | google/gemini-3.1-pro-preview | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.1146 |
| KB-06 | B | openai/gpt-5.6-sol | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.0578 |
| KB-06 | B | qwen/qwen3-coder-next | 3 / 3 | [0.44, 1.00] | 1.00 | yes | 0 | 0.0048 |

## Limits

- Six tasks and at most three attempts per contestant: the intervals are wide. This is an instrument, not a verdict; the decision memo says how many tasks a decision would need.
- History tasks come from one repository whose fixes were written with an AI assistant; domain tasks use a fictitious instrument. Tasks that show an organisation's own advantage need its own repositories.
- Configuration B has models from four providers (three through OpenRouter); A0 and A run Anthropic's CLI, so only Anthropic models. Qwen3 Coder Next has no reasoning setting: the effort is sent and has no effect.
- The judge (KB-06 only) is an Anthropic model, anonymised, never the contestant. Code checks that its quote is in the review; whether the quote is the planted defect is the judge's call (a word-level check rejected 14 of 21 correct reviews and was removed). Bias reduced, not removed.
- Configuration A0 runs the Claude Code CLI restricted and audited, not sandboxed, with file tools only. Whether code execution changes the picture is not answered this month: configuration A (the CLI with Python) ran and was voided, because the CLI's permission matcher refused most of the Python the rule allowed; the fix is the CLI in a container.
- The offline measure is not the contract metric. That is cost per accepted change on real work; this is the gate before it and the regression check after it.
