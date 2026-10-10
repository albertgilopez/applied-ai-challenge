# Design — STORY-B01: manifest validator

Spec: `stories/STORY-B01.md` (DR-1..DR-10), cases: `stories/STORY-B01.cases.yaml` (SB1-01..SB1-14).
Level: **simple-medium** — one pure module in `core/`, a thin CLI package, samples. Same shape as the
SBOM agent: the file is data, a policy file says what the organisation allows, pure code decides.

## Modules

```mermaid
flowchart LR
  M[manifest.yaml] --> L[app/files.py: load_yaml_document, size cap, no duplicate keys, depth]
  P[policy.yaml] --> L
  L --> V[core/manifest.py: validate(manifest, policy) -> Result]
  V --> C[marketplace/cli.py: validate, exit 0 / 1 / 2, --json]
```

```text
 manifest.yaml ──┐
                 ├─► app/files.py  load_yaml_document  (size cap, duplicate keys refused, depth)
 policy.yaml ────┘                         │ plain dicts
                                           ▼
                    core/manifest.py  validate(manifest, policy) → Result(verdict, findings)
                       schema (DR-1) · secrets (DR-2) · wildcards (DR-3) · data → egress/model (DR-4)
                       effects → human (DR-5) · pinned + scanned (DR-6) · accountable (DR-7) · lifecycle (DR-8)
                                           │
                                           ▼
                    marketplace/cli.py  validate --manifest --policy [--json]  → exit 0 / 1 / 2
```

## Key decisions

- **The schema is code, not a JSON Schema file.** A table of fields per object (`required`, `optional`,
  type, enum) walked by one function that reports every problem with its dotted path. A dependency on
  `jsonschema` would add a package to audit for twenty lines of rules, and its messages are not the
  ones a manifest author needs. Unknown fields are findings (DR-1), so a typo cannot silently disable a rule.
- **Rules run even after schema findings, on what is there.** DR-9 wants every finding in one pass; each
  rule reads defensively (`get` with defaults) and adds findings, never raises.
- **Secret detection is a format check (DR-2).** Credentials have recognisable formats (provider key
  prefixes, PEM headers, `user:pass@` in a URL); a pattern is the right tool for a format. The finding
  names the path and the kind of secret and never the value. `secrets[].ref` must start with `vault://`.
- **Data sensitivity selects the allowed hosts and providers (DR-4)** from the policy. `restricted` lists
  nothing external in the sample policy, so a restricted asset cannot call an external model at all.
- **Effects are the harness's vocabulary (DR-5)** plus `physical`, which hardware assets need: an MCP
  server that drives a lab instrument is the clearest case for a human in the loop.
- **Exit codes**: 0 accept, 1 reject, 2 unreadable (missing file, invalid YAML, over the size cap). A
  CI step can fail the build on anything but 0, and a script can tell "unsafe" from "broken file".
- **Output**: `--json` prints the result as data (raw); the default prints one line per finding through
  `core.report.safe_text`.

## File map

```
CREATE: core/manifest.py
CREATE: marketplace/__init__.py, marketplace/__main__.py, marketplace/cli.py
MODIFY: app/files.py (load_yaml_document, shared by policy and manifest loading)
CREATE: samples/marketplace/policy.yaml
CREATE: samples/marketplace/manifests/{test-plan-agent,security-triage-skill,lab-instrument-mcp,simulation-jobs-mcp,eval-pack}.yaml
CREATE: samples/marketplace/unsafe/*.yaml (one per rule, for the demo)
CREATE: tests/story_b01/{__init__,test_validator,test_cli}.py
MODIFY: scripts/canaries.py (one mutation per rule), pyproject.toml (mypy files += marketplace)
```

## Risks

- **Secret formats are a list**: a new provider's format is not caught until it is added. The schema
  limits where free text can live (summary, names), and the scan in Bitbucket/Jenkins is the second net.
- **The policy is trusted input**: whoever edits it decides what is allowed; it is reviewed like code.
