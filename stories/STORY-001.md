# STORY-001 — Parse the SBOM and classify each component's license against the policy

**As** a Legal reviewer preparing CRA documentation
**I want** every component of an SBOM classified against our license policy
**so that** I only look at the components that need a human.

## Scope

- Input: an SBOM in CycloneDX JSON or SPDX JSON. Both formats produce the same component list.
- Policy: a file listing which SPDX license ids are `allowed`, `review` or `rejected`.
- Output per component: `Allow`, `Needs review` or `Reject`, with the reason and a link to the
  component's source.
- License expressions: `A OR B` takes the best option the policy allows; `A AND B` takes the
  strictest.

## Acceptance Criteria

- [ ] A component under an allowed license is `Allow` (case: S1-01)
- [ ] A component under a rejected license is `Reject` (case: S1-02)
- [ ] A component under a review license is `Needs review` (case: S1-03)
- [ ] A component with no declared license is `Needs review`, never `Allow` (case: S1-04)
- [ ] A license id the policy does not list is `Needs review` (case: S1-05)
- [ ] `OR` takes the best allowed option (case: S1-06)
- [ ] `AND` takes the strictest option (case: S1-07)
- [ ] An expression that cannot be parsed is `Needs review` (case: S1-08)
- [ ] The CycloneDX and SPDX samples yield the same components, at least 10, at least 2 AI models (case: S1-09)
- [ ] Every decision carries a source link, or says that none was declared (case: S1-10)

## Out of scope

AI model cards (STORY-002), human review and the report (STORY-003).
