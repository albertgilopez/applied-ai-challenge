# Bug report: one component crashes the whole license review

The working directory holds `core/`, a small Python package that reads a component's license
expression (SPDX syntax: `MIT OR Apache-2.0`, `(MIT AND BSD-3-Clause)`, ...) and decides a verdict
against a policy: `Allow`, `Needs review` or `Reject`. `core.decide.decide(component, policy)` is the
entry point.

A user scanned an SBOM in which one component's license field was a single license wrapped in a few
hundred pairs of parentheses, like `((((...MIT...))))`. Instead of a verdict for that component, the
review of the whole SBOM stopped with a `RecursionError`.

What we expect after the fix:

- That component gets `Needs review`, and its reason says the expression is **nested too deeply**.
- Expressions that real SBOMs contain (they nest two or three levels) are decided exactly as before.
  Anything nested up to 64 levels must still be decided normally.
- Every other behaviour stays the same: `OR` takes the best branch, `AND` the worst, and an expression
  that does not parse is `Needs review`.

You may change `core/license_expr.py` and `core/decide.py`. Changes to other files are not kept.
