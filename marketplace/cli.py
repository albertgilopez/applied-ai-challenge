"""`python -m marketplace validate --manifest PATH --policy PATH [--json]` (STORY-B01).

This file reads files, picks the exit code and prints. Every rule lives in `core/manifest.py`; the
strict YAML reading lives in `app/strict_yaml.py`.

Exit codes: 0 accepted · 1 rejected · 2 the manifest cannot be read or the policy is invalid.
Terminal output is escaped (`core.report.safe_text`); every output is already redacted by the core.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version
from typing import TextIO

from app.strict_yaml import RefusedConstruct, Unreadable, read_yaml_file
from core.manifest import InvalidPolicy, Result, check_policy, refused, validate
from core.report import safe_text

MAX_MANIFEST_BYTES = 256 * 1024
MAX_POLICY_BYTES = 256 * 1024
UNREADABLE = 2


def _validator_version() -> str:
    try:
        return version("applied-ai-challenge")
    except PackageNotFoundError:  # pragma: no cover - running from a source tree without install
        return "unknown"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="marketplace", description="Validate an AI asset manifest against the policy.")
    sub = p.add_subparsers(dest="command", required=True)
    v = sub.add_parser("validate", help="accept or reject a manifest, with every finding")
    v.add_argument("--manifest", required=True)
    v.add_argument("--policy", required=True)
    v.add_argument("--json", action="store_true", help="print the result as JSON")
    return p


def _print(result: Result, out: TextIO, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2, sort_keys=True), file=out)
        return
    print(f"{result.verdict.upper()}  tier {result.tier if result.tier is not None else '-'}", file=out)
    for f in result.findings:
        print(f"  {f.rule}  {safe_text(f.path)}: {safe_text(f.message)}  -> {safe_text(f.hint)}", file=out)


def main(argv: Sequence[str] | None = None, *, out: TextIO = sys.stdout, err: TextIO = sys.stderr) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:  # argparse already printed the usage error
        return int(exc.code or 0)
    try:
        policy_data, policy_sha256 = read_yaml_file(args.policy, MAX_POLICY_BYTES)
        policy = check_policy(policy_data)
    except (Unreadable, RefusedConstruct, InvalidPolicy) as exc:
        print(f"invalid policy: {safe_text(str(exc))}", file=err)
        return UNREADABLE
    checked = {"policy_sha256": policy_sha256, "validator_version": _validator_version()}
    try:
        doc, manifest_sha256 = read_yaml_file(args.manifest, MAX_MANIFEST_BYTES)
        result = validate(doc, policy, {**checked, "manifest_sha256": manifest_sha256})
    except Unreadable as exc:
        print(f"unreadable manifest: {safe_text(str(exc))}", file=err)
        return UNREADABLE
    except RefusedConstruct as exc:
        line = f" (line {exc.problem_mark.line + 1})" if exc.problem_mark is not None else ""
        result = refused(f"{exc.problem or 'a YAML construct a manifest does not allow'}{line}", checked)
    _print(result, out, args.json)
    return 0 if result.verdict == "accept" else 1
