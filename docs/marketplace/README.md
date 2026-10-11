# Challenge B: an internal marketplace for AI assets

- **Design doc** (4 pages, one diagram): [`DESIGN.md`](DESIGN.md), also rendered as [`DESIGN.pdf`](DESIGN.pdf).
- **Working piece**: a manifest validator that rejects unsafe manifests, with tests.
  - Spec and cases: [`stories/STORY-B01.md`](../../stories/STORY-B01.md).
  - Code: `marketplace/` (CLI), `core/manifest.py` (rules), `app/strict_yaml.py` (loader).

## Try it

```bash
uv sync
P=samples/marketplace/policy.yaml
uv run python -m marketplace validate --manifest samples/marketplace/manifests/lab-instrument-mcp.yaml --policy $P
uv run python -m marketplace validate --manifest samples/marketplace/unsafe/lab-instrument-unsafe.yaml --policy $P
uv run python -m marketplace validate --manifest samples/marketplace/unsafe/lab-instrument-unsafe.yaml --policy $P --json
```

**Sample manifests.** These are the four example assets of the brief plus our own evaluation pack. All
five are accepted:

| Manifest | Kind | Tier |
|---|---|---|
| test-plan-agent | agent | 2 |
| security-triage-skill | skill | 2 |
| lab-instrument-mcp | mcp-server | 3 |
| simulation-jobs-mcp | mcp-server | 3 |
| eval-pack | eval-pack | 1 |

**Unsafe manifest.** The demo asset has a token pasted in, a wildcard resource, a model API it may not
call, an unapproved physical tool, and an unpinned artifact with a scan of another digest. The validator
rejects it with 8 findings at tier 3. The token is never printed.

**Exit codes.**

| Code | Meaning |
|---|---|
| 0 | accepted |
| 1 | rejected |
| 2 | the manifest cannot be read, or the policy is invalid |

## What it checks

Seven rules, each finding named with its rule, the path in the manifest, a message and a hint for the fix:

1. **Well-formed.** Exact types. Read with a strict YAML subset that refuses duplicate keys, aliases,
   merge keys and tags.
2. **No secret inside.** Secrets only as `vault://` references under the owner's team.
3. **Named precisely.** No wildcards, no forbidden scopes, hosts matched exactly.
4. **Data decides where it may go.** Each model provider and egress host must be allowed for the data's
   sensitivity.
5. **Effects that reach the world need a human.**
   - Every asset lists its tools, each with a definition digest.
   - A write to a physical system needs a physical tool.
6. **Pinned and scanned.** The artifact is pinned by digest, and the scan covers that exact digest.
7. **Accountable.** The owner and the source are on approved domains.

The result also carries the risk tier (1-3) that decides who signs, and the digests of the manifest, the
policy and the validator.

## How it was verified

- **Every rule seen failing.** Every acceptance criterion cites a case, and one generic test runs every
  case through the real CLI. The canaries break each rule and each loader guard on purpose, and the suite
  must go red.
- **The design was challenged twice before the code was trusted.** Each time, six reviewers argued in
  opposing pairs and verifiers reproduced every claim:
  - [`STORY-B01-challenge.md`](../design/STORY-B01-challenge.md), on the validator's own design.
  - [`marketplace-mcp-vs-cli-challenge.md`](../design/marketplace-mcp-vs-cli-challenge.md), on CLI vs
    MCP delivery. It found an asset that escaped the tool rule by changing its `kind`. That is now fixed
    and has its own canaries.

## Limits

- **What the validator checks.** It checks what a manifest *says*: shape, policy, and consistency with
  the scan evidence the pipeline attached.
- **What it does not do.** It does not scan code for secrets (a separate scanner does) and does not see
  how assets are combined at install.
- **Described in the design, not built.** The registry, the sign-off flow and the asset runtime (catalog
  gate, approve-then-run, login identity).
- **Stretch goal not built.** The working piece is the validator, not an MCP server; the design doc
  explains why the governance is the same either way.
