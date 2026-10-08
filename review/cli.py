"""The reviewer's command line: scan, list, approve, override, report.

Non-interactive on purpose: every command takes flags only, so a test and a live demo drive it the
same way. This file only reads files, reads the clock, appends ledger lines and prints. Every rule
Legal relies on (what counts as the same decision, which reviewer line wins, what is refused, how
SBOM text is escaped) lives in `core.review` and `core.report`.

Exit codes: 0 done; 2 refused (a bad file, a refused review line, a report before its scan), with
the reason on stderr and nothing written.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

from app.files import load_policy, load_sbom_document
from core.decide import decide
from core.policy import PolicyError
from core.report import build_report, safe_text, to_markdown
from core.review import VERDICTS, ReviewError, check_approve, check_override, decision_key, decision_record, fold
from core.sbom import FormatError
from harness.ledger import Ledger
from harness.storage import CorruptRecord, utc_stamp

REFUSED = 2


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="review", description="Human review of an SBOM license decision run.")
    sub = p.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="decide every component not decided yet under this policy")
    scan.add_argument("--sbom", required=True)
    scan.add_argument("--policy", required=True)
    scan.add_argument("--ledger", required=True)

    pending = sub.add_parser("list", help="decisions no reviewer has looked at")
    pending.add_argument("--ledger", required=True)

    approve = sub.add_parser("approve", help="accept a decision as it stands")
    approve.add_argument("--ledger", required=True)
    approve.add_argument("--decision", required=True)
    approve.add_argument("--by", required=True)
    approve.add_argument("--reason")

    override = sub.add_parser("override", help="replace a decision's verdict")
    override.add_argument("--ledger", required=True)
    override.add_argument("--decision", required=True)
    override.add_argument("--verdict", required=True, help=" | ".join(VERDICTS))
    override.add_argument("--by", required=True)
    override.add_argument("--reason")  # required by the rule, checked in core so the refusal is uniform

    report = sub.add_parser("report", help="write report.json and report.md for Legal")
    report.add_argument("--sbom", required=True)
    report.add_argument("--policy", required=True)
    report.add_argument("--ledger", required=True)
    report.add_argument("--out", required=True)
    return p


def _scan(args: argparse.Namespace, out: TextIO) -> None:
    doc, _ = load_sbom_document(args.sbom)
    policy = load_policy(args.policy)
    digest = policy.digest()
    ledger = Ledger(args.ledger)
    known = {s.key for s in fold(ledger.read()).values()}
    decided = reused = 0
    for c in doc.components:
        key = decision_key(c, digest)
        if key in known:
            reused += 1  # the recorded verdict stands; a re-run never decides again (DR-9)
            continue
        ledger.append(decision_record(c, decide(c, policy), digest))
        known.add(key)
        decided += 1
    print(f"{decided} decided, {reused} reused", file=out)


def _list(args: argparse.Namespace, out: TextIO) -> None:
    for s in fold(Ledger(args.ledger).read()).values():
        if s.status == "pending":
            label = s.name + (f"@{s.version}" if s.version else "")
            print(f"{s.decision_id}  {safe_text(label)}  {s.decided_verdict}  {safe_text(s.reason)}", file=out)


def _review(args: argparse.Namespace, out: TextIO) -> None:
    ledger = Ledger(args.ledger)
    states = fold(ledger.read())
    if args.command == "approve":
        record = check_approve(states, args.decision, args.by, args.reason)
    else:
        record = check_override(states, args.decision, args.verdict, args.by, args.reason)
    print(f"{args.command} recorded as {ledger.append(record)}", file=out)


def _write(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))  # bytes: identical files on Windows and Linux


def _report(args: argparse.Namespace, out: TextIO, now: Callable[[], str]) -> None:
    doc, sbom_sha256 = load_sbom_document(args.sbom)
    policy = load_policy(args.policy)
    report = build_report(
        doc.components,
        doc.product,
        fold(Ledger(args.ledger).read()),
        sbom_sha256=sbom_sha256,
        policy_sha256=policy.digest(),
        generated_at=now(),
    )
    target = Path(args.out)
    target.mkdir(parents=True, exist_ok=True)
    _write(target / "report.json", json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    _write(target / "report.md", to_markdown(report))
    print(f"report written to {safe_text(str(target))}", file=out)


def main(
    argv: Sequence[str] | None = None,
    *,
    now: Callable[[], str] = utc_stamp,
    out: TextIO = sys.stdout,
    err: TextIO = sys.stderr,
) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:  # argparse already printed the usage error
        return int(exc.code or 0)
    try:
        if args.command == "scan":
            _scan(args, out)
        elif args.command == "list":
            _list(args, out)
        elif args.command in ("approve", "override"):
            _review(args, out)
        else:
            _report(args, out, now)
    except (ReviewError, FormatError, PolicyError, CorruptRecord, FileNotFoundError) as exc:
        print(f"refused: {safe_text(str(exc))}", file=err)
        return REFUSED
    return 0
