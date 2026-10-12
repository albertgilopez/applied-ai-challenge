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

from agent.model_cards import CardNotFound, InvalidModelId, http_fetch, load_card, model_id_from_purl
from app.files import load_policy, load_sbom_document
from core.component import Component
from core.decide import Decision, decide
from core.model_card import card_key, evidence_digest, review_model
from core.policy import REVIEW, Policy, PolicyError
from core.report import build_report, safe_text, to_markdown
from core.review import VERDICTS, ReviewError, check_approve, check_override, decision_key, decision_record, fold
from core.sbom import FormatError
from harness.ledger import Ledger
from harness.prompts import UnapprovedPrompt, digest
from harness.providers import Provider
from harness.replay import CassetteMiss
from harness.storage import CorruptRecord, JSONObject, utc_stamp

REFUSED = 2


class ModelUnavailable(Exception):
    """The model could not be reached or the SDK raised an API error, so nothing was decided for this component."""


def _provider_errors() -> tuple[type[BaseException], ...]:
    """What a model call raises when the provider cannot answer: network errors and the SDK's own API errors
    (timeouts and connection failures included). Not `OSError` as a whole: a missing card is a FileNotFoundError
    and `main()` already refuses that for its own reason. Any other exception is a bug and propagates."""
    errors: tuple[type[BaseException], ...] = (ConnectionError, TimeoutError)
    try:
        import anthropic
    except ImportError:  # pragma: no cover - the SDK is a dependency
        return errors
    return (*errors, anthropic.APIError)


DEFAULT_RECORDINGS = Path(__file__).resolve().parents[1] / "tests" / "cassettes" / "story_002"

# (model id, live, recordings dir) -> the provider for that model's review
ProviderFactory = Callable[[str, bool, Path], Provider]


def recorded_provider(model_id: str, live: bool, recordings: Path) -> Provider:
    """Live: call the model and record every response. Offline: replay, and refuse what was never recorded."""
    from harness.providers import AnthropicProvider
    from harness.replay import RecordingProvider, ReplayProvider

    path = recordings / f"{model_id.replace('/', '__')}.jsonl"
    if live:
        return RecordingProvider(AnthropicProvider(), path)
    if not path.is_file():
        raise ReviewError(f"no recording for {model_id} in {recordings}; run scan with --live to record it")
    return ReplayProvider(path)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="review", description="Human review of an SBOM license decision run.")
    sub = p.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="decide every component not decided yet under this policy")
    scan.add_argument("--sbom", required=True)
    scan.add_argument("--policy", required=True)
    scan.add_argument("--ledger", required=True)
    scan.add_argument("--model-cards", help="review AI models against their cards, read from this directory")
    scan.add_argument("--recordings", default=str(DEFAULT_RECORDINGS), help="recorded model responses to replay")
    scan.add_argument("--live", action="store_true", help="call the model (and record); fetch missing cards")

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
    report.add_argument("--model-cards", help="the same directory the scan used, if it reviewed AI models")
    return p


def _card_decision(
    c: Component,
    policy: Policy,
    args: argparse.Namespace,
    ledger: Ledger,
    factory: ProviderFactory,
    card: str,
    model_id: str,
) -> tuple[Decision, JSONObject]:
    from agent.reviewer import review_card

    provider = factory(model_id, args.live, Path(args.recordings))
    fetch = http_fetch if args.live else None
    result = review_card(model_id, provider=provider, ledger=ledger, cards_dir=args.model_cards, fetch=fetch)
    review = review_model(c, result.extraction, card, policy)
    x = result.extraction
    evidence: JSONObject = {
        "model_id": model_id,
        "license": review.license,
        "grounded": review.grounded,
        "quote": x.quote if x else None,
        "restrictions": [{"text": r.text, "quote": r.quote} for r in review.restrictions],
        "restrictions_not_grounded": review.dropped,
        "extraction_sha256": evidence_digest(card, x) if x else None,
        "cost_usd": result.run.cost_usd,
    }
    return review.decision, evidence


def _card_inputs(c: Component, model_cards: str | None, live: bool) -> tuple[str | None, str | None, str | None]:
    """(model id, card text, card key) for an AI model reviewed against its card; Nones otherwise.

    `scan` and `report` both call this, so the key a report looks up is the key the scan wrote.
    """
    from agent.reviewer import EFFORT, MODEL, PROMPT

    if not (model_cards and c.is_ai_model):
        return None, None, None
    model_id = model_id_from_purl(c.purl)
    try:
        card: str | None = load_card(model_id or "", model_cards, http_fetch if live else None)
    except (InvalidModelId, CardNotFound):
        card = None
    # Keyed on what the decision is made from: the card, and the prompt, model and effort that read it.
    return model_id, card, card_key(card or "", digest(PROMPT), MODEL, EFFORT)


def _scan(args: argparse.Namespace, out: TextIO, factory: ProviderFactory) -> None:
    doc, _ = load_sbom_document(args.sbom)
    policy = load_policy(args.policy)
    policy_digest = policy.digest()
    ledger = Ledger(args.ledger)
    known = {s.key for s in fold(ledger.read()).values()}
    decided = reused = 0
    for c in doc.components:
        model_id, card, ckey = _card_inputs(c, args.model_cards, args.live)
        key = decision_key(c, policy_digest, ckey)
        if key in known:
            reused += 1  # the recorded verdict stands; a re-run never decides again (DR-9)
            continue
        evidence: JSONObject | None = None
        if ckey is None:
            decision = decide(c, policy)
        elif card is None or model_id is None:
            what = "no model id in the SBOM entry" if model_id is None else f"no model card for {model_id}"
            decision = Decision(c.ref, REVIEW, f"{decide(c, policy).reason}; model card: {what}", c.source_url)
            evidence = {"model_id": model_id, "license": None, "grounded": False}
        else:
            try:
                decision, evidence = _card_decision(c, policy, args, ledger, factory, card, model_id)
            except _provider_errors() as exc:
                # No decision is written: a recorded verdict stands and a re-run would reuse it (DR-9), so a
                # `Needs review` frozen by an outage would never be asked again. Nothing is approved either
                # way: the report refuses a component without a decision. The failed run is already in the
                # ledger (`run_end` with the error), so the history shows what happened.
                raise ModelUnavailable(
                    f"{c.name}: the model call failed ({type(exc).__name__}); no decision was recorded for it "
                    "and nothing is approved. Run scan again when the model answers."
                ) from exc
        ledger.append(decision_record(c, decision, policy_digest, ckey, evidence))
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
    card_keys = {}
    for c in doc.components:
        _, _, ckey = _card_inputs(c, args.model_cards, live=False)
        if ckey is not None:
            card_keys[c.identity] = ckey
    report = build_report(
        doc.components,
        doc.product,
        fold(Ledger(args.ledger).read()),
        sbom_sha256=sbom_sha256,
        policy_sha256=policy.digest(),
        generated_at=now(),
        card_keys=card_keys,
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
    provider_factory: ProviderFactory = recorded_provider,
) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:  # argparse already printed the usage error
        return int(exc.code or 0)
    try:
        if args.command == "scan":
            _scan(args, out, provider_factory)
        elif args.command == "list":
            _list(args, out)
        elif args.command in ("approve", "override"):
            _review(args, out)
        else:
            _report(args, out, now)
    except (
        ReviewError,
        FormatError,
        PolicyError,
        CorruptRecord,
        FileNotFoundError,
        CassetteMiss,
        UnapprovedPrompt,
        ModelUnavailable,
    ) as exc:
        print(f"refused: {safe_text(str(exc))}", file=err)
        return REFUSED
    return 0
