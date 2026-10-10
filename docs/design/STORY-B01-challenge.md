# Adversarial review of the STORY-B01 design (2026-10-10)

The first design of the manifest validator (`25d35dc`) was reviewed before any code existed. Six reviewers
in three opposing pairs (scale and operation vs simplify; security vs usefulness to the decision; rebuild on
2026 standards vs defend-then-find-holes), then two verifiers that reproduced every factual claim in scratch
copies (the repo's PyYAML, Python and Node URL parsers, the coverage test).

## Findings, verdicts and what changed

| # | Finding | Lenses | Verdict | Change |
|---|---|---|---|---|
| 1 | The author wrote both `lifecycle: approved` and the scan result; nothing bound the scan to the artifact | all six | **CONFIRMED** (spec text; a made-up scan id with `passed` was accepted) | `lifecycle` and approvals leave the manifest (registry state, set by sign-off); the scan block carries `artifact_digest` and must match the artifact (R6) |
| 2 | `yaml.safe_load` keeps the last of duplicate keys without a word: `requires_human_approval: false` then `true` reads as `true` | 2A, 3B | **CONFIRMED** (reproduced, pure-Python and C loaders) | strict loader refuses duplicate keys at every level (R1) |
| 3 | A 334-byte alias document expands to 10⁸ strings; walking it for secrets took 11.6 s | 2A, 3B | **CONFIRMED** (measured) | aliases and anchors refused at compose time |
| 4 | Merge keys applied, `on:` became the key `True`, `1.10` became `1.1`, dates became dates, `!!binary` became bytes, `critical: true` passed as an int | 2A, 3B | **CONFIRMED** (reproduced) | tag allowlist (str/int/bool/null/seq/map), exact `type()` checks, counts ≥ 0, quoted version |
| 5 | A 40-line strict loader (pure-Python `SafeLoader` subclass) refuses all of the above and still loads a normal manifest; each guard has its own canary | verifier | **CONFIRMED** (prototype + one canary per guard) | `app/strict_yaml.py` |
| 6 | `https://evil.com\@bitbucket.example.com/x`: Python reads host `bitbucket.example.com`, a WHATWG client (Node) connects to `evil.com` | 2A | **CONFIRMED** (both parsers run) | the source URL's authority may not contain `@`, `\`, `%5c` or a port (R7) |
| 7 | "Scope is `*` or ends in `*`" let `*:read`, `jira:project/*/issues` and `*.atlassian.net` through; host matching was undefined (`"x.com" in "api.x.com"` is `True`) | 2A, 3B | **CONFIRMED** | positive grammars for resources and hosts, `*` anywhere rejected, forbidden scopes, exact membership (R3) |
| 8 | Only the secret rule promised not to echo the secret; other rules' messages and the raw JSON could | 2A, 3B | **CONFIRMED** | one redaction step over every output; keys scanned too (R2, P2) |
| 9 | The evaluation pack (our own asset) had no `kind`, so it would fail the schema or pass as something it is not | 2B | **SUSPECTED** as "SB1-01 cannot pass", **CONFIRMED** as a gap | `kind: eval-pack`, which calls no model and has no outward or physical tool (R4, R5) |
| 10 | `apiVersion` was in the header but not a declared field | 1A | **CONFIRMED** | required, versions listed (R1) |
| 11 | An unparseable manifest was "rejected" in the spec and "exit 2" in the design | 3B, 2A | **CONFIRMED** | syntax error, size, encoding = exit 2 (unreadable); refused constructs = R1 reject (unsafe) |
| 12 | The policy had no schema, so a typo could fail open | 1A, 3B | accepted | the policy is validated; invalid = exit 2 (P4) |
| 13 | The coverage test was green with no samples and no code; no test ran every case; `rules` meant "contains", so flagging everything would pass | 3B, verifier | **CONFIRMED** (ran the test) | SB1-17: every case id executed; `rules` is now the exact set; paths asserted |
| 14 | Cases that could not fail: an accepted manifest with a control character in the name prints nothing to escape; only one secret row checked the output | verifier | **CONFIRMED** | the escape row is now a reject whose finding carries the character; every secret row checks terminal and JSON |
| 15 | Tools listed by an MCP server can change after approval (rug pull); a server could list no tools at all | 2A | accepted | agents and MCP servers list their tools with a definition digest (R5); runtime enforcement is in the design doc |
| 16 | The result did not say which policy and validator decided it | 1A | accepted | digests of manifest, policy and validator version in the result (P3) |
| 17 | "Approved" says nothing about risk | 2B | accepted | the validator computes a risk tier (1-3) from existing fields; the sign-off it requires is in the design doc |
| 18 | Hints: findings phrased as fixes keep the gate non-threatening | 2B | accepted | every finding has a hint (P1) |

## Trade-offs decided between pairs

- **Simplify vs scale.** Ten domain rules became seven rules and four validator properties, a list a talk can
  carry. Waivers, policy versions with grace periods, dependencies between assets and revocation are kept, but
  in the design doc's operating section, not in a stateless validator.
- **Security vs usefulness.** The validator keeps format and consistency checks; trust that needs evidence
  (signed scans in Artifactory, publisher identity, tool lists reconciled against the running server,
  composition at install) is a named control in the design doc, each with where it runs.
- **Rebuild vs defend.** No 2026 standard (MCP `server.json`, SKILL.md, A2A agent cards) carries sensitivity,
  egress, permissions or effects, so the governance manifest stays; it borrows the SKILL.md name rule now, and
  the design doc presents compatibility (descriptor cross-checks, an MCP-Registry-compatible internal API, JSON
  Schema export, gitleaks in Jenkins, OPA when Security owns the rules) as the target.

## What the review cost

Six reviewers and two verifiers, about 2.3 M subagent tokens in total (aggregate counts, no input/output
split, so no dollar figure is claimed).
