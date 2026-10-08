# STORY-003 — Reviewer approve/override, an audit log, and an exported report

**As** a Legal reviewer
**I want** to approve or override any decision, with every step logged
**so that** the CRA file shows who decided what, when and why.

## Scope

- `review` command: list pending items, approve one, or override it with a new verdict.
- Every decision and every override is a ledger line (DOCTRINE D-06). An override points at the
  decision it replaces and needs a reviewer name and a reason.
- `report` command: a short Markdown summary Legal can attach (counts, per-component verdict,
  reason, source link, overrides), plus the same data as JSON.
- A re-run reads the recorded verdicts instead of deciding again, so the report is stable.

## Acceptance Criteria

- [ ] An override is a new ledger line; the original decision stays (case: S3-01)
- [ ] An override without a reviewer or a reason is refused (case: S3-02)
- [ ] The report shows the final verdict after overrides and lists each override (case: S3-03)
- [ ] The report has counts per verdict and a source link per component (case: S3-04)
- [ ] Running the review twice on the same SBOM reuses the recorded verdicts (case: S3-05)
