"""Validate an AI asset's manifest against the organisation's policy (STORY-B01).

Pure: the caller loads the YAML (app/strict_yaml.py) and hands plain data here. Every rule adds findings
and never raises, so one run reports everything a manifest breaks (P1). Rules R1-R7 are in the story;
each finding names its rule, the path in the manifest, a message and a hint for the fix.

Two things run over every output: secrets found anywhere are redacted from every message and path (P2),
and nothing in the manifest's text chooses which checks run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

SUPPORTED_API_VERSIONS = ("marketplace/v1",)
KINDS = ("agent", "skill", "mcp-server", "eval-pack")
DOMAINS = ("software", "hardware-firmware", "simulation")
SENSITIVITIES = ("public", "internal", "confidential", "restricted")
ACCESS = ("read", "write")
EFFECTS = ("read", "write", "outward", "physical")
REACHES_THE_WORLD = ("outward", "physical")
SCAN_TOOLS = ("black-duck", "polaris")
SCAN_STATUS = ("passed", "failed")

ID = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")  # the SKILL.md name rule: lowercase, digits, single hyphens
SEMVER = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?")
SHA256_HEX = re.compile(r"[0-9a-f]{64}")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
SECRET_NAME = re.compile(r"[A-Z][A-Z0-9_]*")
RESOURCE = re.compile(r"[a-z][a-z0-9-]*:[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*")
LABEL = r"[a-z0-9]([a-z0-9-]*[a-z0-9])?"
HOST = re.compile(rf"{LABEL}(\.{LABEL})+")
ARTIFACT_REF = re.compile(r"artifactory://[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*")
VAULT_PATH = re.compile(r"[a-z0-9][a-z0-9_-]*(/[a-z0-9][a-z0-9_-]*)*")

# Credential formats (a format check, so a pattern is the right tool). The code scanner in the pipeline
# is the wider net; this is the manifest-level minimum.
SECRET_FORMATS = (
    ("an Anthropic API key", re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}")),
    ("an API key", re.compile(r"\bsk-[A-Za-z0-9]{20,}")),
    ("a GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    ("a Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("an AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("a Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
    ("a private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("a password in a URL", re.compile(r"[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@", re.IGNORECASE)),
)

# R1: the format as a table. ("type", required) per field; nested objects and lists of objects by name.
OBJECTS: dict[str, dict[str, tuple[str, bool]]] = {
    "": {
        "apiVersion": ("str", True),
        "id": ("str", True),
        "version": ("str", True),
        "kind": ("str", True),
        "domains": ("list[str]", True),
        "owner": ("owner", True),
        "summary": ("str", True),
        "data": ("data", True),
        "model": ("model", False),
        "permissions": ("list[permission]", True),
        "egress": ("list[str]", True),
        "secrets": ("list[secret]", True),
        "tools": ("list[tool]", True),
        "artifact": ("artifact", True),
        "source": ("str", True),
        "security_scan": ("security_scan", True),
    },
    "owner": {"team": ("str", True), "contact": ("str", True)},
    "data": {"sensitivity": ("str", True)},
    "model": {"provider": ("str", True), "id": ("str", True)},
    "permission": {"resource": ("str", True), "access": ("str", True)},
    "secret": {"name": ("str", True), "ref": ("str", True)},
    "tool": {
        "name": ("str", True),
        "effect": ("str", True),
        "requires_human_approval": ("bool", True),
        "definition_sha256": ("str", True),
    },
    "artifact": {"ref": ("str", True), "digest": ("str", True)},
    "security_scan": {
        "tool": ("str", True),
        "id": ("str", True),
        "artifact_digest": ("str", True),
        "status": ("str", True),
        "critical": ("count", True),
        "high": ("count", True),
    },
}
ENUMS = {
    "kind": KINDS,
    "domains.*": DOMAINS,
    "data.sensitivity": SENSITIVITIES,
    "permissions.*.access": ACCESS,
    "tools.*.effect": EFFECTS,
    "security_scan.tool": SCAN_TOOLS,
    "security_scan.status": SCAN_STATUS,
}
PATTERNS = {
    "id": (ID, "1-64 lowercase letters, digits and single hyphens, e.g. 'test-plan-agent'"),
    "version": (SEMVER, 'a quoted semver string, e.g. "1.4.0"'),
    "secrets.*.name": (SECRET_NAME, "an upper-case environment variable name, e.g. 'JIRA_TOKEN'"),
    "tools.*.definition_sha256": (SHA256_HEX, "the 64-hex sha256 of the tool's definition as the server serves it"),
    "artifact.ref": (ARTIFACT_REF, "'artifactory://<repo>/<name>'"),
}


@dataclass(frozen=True)
class Finding:
    rule: str
    path: str
    message: str
    hint: str


@dataclass(frozen=True)
class Result:
    verdict: str  # "accept" | "reject"
    tier: int | None
    findings: tuple[Finding, ...]
    checked: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "tier": self.tier,
            "findings": [f.__dict__ for f in self.findings],
            "checked": dict(self.checked),
        }


class InvalidPolicy(ValueError):
    pass


@dataclass(frozen=True)
class MarketplacePolicy:
    contact_domains: frozenset[str]
    source_hosts: frozenset[str]
    model_hosts: dict[str, str]
    forbidden_scopes: frozenset[str]
    providers: dict[str, frozenset[str]]
    egress: dict[str, frozenset[str]]
    max_critical: int
    max_high: int


# ── the policy fails closed too (P4) ──────────────────────────────────────────────────────────────


def _str_list(value: Any, where: str) -> frozenset[str]:
    if type(value) is not list or not all(type(v) is str for v in value):
        raise InvalidPolicy(f"{where} must be a list of strings")
    return frozenset(value)


def _count(value: Any, where: str) -> int:
    if type(value) is not int or value < 0:
        raise InvalidPolicy(f"{where} must be a non-negative integer")
    return value


def check_policy(data: Any) -> MarketplacePolicy:
    keys = {"contact_domains", "source_hosts", "model_hosts", "forbidden_scopes", "sensitivity", "scan"}
    if type(data) is not dict or set(data) != keys:
        raise InvalidPolicy(f"the policy must have exactly these keys: {', '.join(sorted(keys))}")
    hosts = data["model_hosts"]
    if type(hosts) is not dict or not all(type(k) is str and type(v) is str for k, v in hosts.items()):
        raise InvalidPolicy("model_hosts must map hosts to provider names")
    levels = data["sensitivity"]
    if type(levels) is not dict or set(levels) != set(SENSITIVITIES):
        raise InvalidPolicy(f"sensitivity must define exactly: {', '.join(SENSITIVITIES)}")
    providers, egress = {}, {}
    for level in SENSITIVITIES:
        entry = levels[level]
        if type(entry) is not dict or set(entry) != {"providers", "egress"}:
            raise InvalidPolicy(f"sensitivity.{level} must have exactly 'providers' and 'egress'")
        providers[level] = _str_list(entry["providers"], f"sensitivity.{level}.providers")
        egress[level] = _str_list(entry["egress"], f"sensitivity.{level}.egress")
    scan = data["scan"]
    if type(scan) is not dict or set(scan) != {"max_critical", "max_high"}:
        raise InvalidPolicy("scan must have exactly 'max_critical' and 'max_high'")
    return MarketplacePolicy(
        contact_domains=_str_list(data["contact_domains"], "contact_domains"),
        source_hosts=_str_list(data["source_hosts"], "source_hosts"),
        model_hosts=dict(hosts),
        forbidden_scopes=_str_list(data["forbidden_scopes"], "forbidden_scopes"),
        providers=providers,
        egress=egress,
        max_critical=_count(scan["max_critical"], "scan.max_critical"),
        max_high=_count(scan["max_high"], "scan.max_high"),
    )


# ── validation ────────────────────────────────────────────────────────────────────────────────────


class _Run:
    def __init__(self) -> None:
        self.findings: list[Finding] = []
        self.secrets: set[str] = set()

    def add(self, rule: str, path: str, message: str, hint: str) -> None:
        self.findings.append(Finding(rule, path, message, hint))


def _obj(doc: dict[str, Any], key: str) -> dict[str, Any]:
    """The mapping at `key`, or an empty one: rules read defensively, R1 reports the wrong type."""
    value = doc.get(key)
    return value if isinstance(value, dict) else {}


def _list(doc: dict[str, Any], key: str) -> list[Any]:
    value = doc.get(key)
    return value if isinstance(value, list) else []


def _generic(path: str) -> str:
    return re.sub(r"\.\d+(?=\.|$)", ".*", path)


def _typed(value: Any, kind: str) -> bool:
    if kind == "str":
        return type(value) is str
    if kind == "bool":
        return type(value) is bool  # exact: a string "false" is not a boolean
    if kind == "count":
        return type(value) is int and value >= 0  # exact: True is an int in Python, and is not a count
    if kind.startswith("list["):
        return type(value) is list
    return type(value) is dict


def _schema(run: _Run, obj: Any, name: str, path: str) -> None:
    spec = OBJECTS[name]
    if type(obj) is not dict:
        run.add("R1", path or "$", "expected a mapping", "write this as key: value pairs")
        return
    for key in obj:
        if key not in spec:
            run.add(
                "R1", f"{path}.{key}".lstrip("."), "a field the format does not define", "remove it or check spelling"
            )
    for key, (kind, required) in spec.items():
        here = f"{path}.{key}".lstrip(".")
        if key not in obj:
            if required:
                run.add("R1", here, "required field is missing", f"add '{key}'")
            continue
        value = obj[key]
        if not _typed(value, kind):
            run.add("R1", here, f"expected {kind}", f"write '{key}' as {kind}")
            continue
        if kind in OBJECTS:
            _schema(run, value, kind, here)
        elif kind.startswith("list["):
            inner = kind[5:-1]
            for i, item in enumerate(value):
                item_path = f"{here}.{i}"
                if inner in OBJECTS:
                    _schema(run, item, inner, item_path)
                elif not _typed(item, inner):
                    run.add("R1", item_path, f"expected {inner}", f"write each item as {inner}")
                else:
                    _value_checks(run, item_path, item)
        else:
            _value_checks(run, here, value)


def _value_checks(run: _Run, path: str, value: Any) -> None:
    generic = _generic(path)
    allowed = ENUMS.get(generic)
    if allowed is not None and value not in allowed:
        run.add("R1", path, "a value outside the allowed set", f"use one of: {', '.join(allowed)}")
    pattern = PATTERNS.get(generic)
    if pattern is not None and not (type(value) is str and pattern[0].fullmatch(value)):
        run.add("R1", path, "a value in the wrong format", f"use {pattern[1]}")
    if generic == "id" and type(value) is str and len(value) > 64:
        run.add("R1", path, "longer than 64 characters", "shorten the id")


def _walk_strings(node: Any, path: str = "") -> list[tuple[str, str, bool]]:
    """(path, text, is_key) for every key and string value."""
    out: list[tuple[str, str, bool]] = []
    if isinstance(node, dict):
        for k, v in node.items():
            child = f"{path}.{k}".lstrip(".")
            out.append((child, str(k), True))
            out.extend(_walk_strings(v, child))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out.extend(_walk_strings(v, f"{path}.{i}".lstrip(".")))
    elif isinstance(node, str):
        out.append((path, node, False))
    return out


def _r2_secrets(run: _Run, doc: dict[str, Any]) -> None:
    for path, text, is_key in _walk_strings(doc):
        for label, pattern in SECRET_FORMATS:
            if pattern.search(text):
                run.secrets.add(text)
                where = "a key" if is_key else "a value"
                run.add(
                    "R2",
                    path,
                    f"{where} has the format of {label}",
                    "remove it and declare a vault:// reference in secrets",
                )
                break
    team = _obj(doc, "owner").get("team")
    if not isinstance(team, str):
        return  # R1 already reports the missing owner; without a team there is nothing to compare against
    for i, secret in enumerate(_list(doc, "secrets")):
        ref = secret.get("ref") if isinstance(secret, dict) else None
        if not isinstance(ref, str):
            continue
        prefix = f"vault://{team}/" if isinstance(team, str) else None
        ok = prefix is not None and ref.startswith(prefix) and VAULT_PATH.fullmatch(ref[len(prefix) :]) is not None
        if not ok or ".." in ref:
            run.add(
                "R2", f"secrets.{i}.ref", "not a vault reference under the owner's team", f"use vault://{team}/<path>"
            )


def _host_ok(host: Any) -> bool:
    if type(host) is not str or not HOST.fullmatch(host) or len(host) > 253:
        return False
    return not all(label.isdigit() for label in host.split("."))  # an IP literal is not a host name


def _r3_names(run: _Run, doc: dict[str, Any], policy: MarketplacePolicy) -> None:
    for i, perm in enumerate(_list(doc, "permissions")):
        res = perm.get("resource") if isinstance(perm, dict) else None
        if not isinstance(res, str):
            continue
        path = f"permissions.{i}.resource"
        if "*" in res or not RESOURCE.fullmatch(res):
            run.add(
                "R3", path, "not a precise resource", "name it as <system>:<scope>, no wildcards, e.g. jira:project/QA"
            )
            continue
        scope_parts = res.split(":", 1)[1].split("/")
        if any(part.lower() in policy.forbidden_scopes for part in scope_parts):
            run.add("R3", path, "a scope the policy forbids as too broad", "name the project, space or bench it needs")
    for i, host in enumerate(_list(doc, "egress")):
        if isinstance(host, str) and not _host_ok(host):
            run.add("R3", f"egress.{i}", "not a host name", "a lowercase host name: no wildcard, IP address or port")


def _r4_data(run: _Run, doc: dict[str, Any], policy: MarketplacePolicy) -> None:
    level = _obj(doc, "data").get("sensitivity")
    model = _obj(doc, "model")
    provider = model.get("provider")
    if doc.get("kind") == "eval-pack" and "model" in doc:
        run.add(
            "R4",
            "model",
            "an evaluation pack calls no model",
            "remove 'model': the pack is what models are measured on",
        )
    if level not in SENSITIVITIES:
        return
    if isinstance(provider, str) and provider not in policy.providers[level]:
        run.add(
            "R4",
            "model.provider",
            f"provider not approved for {level} data",
            "use a provider the policy approves for this sensitivity",
        )
    for i, host in enumerate(_list(doc, "egress")):
        if not _host_ok(host):
            continue  # R3 already reported it
        if host not in policy.egress[level]:
            run.add(
                "R4",
                f"egress.{i}",
                f"host not approved for {level} data",
                "remove it or ask for it to be approved for this sensitivity",
            )
        api_provider = policy.model_hosts.get(host)
        if api_provider is not None and api_provider != provider:
            run.add(
                "R4",
                f"egress.{i}",
                "a model API with no matching model declared",
                f"declare model.provider: {api_provider}, or remove the host",
            )


def _r5_effects(run: _Run, doc: dict[str, Any]) -> None:
    tools = _list(doc, "tools")
    kind = doc.get("kind")
    if kind in ("agent", "mcp-server") and not tools:
        run.add(
            "R5", "tools", f"an {kind} must list its tools", "list every tool with its effect and definition digest"
        )
    for i, tool in enumerate(tools):
        if not isinstance(tool, dict) or tool.get("effect") not in REACHES_THE_WORLD:
            continue
        if kind == "eval-pack":
            run.add(
                "R5",
                f"tools.{i}",
                "an evaluation pack has no outward or physical tool",
                "an evaluation pack only reads and runs tasks",
            )
        elif tool.get("requires_human_approval") is not True and type(tool.get("requires_human_approval")) is bool:
            run.add(
                "R5",
                f"tools.{i}",
                f"a {tool.get('effect')} tool without human approval",
                "set requires_human_approval: true",
            )


def _r6_pinned(run: _Run, doc: dict[str, Any], policy: MarketplacePolicy) -> None:
    artifact = _obj(doc, "artifact")
    scan = _obj(doc, "security_scan")
    digest = artifact.get("digest")
    if isinstance(digest, str) and not DIGEST.fullmatch(digest):
        run.add(
            "R6",
            "artifact.digest",
            "the artifact is not pinned by a sha256 digest",
            "use sha256:<64 lowercase hex> from Artifactory",
        )
    covered = scan.get("artifact_digest")
    if isinstance(covered, str) and covered != digest:
        run.add(
            "R6",
            "security_scan.artifact_digest",
            "the scan is of another artifact",
            "scan this digest; the pipeline writes this block",
        )
    if scan.get("status") == "failed":
        run.add("R6", "security_scan.status", "the security scan failed", "fix the findings and scan again")
    for key, limit in (("critical", policy.max_critical), ("high", policy.max_high)):
        count = scan.get(key)
        if type(count) is int and count > limit:
            run.add(
                "R6",
                f"security_scan.{key}",
                f"{count} {key} findings, above the limit of {limit}",
                "fix them or get a waiver",
            )


def _r7_accountable(run: _Run, doc: dict[str, Any], policy: MarketplacePolicy) -> None:
    owner = _obj(doc, "owner")
    contact = owner.get("contact")
    if isinstance(contact, str):
        parts = contact.split("@")
        if len(parts) != 2 or not parts[0] or parts[1] not in policy.contact_domains:
            run.add(
                "R7", "owner.contact", "not a contact on an approved domain", "use a team address on the company domain"
            )
    source = doc.get("source")
    if isinstance(source, str):
        ok = source.startswith("https://")
        authority = source[len("https://") :].split("/", 1)[0] if ok else ""
        if ok and any(c in authority.lower() for c in ("@", "\\", "%5c", ":")):
            ok = False
        if not ok or authority not in policy.source_hosts:
            run.add(
                "R7",
                "source",
                "not an https URL on an approved source host",
                "use https://<approved host>/<path>, no user, port or backslash",
            )


def tier_of(doc: dict[str, Any]) -> int:
    tools = _list(doc, "tools")
    perms = _list(doc, "permissions")
    level = _obj(doc, "data").get("sensitivity")
    if level == "restricted" or any(isinstance(t, dict) and t.get("effect") in REACHES_THE_WORLD for t in tools):
        return 3
    if level == "confidential" or any(isinstance(p, dict) and p.get("access") == "write" for p in perms):
        return 2
    return 1


def _redact(text: str, secrets: set[str]) -> str:
    for secret in sorted(secrets, key=len, reverse=True):
        text = text.replace(secret, "[redacted]")
    return text


def _finish(run: _Run, tier: int | None, checked: dict[str, str]) -> Result:
    findings = tuple(
        Finding(f.rule, _redact(f.path, run.secrets), _redact(f.message, run.secrets), _redact(f.hint, run.secrets))
        for f in run.findings
    )
    return Result("reject" if findings else "accept", tier, findings, checked)


def refused(reason: str, checked: dict[str, str]) -> Result:
    """The loader refused a construct (duplicate key, alias, merge key, tag): the manifest is unsafe."""
    return Result(
        "reject",
        None,
        (Finding("R1", "$", reason, "write plain YAML: no anchors, aliases, merges, tags or repeated keys"),),
        checked,
    )


def validate(doc: Any, policy: MarketplacePolicy, checked: dict[str, str]) -> Result:
    run = _Run()
    if type(doc) is not dict:
        run.add("R1", "$", "a manifest is a mapping", "start with 'apiVersion: marketplace/v1'")
        return _finish(run, None, checked)
    api = doc.get("apiVersion")
    checked = {**checked, "api_version": api if isinstance(api, str) else ""}
    _schema(run, doc, "", "")
    if "apiVersion" in doc and api not in SUPPORTED_API_VERSIONS:
        run.add("R1", "apiVersion", "a version this validator does not support", f"use {SUPPORTED_API_VERSIONS[0]}")
    _r2_secrets(run, doc)
    _r3_names(run, doc, policy)
    _r4_data(run, doc, policy)
    _r5_effects(run, doc)
    _r6_pinned(run, doc, policy)
    _r7_accountable(run, doc, policy)
    return _finish(run, tier_of(doc), checked)
