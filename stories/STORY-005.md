# STORY-005 — Reject any component with a critical vulnerability (OSV)

**As** Legal and the release manager
**I want** every component checked against OSV, and any component with a critical CVE rejected
**so that** nothing with a known critical vulnerability ships, whatever its license says.

## Scope

- A pure rule in `core/` combines the license decision with the component's OSV vulnerabilities.
- A critical vulnerability makes the verdict `Reject`, and the reason names the vulnerability id.
- Non-critical vulnerabilities do not change the verdict; their ids go into the reason.
- Fail closed (DOCTRINE D-02): a component that could not be checked, or a vulnerability whose severity
  is unknown, is never `Allow`; it is `Needs review`.
- Out of scope here: the network adapter that queries `api.osv.dev` (next step, recorded and replayed in
  CI like the model calls), and the vulnerability data in `decision_key` (D-08, same commit as the adapter).

## Acceptance Criteria

- [x] An allowed component with no vulnerabilities stays `Allow` (case: S5-01)
- [x] A critical vulnerability rejects the component and names the id (case: S5-02)
- [x] A non-critical vulnerability keeps the verdict and is named in the reason (case: S5-03)
- [x] A component that could not be checked against OSV is `Needs review`, never `Allow` (case: S5-04)
- [x] A critical vulnerability rejects even a component already under review (case: S5-05)
- [x] A vulnerability with unknown severity is `Needs review`, never `Allow` (case: S5-06)
