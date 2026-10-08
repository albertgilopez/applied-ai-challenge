"""Build samples/sbom.cdx.json and samples/sbom.spdx.json from one table.

Both files describe the same product, so they are generated from the same rows
instead of being written twice by hand. Licenses are the ones each project
declares in its registry (PyPI, npm, Maven Central, Hugging Face), checked on
2026-10-08; where a registry gives prose instead of an SPDX id, the row says
what was concluded from it.

    python samples/build_samples.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent

# name, version, purl, license (SPDX expression, or ("name", <license name>)), cyclonedx type
ROWS = [
    ("requests", "2.32.3", "pkg:pypi/requests@2.32.3", "Apache-2.0", "library"),
    ("numpy", "2.1.3", "pkg:pypi/numpy@2.1.3", "BSD-3-Clause", "library"),  # PyPI: license text is BSD 3-clause
    ("PyYAML", "6.0.2", "pkg:pypi/pyyaml@6.0.2", "MIT", "library"),
    ("psycopg2", "2.9.10", "pkg:pypi/psycopg2@2.9.10", ("name", "LGPL with exceptions"), "library"),  # PyPI wording
    ("PyQt5", "5.15.11", "pkg:pypi/pyqt5@5.15.11", "GPL-3.0-only", "library"),  # PyPI: "GPL v3"
    ("react", "18.3.1", "pkg:npm/react@18.3.1", "MIT", "library"),
    ("@babel/core", "7.26.0", "pkg:npm/%40babel/core@7.26.0", "MIT", "library"),
    ("lodash", "4.17.21", "pkg:npm/lodash@4.17.21", "MIT", "library"),
    ("slf4j-api", "2.0.13", "pkg:maven/org.slf4j/slf4j-api@2.0.13", "MIT", "library"),
    (
        "mysql-connector-j",
        "9.1.0",
        "pkg:maven/com.mysql/mysql-connector-j@9.1.0",
        "GPL-2.0-only WITH Universal-FOSS-exception-1.0",
        "library",
    ),
    ("Mistral-7B-v0.1", None, "pkg:huggingface/mistralai/Mistral-7B-v0.1", "Apache-2.0", "machine-learning-model"),
    (
        "Llama-3.1-8B",
        None,
        "pkg:huggingface/meta-llama/Llama-3.1-8B",
        ("name", "Llama 3.1 Community License"),
        "machine-learning-model",
    ),
    ("gemma-2-2b", None, "pkg:huggingface/google/gemma-2-2b", ("name", "Gemma Terms of Use"), "machine-learning-model"),
    ("internal-telemetry", "0.4.0", None, None, "library"),  # in-house component: no license, no source
]


def _ref(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ".-" else "-" for ch in name)


def _licenseref(name: str) -> str:
    # Same rule as core/sbom.py, written out again because this script runs standalone.
    return "LicenseRef-" + (re.sub(r"[^A-Za-z0-9.]+", "-", name).strip("-") or "unnamed")


def cyclonedx() -> dict[str, Any]:
    components: list[dict[str, Any]] = []
    for name, version, purl, lic, ctype in ROWS:
        c: dict[str, Any] = {"type": ctype, "bom-ref": purl or f"{name}@{version}", "name": name}
        if version:
            c["version"] = version
        if purl:
            c["purl"] = purl
        if isinstance(lic, tuple):
            c["licenses"] = [{"license": {"name": lic[1]}}]
        elif lic and " " in lic:
            c["licenses"] = [{"expression": lic}]
        elif lic:
            c["licenses"] = [{"license": {"id": lic}}]
        components.append(c)
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {"component": {"type": "application", "name": "sample-instrument-software", "version": "3.2.0"}},
        "components": components,
    }


def spdx() -> dict[str, Any]:
    packages, extracted = (
        [
            {
                "SPDXID": "SPDXRef-product",
                "name": "sample-instrument-software",
                "versionInfo": "3.2.0",
                "downloadLocation": "NOASSERTION",
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": "NOASSERTION",
            }
        ],
        {},
    )
    for name, version, purl, lic, _ in ROWS:
        if isinstance(lic, tuple):
            ref = _licenseref(lic[1])
            extracted[ref] = {"licenseId": ref, "name": lic[1], "extractedText": f"See the project's {lic[1]}."}
            lic = ref
        p: dict[str, Any] = {
            "SPDXID": f"SPDXRef-{_ref(name)}",
            "name": name,
            "downloadLocation": "NOASSERTION",
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": lic or "NOASSERTION",
        }
        if version:
            p["versionInfo"] = version
        if purl:
            p["externalRefs"] = [
                {"referenceCategory": "PACKAGE-MANAGER", "referenceType": "purl", "referenceLocator": purl}
            ]
        packages.append(p)
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "sample-instrument-software-3.2.0",
        "documentNamespace": "https://example.org/spdx/sample-instrument-software-3.2.0",
        "creationInfo": {"created": "2026-10-08T00:00:00Z", "creators": ["Tool: samples/build_samples.py"]},
        "packages": packages,
        "relationships": [
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relationshipType": "DESCRIBES",
                "relatedSpdxElement": "SPDXRef-product",
            }
        ],
        "hasExtractedLicensingInfos": list(extracted.values()),
    }


if __name__ == "__main__":
    for filename, doc in (("sbom.cdx.json", cyclonedx()), ("sbom.spdx.json", spdx())):
        (HERE / filename).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8", newline="\n")
        print("wrote", filename)
