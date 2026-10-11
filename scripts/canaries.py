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
import time

muts = [
    (
        "harness/gate.py",
        'return Decision("escalate", f"{t.effect} effect needs a human")',
        'return Decision("allow", f"{t.effect} effect needs a human")',
    ),
    ("harness/gate.py", 'if t.effect in ("outward", "physical"):', 'if t.effect == "outward":'),
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
        '"policy_sha256": policy_sha256,\n    }\n    if card_key',
        '"policy_sha256": "",\n    }\n    if card_key',
    ),  # DR-5: a policy change reopens the item
    ("core/review.py", 'fields["card_key"] = card_key', "pass"),  # STORY-002 DR-5: the card is part of the key
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
    # STORY-002: one mutation per domain rule.
    ("core/model_card.py", 'and normalise(license_id) in normalise(quote or "")', "and True"),  # DR-1 names the id
    ("core/model_card.py", "if _grounded_restriction(r, card))", "if True)"),  # DR-2
    (
        "core/model_card.py",
        "verdict = min((sbom.verdict, card_verdict), key=lambda v: RANK[v])",
        "verdict = card_verdict",
    ),
    ("core/model_card.py", '{"card_sha256": _sha256(card), "prompt_sha256"', '{"card_sha256": "", "prompt_sha256"'),
    (
        "core/model_card.py",
        'REVIEW, "the model\'s answer could not be read"',
        '"Allow", "the model\'s answer could not be read"',
    ),
    ("agent/model_cards.py", '_PART = r"[A-Za-z0-9][A-Za-z0-9._-]', '_PART = r"[A-Za-z0-9.][A-Za-z0-9._-]'),  # D-04
    (
        "core/report.py",
        "decision_key(c, policy_sha256, (card_keys or {}).get(c.identity))",
        "decision_key(c, policy_sha256)",
    ),
    # STORY-B01: each loader guard, each rule, the exact types, redaction, the tier, the policy check.
    ("app/strict_yaml.py", "if self.check_event(AliasEvent):", "if False:"),
    ("app/strict_yaml.py", "if node.tag not in ALLOWED_TAGS:", "if False:"),
    ("app/strict_yaml.py", 'if not (isinstance(key_node, ScalarNode) and key_node.tag == _Y + "str"):', "if False:"),
    ("app/strict_yaml.py", "if key in seen:", "if False:"),
    ("core/manifest.py", "return type(value) is bool", "return isinstance(value, (bool, str))"),
    ("core/manifest.py", "return type(value) is int and value >= 0", "return isinstance(value, int)"),
    ("core/manifest.py", "if pattern.search(text):", "if False:"),
    ("core/manifest.py", 'text = text.replace(secret, "[redacted]")', "pass"),
    ("core/manifest.py", 'if not ok or ".." in ref:', "if False:"),
    ("core/manifest.py", 'RESOURCE = re.compile(r"[a-z][a-z0-9-]*:', 'RESOURCE = re.compile(r"[a-z*][a-z0-9*-]*:'),
    (
        "core/manifest.py",
        "if any(part.lower() in policy.forbidden_scopes",
        "if False and any(part.lower() in policy.forbidden_scopes",
    ),
    ("core/manifest.py", 'return not all(label.isdigit() for label in host.split("."))', "return True"),
    ("core/manifest.py", "if isinstance(provider, str) and provider not in policy.providers[level]:", "if False:"),
    ("core/manifest.py", "if host not in policy.egress[level]:", "if False:"),
    ("core/manifest.py", "if api_provider is not None and api_provider != provider:", "if False:"),
    ("core/manifest.py", 'if doc.get("kind") == "eval-pack" and "model" in doc:', "if False:"),
    (
        "core/manifest.py",
        'elif tool.get("requires_human_approval") is not True',
        "elif False and tool.get('x') is not True",
    ),
    ("core/manifest.py", "    if not tools:\n", "    if False:\n"),
    # D1 of the MCP/CLI design review: relabelling an asset must not let it escape the tool rule or its tier.
    ("core/manifest.py", "    if not tools:\n", '    if kind in ("agent", "mcp-server") and not tools:\n'),
    ("core/manifest.py", 'and p["resource"].split(":", 1)[0] in policy.physical_systems', "and False"),
    ("core/manifest.py", "        if not physical_tool:\n", "        if False:\n"),
    (
        "core/manifest.py",
        'if level == "restricted" or reaches or _physical_writes(doc, policy):',
        'if level == "restricted" or reaches:',
    ),
    ("core/manifest.py", "if isinstance(digest, str) and not DIGEST.fullmatch(digest):", "if False:"),
    ("core/manifest.py", "if isinstance(covered, str) and covered != digest:", "if False:"),
    ("core/manifest.py", 'if scan.get("status") == "failed":', "if False:"),
    ("core/manifest.py", "if type(count) is int and count > limit:", "if False:"),
    ("core/manifest.py", "if len(parts) != 2 or not parts[0] or parts[1] not in policy.contact_domains:", "if False:"),
    ("core/manifest.py", "if not ok or authority not in policy.source_hosts:", "if False:"),
    ("core/manifest.py", "if type(value) is not list or not all(type(v) is str for v in value):", "if False:"),
    ("core/manifest.py", "        return 3\n", "        return 2\n"),
    # STORY-004 T1: workspace-relative paths, measured latency, retries recorded as calls.
    (
        "harness/gate.py",
        'if rel.is_absolute() or PureWindowsPath(raw).drive or ".." in rel.parts:',
        "if rel.is_absolute() or PureWindowsPath(raw).drive:",
    ),
    ("harness/gate.py", "if rel.is_absolute() or PureWindowsPath(raw).drive", "if PureWindowsPath(raw).drive"),
    ("harness/gate.py", 'rel = PurePosixPath(raw.replace("\\\\", "/"))', "rel = PurePosixPath(raw)"),
    (
        "harness/loop.py",
        "latency = sum(measured) if model_calls and len(measured) == len(model_calls) else wall",
        "latency = wall",
    ),
    ("harness/loop.py", 'for failed in measured.get("failed_tries") or []:', "for failed in []:"),
    ("harness/loop.py", 'request["cache_control"] = {"type": "ephemeral"}', "pass"),
    ("harness/providers.py", "return status in RETRYABLE_STATUS", "return True"),
    # STORY-004 T4: each grader guard on its own layer.
    (
        "keysbench/graders.py",
        "    for rel in spec.editable:\n",
        "    for rel in [p.name for p in workspace.iterdir()]:\n",
    ),
    ("keysbench/graders.py", '"--noconftest", "-p", "no:cacheprovider",', '"-p", "no:cacheprovider",'),
    ("keysbench/graders.py", 'sys.executable, "-I", "-B", "-m", "pytest",', 'sys.executable, "-B", "-m", "pytest",'),
    (
        "keysbench/graders.py",
        'return GradeResult(False, ("no_report",), f"exit {proc.returncode} and no test report")',
        'return GradeResult(True, (), "")',
    ),
    ("keysbench/graders.py", '("failure", "error", "skipped")', '("failure", "error")'),
    (
        "keysbench/graders.py",
        "env = {k: v for k, v in os.environ.items() if k.upper() in _KEEP}",
        "env = dict(os.environ)",
    ),
    ("keysbench/kbcall.py", "    if type(actual) is not type(expected):\n", "    if False:\n"),
    # STORY-004 T2: the scorer (the cell key, what counts as an attempt, saturation, intervals, sizing).
    (
        "core/bench_score.py",
        'return (row["task_id"], row["task_sha256"], row["config"], contestant["model"], contestant["effort"])',
        'return (row["task_id"], "", row["config"], contestant["model"], contestant["effort"])',
    ),
    (
        "core/bench_score.py",
        'NOT_ATTEMPTS = frozenset({"budget_stopped", "error"})',
        'NOT_ATTEMPTS = frozenset({"error"})',
    ),
    (
        "core/bench_score.py",
        '        if c["attempts"] > 0:\n            rates.setdefault',
        '        if c["attempts"] > 0 and not c["saturated"]:\n            rates.setdefault',
    ),
    ("core/bench_score.py", "6: 2.4469,", "6: 1.96,"),
    ("core/bench_score.py", "return {task for task, who in perfect.items() if who == everyone}", "return set(perfect)"),
    (
        "core/bench_score.py",
        "rank = max(1, math.ceil(q * len(ordered)))",
        "rank = max(1, round(q * (len(ordered) - 1)) + 1)",
    ),
    ("core/bench_score.py", "POWER = 0.8\n", "POWER = 0.9\n"),
    (
        "core/bench_score.py",
        "return math.fsum(float(c) for c in costs if c is not None)",
        "return sum(float(c) for c in costs if c is not None)",
    ),
    # STORY-004 T3: the KX-100 traps the tasks rely on.
    (
        "keysbench/instrument/sim.py",
        "            if not self._fresh:\n                self.stale_fetches += 1\n",
        "            self._measure()\n",
    ),
    ("keysbench/instrument/sim.py", "NOISE_REL_N1 / math.sqrt(self._aver) * z", "NOISE_REL_N1 * z"),
    ("keysbench/instrument/sim.py", "ratio = cal_factor_pct(self.signal_hz) / cal_factor_pct(freq_hz)", "ratio = 1.0"),
    (
        "keysbench/instrument/sim.py",
        "        if not FREQ_MIN_HZ <= value <= FREQ_MAX_HZ:\n            raise _CommandError(-222)\n",
        "",
    ),
    ("keysbench/instrument/sim.py", "self._errors.pop(0) if self._errors", "self._errors.pop() if self._errors"),
    ("keysbench/instrument/sim.py", "        self._buffer = RESET_READING_DBM\n", ""),
    # STORY-004 T8: the runner (rounds, resume, budget, named outcomes, one recording per attempt).
    (
        "keysbench/runner.py",
        "by_price = sorted(plan.models, key=lambda m: (PRICES[m].output, m))",
        "by_price = list(plan.models)",
    ),
    (
        "keysbench/runner.py",
        'if r.get("kind") == "attempt" and r.get("outcome") != "budget_stopped"',
        'if r.get("kind") == "attempt" and False',
    ),
    ("keysbench/runner.py", "if self.budget.spent_usd + worst > self.budget.cap_usd:", "if False:"),
    ("keysbench/runner.py", "if projected is not None and budget.spent_usd + projected > cap:", "if False:"),
    ("keysbench/runner.py", 'row["cost_usd"] = round(provider.attempt_spent, 6)', 'row["cost_usd"] = 0.0'),
    ("keysbench/runner.py", 'if run.stop_reason == "refusal":', "if False:"),
    ("keysbench/runner.py", 'elif run.stop_reason == "max_tokens":', "elif False:"),
    (
        "keysbench/runner.py",
        'return root / key.task_id / key.task_sha256[:12] / f"{key.slug()}.jsonl"',
        'return root / key.task_id / key.task_sha256[:12] / "attempt.jsonl"',
    ),
    ("keysbench/runner.py", "    if unpriced:\n", "    if False:\n"),
    # STORY-004 T9: configurations A and A0 (the audit, the key scrub, safe restore).
    (
        "keysbench/arm_a.py",
        "if isinstance(value, str) and value and not _inside(value, workspace):",
        "if False:",
    ),
    ("keysbench/arm_a.py", "                if not _inside(p, workspace):\n", "                if False:\n"),
    ("keysbench/arm_a.py", 'env["CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"] = "1"', "pass"),
    (
        "keysbench/arm_a.py",
        'if not rel or p.is_absolute() or PureWindowsPath(rel).drive or ".." in p.parts:',
        "if not rel:",
    ),
    # STORY-004 T7: the judge's evidence is checked by code, and the judge is never the contestant.
    ("keysbench/judge.py", "    if not quote_in_review:\n", "    if False:\n"),
    ("keysbench/judge.py", "    if not points:\n", "    if False:\n"),
    ("keysbench/judge.py", 'if verdict != "pass" or not found:', "if False:"),
    (
        "keysbench/judge.py",
        'return cfg.get("instead", "claude-sonnet-5-5") if contestant_model == default else default',
        "return default",
    ),
    ("keysbench/judge.py", 'return _MODEL_NAMES.sub("<contestant>", text)', "return text"),
    # STORY-004 T10 and task graders: escaped report, KB-05 relevance.
    ("keysbench/report.py", '[md_cell(f["mode"]), md_cell(f["task_id"])', '[f["mode"], md_cell(f["task_id"])'),
    (
        "keysbench/tasks/KB-05/tests/test_kb05.py",
        "    assert any(line in normalise(quote) for line in RELEVANT_LIMIT_LINES), quote\n",
        "    assert True\n",
    ),
    ("pyproject.toml", 'testpaths = ["tests"]', 'testpaths = ["tests", "keysbench"]'),
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
TIMEOUT_S = 120.0

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


def _suite(cwd: pathlib.Path, timeout_s: float | None = None) -> int:
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
        timeout=timeout_s,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    return r.returncode


# Baseline: the UNMUTATED copy must pass. If it does not (a file missing from the copy, a broken
# environment), every mutation would read as KILLED and the run would prove nothing.
started = time.monotonic()
if _suite(work) != 0:
    shutil.rmtree(work, ignore_errors=True)
    print("BASELINE RED: the unmutated copy fails its own suite; no mutation result would mean anything")
    sys.exit(3)
# A mutation that makes the suite hang has not passed it, so a timeout counts as KILLED. The limit is
# therefore tied to how long the clean suite takes: with a fixed 120 s, a suite that grew past it would
# have read every survivor as KILLED (the KeysBench grader tests made the suite several times longer).
TIMEOUT_S = max(TIMEOUT_S, 4 * (time.monotonic() - started))
print(f"baseline {time.monotonic() - started:.0f} s; a mutation times out after {TIMEOUT_S:.0f} s")

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
            status = "KILLED" if _suite(work, TIMEOUT_S) != 0 else "SURVIVED"
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
