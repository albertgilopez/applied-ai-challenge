# Tasks — STORY-002

Design: `docs/design/STORY-002.md`. One commit per task, test first.

| Task | What | Closes | Done when | Depends on |
|---|---|---|---|---|
| T1 | `core/model_card.py`: normalise, ground, card_license, review_model (worst of), evidence_digest | S2-01..05, S2-08, S2-09, S2-11 (logic) | unit tests green; boundary test green | — |
| T2 | harness: `Agent(output_config=...)`; `usage.py` price table, nested usage, region, per-call cost | S2-07 | harness tests green, new price tests | — |
| T3 | `samples/model-cards/*.md` (3 sample models + 2 fixtures) and `agent/model_cards.py` (id check, local, fixed host) | S2-06 | tool tests green | — |
| T4 | `agent/reviewer.py` + prompt approved by hash; parse and validate the answer | S2-01..05 via scripted answers | reviewer tests green | T1, T2, T3 |
| T5 | `review scan --model-cards --recordings --live`; `decision_key` with evidence | S2-10, S2-12 | CLI tests green; STORY-003 tests unchanged | T4 |
| T6 | record the real cassettes (live, Haiku 5.5), regenerate the sample report, canaries, README/AGENTS/STATED | all | `scripts/ci.sh all` green; canaries all red | T5 |

Graph: T1, T2, T3 in parallel → T4 → T5 → T6.
