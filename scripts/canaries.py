"""Mutation canaries: break one property at a time and require the suite to go red.

A green test only counts once it has been seen failing. Each mutation is checked
to have actually changed the file before the suite runs, and the file is restored
afterwards. Exit code = number of mutations the suite failed to catch.

Mutate what a test guards (the code, the data), never the test itself: a loosened
test over a clean tree stays green, which proves nothing.
"""
import subprocess, sys, pathlib
muts = [
 ("harness/gate.py", 'return Decision("escalate", "outward effect needs a human")', 'return Decision("allow", "outward effect needs a human")'),
 ("harness/gate.py", 'return Decision("deny", "tool is not in the catalog")', 'return Decision("allow", "tool is not in the catalog")'),
 ("harness/gate.py", 'if not isinstance(value, str) or not self._inside_roots(value):', 'if not isinstance(value, str):'),
 ("harness/prompts.py", 'if not ok and env == "prod":', 'if False:'),
 ("harness/prompts.py", 'if not by.strip() or not validation_ref.strip():', 'if False:'),
 ("harness/loop.py", 'if seen[key] >= REPEAT_LIMIT:', 'if False:'),
 ("harness/replay.py", 'if key not in self.data:', 'if False:'),
 ("harness/usage.py", 'return None\n    per_in', 'return 0.0\n    per_in'),
 # Boundary and story coverage: mutate what the test guards, not the test.
 ("core/__init__.py", 'tests/test_boundary.py).\n"""\n', 'tests/test_boundary.py).\n"""\nimport anthropic\n'),
 ("stories/STORY-003.md", "the original decision stays (case: S3-01)\n", "the original decision stays (case: S3-01)\n- [ ] A promise no case checks\n"),
 ("harness/loop.py", 'self.ledger.append({"kind": "tool", **record, "output": output[:2000]})', 'pass'),
 # STORY-001: one mutation per domain rule.
 ("core/license_expr.py", 'while self.peek() == "AND":', 'while self.peek() in ("AND", "OR"):'),  # DR-2 precedence
 ("core/decide.py", "return max(results, key=lambda r: RANK[r[0]])", "return min(results, key=lambda r: RANK[r[0]])"),  # DR-3 OR
 ("core/decide.py", "return min(results, key=lambda r: RANK[r[0]])", "return max(results, key=lambda r: RANK[r[0]])"),  # DR-3 AND
 ("core/decide.py", 'verdict, reason = REVIEW, "no license declared"', 'verdict, reason = ALLOW, "no license declared"'),  # DR-1
 ("core/decide.py", 'return REVIEW, f"{leaf.text} not in policy"', 'return ALLOW, f"{leaf.text} not in policy"'),  # DR-1
 ("core/decide.py", "verdict = policy.lookup(leaf.text)", "verdict = policy.lookup(leaf.id)"),  # DR-4 no inference
 ("core/policy.py", "if k in where and where[k] != section:", "if False:"),  # DR-8
 ("core/sbom.py", '" AND ".join(f"({t})" for t in terms)', '" OR ".join(f"({t})" for t in terms)'),  # DR-5
 ("core/sbom.py", 'license_expression=_spdx_value(p.get("licenseConcluded")) or _spdx_value(p.get("licenseDeclared")),',
  'license_expression=_spdx_value(p.get("licenseDeclared")) or _spdx_value(p.get("licenseConcluded")),'),  # DR-5
 ("core/sbom.py", 'if not isinstance(p, dict) or p.get("SPDXID") in described:', "if not isinstance(p, dict):"),
 ("app/files.py", "if size > limit:", "if False:"),
 ("core/purl.py", 'parts = [unquote(p) for p in body.split("/") if p]', 'parts = [p for p in body.split("/") if p]'),
]
bad = 0
for f, a, b in muts:
    # Bytes in, bytes out: text mode on Windows would rewrite line endings on restore.
    p = pathlib.Path(f); raw = p.read_bytes(); orig = raw.decode("utf-8")
    assert a in orig, f"mutation anchor missing: {a[:50]}"
    p.write_bytes(orig.replace(a, b, 1).encode("utf-8"))
    assert p.read_bytes() != raw
    r = subprocess.run(["uv", "run", "pytest", "-q", "-x"], capture_output=True, text=True)
    p.write_bytes(raw)
    assert p.read_bytes() == raw, f"{f} was not restored byte for byte"
    status = "KILLED" if r.returncode != 0 else "SURVIVED"
    bad += status == "SURVIVED"
    print(f"{status:9} {f}: {a[:60]}")
print("survivors:", bad); sys.exit(bad)
