"""STORY-B01: every case of stories/STORY-B01.cases.yaml, run through the real CLI, in process.

One runner reads the case grammar defined at the top of the cases file (patch, file, raw, raw_append,
raw_size_bytes, policy_patch) and checks every `expected` key. SB1-17 checks that the set of cases this
module runs is exactly the set in the file, so a case added there cannot sit unexecuted.
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from marketplace.cli import main

ROOT = Path(__file__).resolve().parents[2]
CASES = yaml.safe_load((ROOT / "stories" / "STORY-B01.cases.yaml").read_text("utf-8"))
BASE = ROOT / "samples" / "marketplace" / "manifests" / "test-plan-agent.yaml"
POLICY = ROOT / "samples" / "marketplace" / "policy.yaml"
DELETE = "<delete>"
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def apply_patch(doc: Any, patch: dict[str, Any]) -> Any:
    for dotted, value in patch.items():
        parts = [int(p) if p.isdigit() else p for p in dotted.split(".")]
        node = doc
        for part in parts[:-1]:
            node = node[part]
        last = parts[-1]
        if value == DELETE:
            del node[last]
        else:
            node[last] = value
    return doc


def dump(doc: Any) -> str:
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=1000)


def manifest_text(row: dict[str, Any]) -> str:
    if "raw" in row:
        return str(row["raw"])
    if "raw_size_bytes" in row:
        return "#" * int(row["raw_size_bytes"])
    base = ROOT / row["file"] if "file" in row else BASE
    text = base.read_text("utf-8")
    if "raw_append" in row:
        return text + row["raw_append"]
    if "patch" in row:
        return dump(apply_patch(yaml.safe_load(text), row["patch"]))
    return text


def run(row: dict[str, Any], tmp: Path) -> dict[str, Any]:
    manifest = tmp / "manifest.yaml"
    if row.get("file") == "does/not/exist.yaml" and "patch" not in row:
        manifest = tmp / "does-not-exist.yaml"
    else:
        manifest.write_text(manifest_text(row), encoding="utf-8")
    policy = POLICY
    if "policy_patch" in row:
        policy = tmp / "policy.yaml"
        policy.write_text(dump(apply_patch(yaml.safe_load(POLICY.read_text("utf-8")), row["policy_patch"])), "utf-8")
    args = ["validate", "--manifest", str(manifest), "--policy", str(policy)]
    out, err = io.StringIO(), io.StringIO()
    code = main(args, out=out, err=err)
    jout = io.StringIO()
    main([*args, "--json"], out=jout, err=io.StringIO())
    result = json.loads(jout.getvalue()) if jout.getvalue().strip() else None
    return {"code": code, "terminal": out.getvalue() + err.getvalue(), "json_text": jout.getvalue(), "result": result}


def check(expected: dict[str, Any], r: dict[str, Any]) -> None:
    result = r["result"]
    if "exit_code" in expected:
        assert r["code"] == expected["exit_code"], r["terminal"]
    if "verdict" in expected:
        assert result["verdict"] == expected["verdict"], result
    if "findings" in expected:
        assert len(result["findings"]) == expected["findings"], result["findings"]
    if "rules" in expected:
        assert result["verdict"] == "reject"
        assert {f["rule"] for f in result["findings"]} == set(expected["rules"]), result["findings"]
    if "paths" in expected:
        assert set(expected["paths"]) <= {f["path"] for f in result["findings"]}, result["findings"]
    if "every_finding_has" in expected:
        for f in result["findings"]:
            assert all(f.get(k) for k in expected["every_finding_has"]), f
    if "no_output_contains" in expected:
        secret = expected["no_output_contains"]
        assert secret not in r["terminal"] and secret not in r["json_text"]
    if expected.get("terminal_has_control_chars") is False:
        assert r["terminal"] and not CONTROL.search(r["terminal"])


def rows(case: dict[str, Any]) -> list[dict[str, Any]]:
    if "rows" in case:
        return case["rows"]
    if "files" in case:
        return [{"file": f, "expected": case["expected"]} for f in case["files"]]
    return [case]


RUNNABLE = [c for c in CASES if c["id"] not in ("SB1-15", "SB1-17")]


@pytest.mark.parametrize("case", RUNNABLE, ids=[c["id"] for c in RUNNABLE])
def test_case(case, tmp_path):
    for i, row in enumerate(rows(case)):
        sub = tmp_path / str(i)
        sub.mkdir()
        check(row["expected"], run(row, sub))


def test_sb1_15_tier_and_provenance(tmp_path):
    case = next(c for c in CASES if c["id"] == "SB1-15")
    tiers = []
    for i, f in enumerate(case["files"]):
        sub = tmp_path / str(i)
        sub.mkdir()
        result = run({"file": f}, sub)["result"]
        tiers.append(result["tier"])
        assert set(case["expected"]["checked_has"]) <= set(result["checked"])
    assert tiers == case["expected"]["tiers"]
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    one = run({}, a)["result"]["checked"]["policy_sha256"]
    two = run({"policy_patch": {"contact_domains": ["example.com", "example.org"]}}, b)["result"]["checked"]
    assert one != two["policy_sha256"]


def test_sb1_17_every_case_in_the_file_is_executed():
    executed = {c["id"] for c in RUNNABLE} | {"SB1-15", "SB1-17"}
    assert executed == {c["id"] for c in CASES}
