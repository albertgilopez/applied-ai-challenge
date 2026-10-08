# DOCTRINE

Decisions that shape this repo, each with what it costs. Append-only: a decision that changes
gets a new entry that supersedes the old one, it is not rewritten.

## D-01 — `core/` is pure, and a test enforces it

`core/` imports only the standard library and itself. `tests/test_boundary.py` parses every file
with `ast` and fails naming the offending import.
**Why:** the decision logic is what Legal relies on; it must be testable without a model, a
network or a vendor SDK, and it must not inherit their failures.
**Cost:** adapters in `agent/` and `review/` translate between formats.
**Measured (2026-10-08):** seen red twice before trusting it: `import anthropic` in `core/_probe.py`
and `import psycopg2` in a throwaway core module both failed `test_core_imports_only_stdlib_and_itself`
naming the file; removing the probe turned it green.

## D-02 — Fail closed

A component whose license is missing, unknown, unparseable or not verifiable is `Needs review`.
Never `Allow`.
**Why:** a false `Allow` ships a component Legal never saw; a false `Needs review` costs one
human look. The asymmetry decides it.
**Cost:** more items in the review queue when SBOMs are poor.

## D-03 — The model extracts, the code decides, and the extraction is grounded

For AI models the license often lives in prose (a model card, a custom licence). The model is used
there and only there, and it returns `{license_id, quote, restrictions[]}`. The code then checks
that `quote` appears verbatim in the card; if not, the result is `Needs review` with reason
`grounding failed`. The verdict comes from `core/` applying the policy to `license_id`.
**Why:** the model reads prose better than a regex; it should not be the one deciding, and an
unverified quote is a claim, not evidence.
**Cost:** a card that states its licence only in an image or a link is `Needs review`.

## D-04 — Fetching a model card is a `read` effect, by identifier, to a fixed host

The tool accepts a model id (`org/name`), refuses anything else, and builds
`https://huggingface.co/<id>/raw/main/README.md` itself. It never takes a URL from the model.
**Why:** a URL from the model (or from a poisoned SBOM entry) would let either one send data to
any host. With a fixed host and a public identifier that is already in the SBOM, the request
carries nothing that is not already public.
**Cost:** models hosted elsewhere need their card supplied in `samples/model-cards/`.

## D-05 — The system prompt is a governed artifact

Prompts are approved by content hash, with who approved and the evidence (`validation_ref`).
Editing a prompt revokes its approval; outside an explicit `dev` or `test` env the agent refuses
to start on an unapproved prompt, and the refusal is recorded. Any other env (`production`, `PROD`,
empty) and the default are prod: fail closed (security review H3).
**Why:** the prompt decides behaviour as much as the code does, and it is easier to change.

## D-06 — The ledger is history, not state

Every model call, tool call, decision and override is appended to a JSONL file. An override is a
new line pointing at the decision it overrides. If the ledger cannot be written, the operation
fails. On read, a last line that does not parse is an interrupted write and is skipped; any other
line that does not parse is corruption and stops the read, naming the line (security review H6).
**Why:** an audit trail with gaps is worse than a failed run.

## D-07 — CI never calls a model

Model responses are recorded once and replayed. A request the recording never saw fails the run
instead of reaching the network.
**Why:** reproducible CI, no secrets in the pipeline, and the recordings double as a regression
eval of the prompt.
