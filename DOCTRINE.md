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

## D-08 — A frozen decision is keyed on every input it was decided from

A recorded decision is reused only when its key matches: the component identity, its license
expression, its source link and the digest of the policy as loaded. A field that `decide()` starts
reading must be added to the key in the same change; two canaries remove a field each and the suite
goes red.
**Why:** keyed on identity alone, two packages with the same name and version but different licenses
shared one verdict, and a re-run ignored a policy edit (security review C12). Both are an `Allow`
that the current inputs never produced.
**Cost:** a policy change reopens every item it touches, and the reviewer looks at them again; an
override does not carry over to a new policy.

## D-09 — A benchmark result belongs to (configuration, model, effort)

Every attempt names all three plus the harness version; configurations never share a ranked table.
**Why:** the same model moves by more than the gap between neighbouring models when the harness
changes, and running code is a capability of its own (A − A0).
**Cost:** three configurations for one question.

## D-10 — A grader is trusted once it has been seen failing, reward hacks included

`check-graders` requires 1 for the reference solution and 0 for the untouched environment, a plausible
wrong answer and every hack, in CI; each grader family has a canary.
**Why:** a pytest grader that trusted the exit code passed a planted `conftest.py`, an `os._exit(0)`
and a shadowing `pytest.py`; a quote check against the wrong artifact passed a review that never found
the defect; a quote of the whole limits block passed a check meant for one line.
**Cost:** a reference, an antipattern and a set of hacks per task, written before the task is used.

## D-11 — The task is the unit of a benchmark interval

Intervals over contestants are clustered by task; Wilson is per cell only.
**Why:** attempts of one task are correlated, and pooled Wilson was about half as wide as the
task-clustered interval.
**Cost:** with few tasks, honest intervals are wide, and the report says no ranking.

## D-12 — Contestant code never runs where the answer is

It is graded in a disposable container with no network, a read-only root, a non-root user and only the
code under test mounted; expected values, oracles and the repository stay on the host.
**Why:** on the first layout four solutions passed without solving their task: one read the hidden
test's reference values, one imported the benchmark's own solution through the interpreter's path, one
read the simulator's oracle from the shared process, one forged the grader's result line (code review,
2026-10-11).
**Cost:** about a second of container start per call; the suite went from 47 s to about 170 s.
