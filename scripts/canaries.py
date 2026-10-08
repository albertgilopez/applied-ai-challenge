"""Mutation canaries: break one property at a time and require the suite to go red.

A green test only counts once it has been seen failing. Each mutation is checked
to have actually changed the file before the suite runs, and the file is restored
afterwards. Exit code = number of mutations the suite failed to catch.

Mutate what a test guards (the code, the data), never the test itself: a loosened
test over a clean tree stays green, which proves nothing.
"""

import pathlib
import subprocess
import sys

muts = [
    (
        "harness/gate.py",
        'return Decision("escalate", "outward effect needs a human")',
        'return Decision("allow", "outward effect needs a human")',
    ),
    (
        "harness/gate.py",
        'return Decision("deny", "tool is not in the catalog")',
        'return Decision("allow", "tool is not in the catalog")',
    ),
    (
        "harness/gate.py",
        "if not isinstance(value, str) or not self._inside(value, roots):",
        "if not isinstance(value, str):",
    ),
    (
        "harness/gate.py",
        'return self._check_paths(t, args, self.read_roots, "read") or Decision("allow", "read-only tool")',
        'return Decision("allow", "read-only tool")',
    ),
    (
        "harness/gate.py",
        'return Decision("deny", f"unknown effect {t.effect!r}")',
        'return Decision("escalate", f"unknown effect {t.effect!r}")',
    ),
    ("harness/prompts.py", r'text.replace("\r\n", "\n").encode("utf-8")', 'text.encode("utf-8")'),
    ("harness/prompts.py", 'if not ok and env == "prod":', "if False:"),
    ("harness/prompts.py", "if not by.strip() or not validation_ref.strip():", "if False:"),
    ("harness/loop.py", "if seen[key] >= REPEAT_LIMIT:", "if False:"),
    ("harness/replay.py", "if key not in self.data:", "if False:"),
    ("harness/usage.py", "return None\n    per_in", "return 0.0\n    per_in"),
    # Boundary and story coverage: mutate what the test guards, not the test.
    ("core/__init__.py", 'tests/test_boundary.py).\n"""\n', 'tests/test_boundary.py).\n"""\nimport anthropic\n'),
    (
        "stories/STORY-003.md",
        "the original decision stays (case: S3-01)\n",
        "the original decision stays (case: S3-01)\n- [ ] A promise no case checks\n",
    ),
    (
        "harness/loop.py",
        "intent = self.ledger.append(\n",
        "intent = None and (\n",
    ),
    # STORY-001: one mutation per domain rule.
    ("core/license_expr.py", 'while self.peek() == "AND":', 'while self.peek() in ("AND", "OR"):'),  # DR-2 precedence
    (
        "core/decide.py",
        "return max(results, key=lambda r: RANK[r[0]])",
        "return min(results, key=lambda r: RANK[r[0]])",
    ),  # DR-3 OR
    (
        "core/decide.py",
        "return min(results, key=lambda r: RANK[r[0]])",
        "return max(results, key=lambda r: RANK[r[0]])",
    ),  # DR-3 AND
    (
        "core/decide.py",
        'verdict, reason = REVIEW, "no license declared"',
        'verdict, reason = ALLOW, "no license declared"',
    ),  # DR-1
    (
        "core/decide.py",
        'return REVIEW, f"{leaf.text} not in policy"',
        'return ALLOW, f"{leaf.text} not in policy"',
    ),  # DR-1
    ("core/decide.py", "verdict = policy.lookup(leaf.text)", "verdict = policy.lookup(leaf.id)"),  # DR-4 no inference
    ("core/policy.py", "if k in where and where[k] != section:", "if False:"),  # DR-8
    # DR-5 / scan C1: reintroduce text concatenation, and skip an entry that does not parse.
    ("core/sbom.py", "return to_text(And(tuple(trees)))", 'return " AND ".join(f"({t})" for t in terms)'),
    ("core/sbom.py", "return term  # does not parse on its own", "continue  # does not parse on its own"),
    (
        "core/license_expr.py",
        'return " AND ".join(f"({to_text(i)})" if isinstance(i, Or) else to_text(i) for i in node.items)',
        'return " AND ".join(to_text(i) for i in node.items)',
    ),
    # DR-5: concluded before declared; scan C2: a concluded NONE does not fall back.
    (
        "core/sbom.py",
        'return _spdx_value(concluded) or _spdx_value(p.get("licenseDeclared"))',
        'return _spdx_value(p.get("licenseDeclared")) or _spdx_value(concluded)',
    ),
    ("core/sbom.py", 'if isinstance(concluded, str) and concluded.strip().upper() == "NONE":', "if False:"),
    # DR-9 / scan C3: the product leaves the list only if unique and nothing depends on it.
    ("core/sbom.py", '(product is not None and p.get("SPDXID") == product)', "False"),
    ("core/sbom.py", "if len(described) != 1:", "if not described:"),
    (
        "core/sbom.py",
        "if (kind in _INBOUND and dst == product) or (kind in _OUTBOUND and src == product):",
        "if False:",
    ),
    ("core/sbom.py", "for entry in concluded or entries:", "for entry in entries:"),  # DR-5 concluded
    ("core/sbom.py", 'return url[4:] if url.startswith("git+") else url', "return url"),  # DR-7 git+ prefix
    (
        "core/sbom.py",
        '("vcs", "source-distribution", "distribution", "website")',
        '("vcs", "distribution", "source-distribution", "website")',
    ),  # DR-7
    ("app/files.py", "if size > limit:", "if False:"),
    # Review findings C6-C9, C11, C16-C18: one mutation per fix, each reintroduces the bug.
    ("core/policy.py", "if not text.isascii():\n        return None", "if False:\n        return None"),  # C9
    ("core/policy.py", "if not isinstance(entries, list):", "if False:"),  # C8
    ("core/policy.py", "{type(entry).__name__} is not a license id", "{entry!r} is not a license id"),  # C6
    ("core/license_expr.py", "if self.depth > MAX_DEPTH:", "if False:"),  # C7
    ("core/sbom.py", 'if "bomFormat" in doc and "spdxVersion" in doc:', "if False:"),  # C18
    ("core/sbom.py", 'if isinstance(product, dict) and "components" in product:', "if False:"),  # C17
    ("app/files.py", "doc = json.loads(text, object_pairs_hook=_no_duplicate_keys)", "doc = json.loads(text)"),  # C11
    ("app/files.py", 'raise PolicyError(f"{Path(path).name} is nested too deeply") from exc', "raise"),  # C16
    ("core/purl.py", 'parts = [unquote(p) for p in body.split("/") if p]', 'parts = [p for p in body.split("/") if p]'),
]
# Every anchor is checked before anything is mutated: a reformat that splits a
# line should report all the stale anchors at once, not stop at the first.
missing = [(f, a) for f, a, _ in muts if a not in pathlib.Path(f).read_bytes().decode("utf-8")]
if missing:
    for f, a in missing:
        print(f"ANCHOR MISSING {f}: {a[:70]}")
    sys.exit(2)

bad = 0
for f, a, b in muts:
    # Bytes in, bytes out: text mode on Windows would rewrite line endings on restore.
    p = pathlib.Path(f)
    raw = p.read_bytes()
    orig = raw.decode("utf-8")
    assert a in orig, f"mutation anchor missing: {a[:50]}"
    try:
        p.write_bytes(orig.replace(a, b, 1).encode("utf-8"))
        assert p.read_bytes() != raw
        r = subprocess.run(["uv", "run", "pytest", "-q", "-x"], capture_output=True, text=True)
    finally:  # a Ctrl-C or a crash must never leave a mutated file in the tree
        p.write_bytes(raw)
    assert p.read_bytes() == raw, f"{f} was not restored byte for byte"
    status = "KILLED" if r.returncode != 0 else "SURVIVED"
    bad += status == "SURVIVED"
    print(f"{status:9} {f}: {a[:60]}")
print("survivors:", bad)
sys.exit(bad)
