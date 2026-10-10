# STORY-B01 — Marketplace: a manifest validator that rejects unsafe AI assets

**As** the platform team that runs an internal marketplace of AI assets (agents, skills, MCP servers)
**I want** every asset's manifest checked against the organisation's policy before it is published
**so that** nothing reaches other teams with a secret inside, a wildcard permission, an unpinned
artifact, a failed security scan, or a model call its data may not make.

Challenge B of the take-home. The design of the whole marketplace is in `docs/marketplace/DESIGN.md`;
this story is its one working piece.

## Scope

- A manifest format (YAML) that every asset declares: identity, owner, kind and domains, data
  sensitivity, the model it calls, permissions, network egress, secrets (as references), tools with
  their effects, the pinned artifact, the source, the security scan, the lifecycle state.
- An organisation policy (YAML) that the validator reads: approved egress hosts and model providers per
  sensitivity, contact domains, source hosts, scan thresholds.
- `python -m marketplace validate --manifest PATH --policy PATH [--json]`: accept or reject, with every
  finding (rule, path in the manifest, message). Exit 0 accepted, 1 rejected, 2 unreadable.
- Sample manifests for the four example assets of the brief plus one of our own, and unsafe variants.

**Why deterministic, not a model:** these are invariants that must never fail (a secret in a manifest,
a wildcard permission); the decision has to be the same every time and explainable line by line. A
model can help an author **write** a manifest or explain a rejection; it never decides acceptance.

## Interface contract

Manifest (`apiVersion: marketplace/v1`):

```
id: kebab-case                     name: str              version: semver
kind: agent | skill | mcp-server   domains: [software | hardware-firmware | simulation]
owner: { team: str, contact: email }                       summary: str
data: { sensitivity: public | internal | confidential | restricted }
model: { provider: str, id: str } | absent                 # assets that call a model
permissions: [ { resource: "<system>:<scope>", access: read | write } ]
network: { egress: [host] }                                 # empty: no network
secrets: [ { name: str, ref: "vault://<path>" } ]           # references only
tools: [ { name: str, effect: read | write | outward | physical, requires_human_approval: bool } ]
artifact: { ref: "artifactory://<repo>/<name>", digest: "sha256:<64 hex>" }
source: https URL
security_scan: { tool: black-duck | polaris, id: str, status: passed | failed, critical: int, high: int }
lifecycle: { status: draft | approved | deprecated | retired }
```

Policy:

```
contact_domains: [domain]                source_hosts: [host]
sensitivity: { <level>: { egress: [host], model_providers: [provider] } }
scan: { max_critical: int, max_high: int }
```

Result: `{ verdict: accept | reject, findings: [ { rule, path, message } ] }`; JSON keeps manifest text
raw, the terminal output escapes it.

## Domain rules

- **DR-1 Fail closed.** A manifest that does not parse, misses a required field, has a field the format
  does not define, or a value outside its enum is rejected. Unknown is never accepted.
- **DR-2 No secret inside.** A secret is declared only as a `vault://` reference. Any string anywhere in
  the manifest that has the format of a credential (provider key prefixes, private key blocks, a
  `user:password@` in a URL) rejects the manifest, and the finding never echoes the secret.
- **DR-3 No wildcard.** A permission whose scope is `*` or ends in `*`, an egress of `*` or a CIDR, or an
  access other than `read`/`write` is rejected: the manifest must say what it touches.
- **DR-4 Data decides where calls may go.** The model provider and every egress host must be approved
  for the asset's sensitivity in the policy. `restricted` (export-controlled) allows only what the
  policy lists for it, which can be nothing.
- **DR-5 Effects that reach the world need a human.** A tool with effect `outward` (sends, publishes,
  creates outside the asset) or `physical` (drives an instrument, a lab bench, firmware) must declare
  `requires_human_approval: true`.
- **DR-6 Pinned and scanned.** The artifact is pinned by a sha256 digest (no tag, no `latest`); the
  security scan passed and its critical and high counts are within the policy's thresholds.
- **DR-7 Accountable.** The owner has a team and a contact on an approved domain; the source is an
  `https` URL on an approved host; `id` is kebab-case and `version` is semver.
- **DR-8 Retired is not publishable.** A manifest whose lifecycle is `retired` is rejected for publishing.
- **DR-9 Every finding, not the first.** The validator reports every rule a manifest breaks, so an author
  fixes them in one pass; the verdict is `reject` if there is at least one.
- **DR-10 Manifest text is data.** A summary or a name that asks the validator to skip a check changes
  nothing; text printed to a terminal is escaped.

## Acceptance Criteria

- [ ] The five sample manifests (four from the brief and our own) are accepted (case: SB1-01)
- [ ] A manifest that does not parse, misses a required field or has an unknown field is rejected (case: SB1-02)
- [ ] A literal credential anywhere in the manifest is rejected and not echoed (case: SB1-03)
- [ ] A secret that is not a vault reference is rejected (case: SB1-04)
- [ ] A wildcard permission or egress is rejected (case: SB1-05)
- [ ] A model provider or egress host not approved for the sensitivity is rejected (case: SB1-06)
- [ ] An outward or physical tool without human approval is rejected (case: SB1-07)
- [ ] An unpinned artifact is rejected (case: SB1-08)
- [ ] A failed scan, or findings above the thresholds, is rejected (case: SB1-09)
- [ ] An owner contact or source host outside the policy, a bad id or version, is rejected (case: SB1-10)
- [ ] A retired manifest is rejected for publishing (case: SB1-11)
- [ ] All findings are reported in one run, each with its rule and path (case: SB1-12)
- [ ] Text in the manifest cannot skip a check, and the terminal output is escaped (case: SB1-13)
- [ ] The CLI exits 0 accepted, 1 rejected, 2 unreadable (case: SB1-14)
