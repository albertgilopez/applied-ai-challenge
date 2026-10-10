"""Mutation canaries: break one property at a time and require the suite to go red.

A green test only counts once it has been seen failing. Each mutation is checked
to have actually changed the file before the suite runs, and the file is restored
afterwards. Exit code = number of mutations the suite failed to catch.

Everything happens on a temporary copy of the tracked files; the checkout is never
written. Run it from the repo root after `uv sync` (it uses the project's .venv).

Mutate what a test guards (the code, the data), never the test itself: a loosened
test over a clean tree stays green, which proves nothing.
"""

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

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
    ("harness/prompts.py", "if not ok and env.strip().lower() not in RELAXED_ENVS:", "if False:"),  # H3
    ("harness/loop.py", 'env: str = "prod",', 'env: str = "dev",'),  # H3 default
    ("harness/catalog.py", 'if t.effect in ("read", "write") and t.path_args is None:', "if False:"),  # H1
    ("harness/storage.py", "if number == len(lines):", "if True:"),  # H6 only the LAST line may be partial
    (
        "harness/storage.py",
        "            if number == len(lines):\n                return",
        "            if False:\n                return",
    ),  # H6
    ("harness/prompts.py", "if not by.strip() or not validation_ref.strip():", "if False:"),
    ("harness/loop.py", "if seen[key] >= REPEAT_LIMIT:", "if False:"),
    ("harness/replay.py", "if key not in self.data:", "if False:"),
    # Pricing: every way the table could under-price a call must stay None (S2-07, STORY-004 DR-3).
    (
        "harness/usage.py",
        "if price is None:\n        return None\n    return _priced",
        "if price is None:\n        return 0.0\n    return _priced",
    ),
    ("harness/usage.py", 'raw.get("inference_geo") != PRICED_REGION', "False"),
    ("harness/usage.py", "u.total_input_tokens > price.max_prompt_tokens", "False"),
    ("harness/usage.py", "if u.cache_creation_input_tokens != u.cache_write_5m + u.cache_write_1h:", "if False:"),
    ("harness/loop.py", "cost = None if not costs or any(c is None for c in costs) else", "cost = 0.0 if False else"),
    ("harness/loop.py", 'request["output_config"] = self.output_config', "pass"),
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
    ("core/sbom.py", 'if product is not None and p.get("SPDXID") == product:', "if False:"),
    ("core/sbom.py", "if len(described) != 1:", "if not described:"),
    (
        "core/sbom.py",
        "if (kind in _INBOUND and dst == product) or (kind in _OUTBOUND and src == product):",
        "if False:",
    ),
    ("core/sbom.py", "for entry in concluded or entries:", "for entry in entries:"),  # DR-5 concluded
    ("core/sbom.py", 'url = url[4:] if url.startswith("git+") else url', "url = url"),  # DR-7 git+ prefix
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
    # STORY-003: one mutation per domain rule.
    (
        "core/review.py",
        '"license_expression": component.license_expression,',
        '"license_expression": None,',
    ),  # DR-4 / C12: the license is part of the key
    (
        "core/review.py",
        '"policy_sha256": policy_sha256,\n        },',
        '"policy_sha256": "",\n        },',
    ),  # DR-5: a policy change reopens the item
    ("core/sbom.py", 'if url.lower().startswith("https://"):', "if True:"),  # DR-6 / C5
    ("core/report.py", "if unicodedata.category(ch) in _UNSAFE_CATEGORIES else ch", "if False else ch"),  # DR-7 / C4
    ("core/report.py", "if ch in _MARKDOWN else ch for ch in out", "if False else ch for ch in out"),  # DR-7 / C4
    ("core/report.py", 'return out.replace("://", "[:]//").replace("www.", "www[.]")', "return out"),  # DR-7
    ("core/report.py", 'return "<" + quote(url, safe=_URL_SAFE) + ">"', 'return "<" + url + ">"'),  # DR-7
    ("core/review.py", "if value is None or not value.strip():", "if value is None:"),  # DR-2
    ("core/review.py", "if decision_id not in states:", "if False:"),  # DR-1
    (
        "core/review.py",
        "return self.reviews[-1].verdict if self.reviews",
        "return self.reviews[0].verdict if self.reviews",
    ),  # DR-3 latest wins
    ("review/cli.py", "if key in known:", "if False:"),  # DR-9 a re-run never decides again
    (
        "core/sbom.py",
        'named = Product(str(product["name"]), version if isinstance(version, str) else None)',
        "named = None",
    ),  # DR-8 the product is named
]
# Every anchor is checked before anything is mutated: a reformat that splits a
# line should report all the stale anchors at once, not stop at the first.
missing = [(f, a) for f, a, _ in muts if a not in pathlib.Path(f).read_bytes().decode("utf-8")]
if missing:
    for f, a in missing:
        print(f"ANCHOR MISSING {f}: {a[:70]}")
    sys.exit(2)

# Mutations run on a temporary COPY of the tracked files, never on the checkout. Mutating the
# real tree left the security gate rewritten on disk for the duration of each run: a hard kill,
# a parallel session or a `git add` in that window could keep it (security scan H9).
REPO = pathlib.Path.cwd()
VENV_PY = REPO / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
TIMEOUT_S = 120

work = pathlib.Path(tempfile.mkdtemp(prefix="canaries-"))
# Tracked files AND new files not yet added (but not ignored ones): copying only what git tracks
# would leave a new module out of the copy, every run would fail on an ImportError, and every
# mutation would read as KILLED for the wrong reason.
tracked = subprocess.run(
    ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
    capture_output=True,
    text=True,
    check=True,
).stdout.split("\0")
for rel in filter(None, tracked):
    dest = work / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REPO / rel, dest)


def _suite(cwd: pathlib.Path) -> int:
    # No bytecode cache (-B). Python reuses a .pyc when the source has the same size and the same
    # mtime in whole seconds. A mutation that swaps two expressions of equal length, written in the
    # same second as the previous restore, then ran the OLD code: on Linux, where the suite takes
    # half a second, that canary read SURVIVED while the guard was fine. The opposite case is worse:
    # a restore that does not take effect leaves a mutation live and the next canary reads KILLED.
    r = subprocess.run(
        [str(VENV_PY), "-B", "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=TIMEOUT_S,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    return r.returncode


# Baseline: the UNMUTATED copy must pass. If it does not (a file missing from the copy, a broken
# environment), every mutation would read as KILLED and the run would prove nothing.
if _suite(work) != 0:
    shutil.rmtree(work, ignore_errors=True)
    print("BASELINE RED: the unmutated copy fails its own suite; no mutation result would mean anything")
    sys.exit(3)

bad = 0
try:
    for f, a, b in muts:
        # Bytes in, bytes out: text mode on Windows would rewrite line endings on restore.
        p = work / f
        raw = p.read_bytes()
        orig = raw.decode("utf-8")
        assert a in orig, f"mutation anchor missing: {a[:50]}"
        try:
            p.write_bytes(orig.replace(a, b, 1).encode("utf-8"))
            assert p.read_bytes() != raw
            status = "KILLED" if _suite(work) != 0 else "SURVIVED"
        except subprocess.TimeoutExpired:
            status = "KILLED"  # a mutation that makes the suite hang has not passed it
        finally:
            p.write_bytes(raw)
        assert p.read_bytes() == raw, f"{f} was not restored byte for byte"
        bad += status == "SURVIVED"
        print(f"{status:9} {f}: {a[:60]}")
finally:
    shutil.rmtree(work, ignore_errors=True)
print("survivors:", bad)
sys.exit(bad)
