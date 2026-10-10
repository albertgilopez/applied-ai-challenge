# STORY-B01 — Marketplace: a manifest validator that rejects unsafe AI assets

**As** the platform team that runs an internal marketplace of AI assets (agents, skills, MCP servers,
evaluation packs)
**I want** every asset's manifest checked against the organisation's policy before it is published
**so that** nothing reaches other teams with a secret inside, a vague permission, an unpinned or unscanned
artifact, a tool that acts on the world without a human, or a model call its data may not make.

Challenge B of the take-home. The design of the whole marketplace is in `docs/marketplace/DESIGN.md`;
this story is its one working piece.

> Revised after an adversarial design review (six lenses, findings reproduced by verifiers):
> `docs/design/STORY-B01-challenge.md`.

## Scope

- A manifest format (YAML) every asset declares, and an organisation policy (YAML) the validator reads.
- `python -m marketplace validate --manifest PATH --policy PATH [--json]`: accept or reject, with every
  finding (rule, path, message, hint), the computed risk tier, and the digests of what was checked.
- Sample manifests for the four example assets of the brief plus our own (an evaluation pack), and one
  unsafe manifest for the demo.

**What the validator is, and what it is not.** It is the stateless gate in the publish pipeline: it checks
what a manifest says, its shape, and its consistency with the policy and with the evidence the pipeline
attached. It does not approve assets (that is registry state, set by a human sign-off), does not scan code
for secrets (a scanner stage does), and cannot see how assets are combined at install time. Those are
named controls in the design doc.

**Why deterministic, not a model:** these are invariants that must never fail, and the answer has to be
the same every time and explainable line by line. A model can help an author write a manifest or explain
a finding; it never decides acceptance.

## Interface contract

Manifest:

```
apiVersion: marketplace/v1
id: <name>                         # 1-64 chars, lowercase letters, digits, single hyphens (the SKILL.md name rule)
version: "<semver>"                # a quoted string
kind: agent | skill | mcp-server | eval-pack
domains: [software | hardware-firmware | simulation]
owner: { team: <name>, contact: <email> }
summary: <text>
data: { sensitivity: public | internal | confidential | restricted }   # the most sensitive data it handles
model: { provider: <name>, id: <model id> }          # required if it calls a model; absent for eval-pack
permissions: [ { resource: "<system>:<scope>", access: read | write } ]
egress: [<host>]                                      # empty list: no network
secrets: [ { name: <NAME>, ref: "vault://<owner.team>/<path>" } ]
tools: [ { name: <name>, effect: read | write | outward | physical,
           requires_human_approval: <bool>, definition_sha256: <64 hex> } ]
artifact: { ref: "artifactory://<repo>/<name>", digest: "sha256:<64 hex>" }
source: <https URL>
security_scan: { tool: black-duck | polaris, id: <id>, artifact_digest: "sha256:<64 hex>",
                 status: passed | failed, critical: <int ≥ 0>, high: <int ≥ 0> }   # written by the scan stage
```

Policy: `contact_domains`, `source_hosts`, `model_hosts` (host → provider), `forbidden_scopes`,
`sensitivity.<level>.{providers, egress}`, `scan.{max_critical, max_high}`. The policy is validated too.

Result: `{ verdict: accept | reject, tier: 1 | 2 | 3, findings: [ { rule, path, message, hint } ],
checked: { api_version, manifest_sha256, policy_sha256, validator_version } }`.

Exit codes: 0 accepted · 1 rejected · 2 the manifest cannot be read (missing, not UTF-8, over the size cap,
not YAML) or the policy is invalid.

## Rules (each finding names one)

- **R1 Well-formed, or rejected.** `apiVersion` is a version this validator supports. Every required field is
  there, no field the format does not define, every value of its exact type (a boolean is not a number, a
  count is never negative, `version` is a quoted semver string) and inside its enum. A YAML document that
  parses but uses constructs a manifest has no need for (duplicate keys at any level, anchors and aliases,
  merge keys, non-string keys, custom tags) is rejected: two readers must never see two manifests.
- **R2 No secret inside.** A secret is declared only as `vault://<owner.team>/<path>` (no `..`, no other
  team's path). Any key or value with the format of a credential rejects the manifest, and **no output**
  (terminal or JSON, any rule's finding) ever contains it.
- **R3 Named precisely.** A resource follows `<system>:<scope>` with a positive grammar; a `*` anywhere, or
  a scope the policy lists as forbidden (`all`, `admin`…), is rejected. A host is a lowercase hostname: no IP
  literal, no port, no trailing dot, matched exactly against the policy.
- **R4 Data decides where it may go.** The model provider and every egress host must be approved for the
  asset's sensitivity. An egress host the policy knows as a model API requires the matching `model`. An
  evaluation pack calls no model.
- **R5 Effects that reach the world need a human, and tools are pinned.** An `outward` or `physical` tool
  declares `requires_human_approval: true` (a real boolean). An agent or MCP server lists its tools, each
  with the sha256 of its definition, so a tool that changes after approval is a new version. An evaluation
  pack has no `outward` or `physical` tool.
- **R6 Pinned and scanned.** The artifact is pinned by a sha256 digest; the scan covers **that** digest,
  passed, and is within the policy's thresholds.
- **R7 Accountable.** The owner's contact is on an approved domain (exact match after the single `@`); the
  source is an `https` URL on an approved host, with no user info, backslash, encoded backslash or port.

## Properties of the validator

- **P1 Every finding, in one pass**, each with its rule, its path in the manifest, a message and a fix hint.
- **P2 Manifest text is data.** Nothing in the manifest changes which checks run; terminal output is escaped
  and every output is redacted.
- **P3 The result says what was decided from**: the risk tier computed from the manifest (3 if any outward or
  physical tool or restricted data; 2 if any write permission or confidential data; else 1), and the digests
  of the manifest, the policy and the validator version.
- **P4 The policy fails closed too**: an unknown key, a scalar where a list is expected, a missing sensitivity
  level or threshold is exit 2, never a permissive default.

## Acceptance Criteria

- [x] The five sample manifests (four from the brief and the evaluation pack) are accepted (case: SB1-01)
- [x] A missing, unknown, mistyped or out-of-enum field, or an unsupported apiVersion, is rejected (case: SB1-02)
- [x] Duplicate keys, aliases, merge keys, non-string keys and custom tags are rejected (case: SB1-03)
- [x] A credential in any key or value is rejected and appears in no output (case: SB1-04)
- [x] A secret that is not a vault reference under the owner's team is rejected (case: SB1-05)
- [x] A wildcard, a forbidden scope or a malformed resource or host is rejected (case: SB1-06)
- [x] A provider or egress host not approved for the sensitivity, or a model API host without a model, is rejected (case: SB1-07)
- [x] An outward or physical tool without human approval, or tools without a definition digest, is rejected (case: SB1-08)
- [x] An unpinned artifact, a scan of another digest, a failed scan or findings above the thresholds are rejected (case: SB1-09)
- [x] An owner or source outside the policy, or a source URL with user info, backslash or port, is rejected (case: SB1-10)
- [x] An evaluation pack that calls a model or has an outward or physical tool is rejected (case: SB1-11)
- [x] Every finding is reported in one run with rule, path, message and hint (case: SB1-12)
- [x] Manifest text cannot change the checks, and terminal output is escaped (case: SB1-13)
- [x] The CLI exits 0 accepted, 1 rejected, 2 unreadable manifest or invalid policy (case: SB1-14)
- [x] The result carries the tier and the digests of the manifest, the policy and the validator (case: SB1-15)
- [x] An invalid policy fails closed with exit 2 (case: SB1-16)
- [x] Every case in this file is executed by a test (case: SB1-17)
