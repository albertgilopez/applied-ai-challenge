# Open-source license review

- SBOM sha256: `571b377f9b8ef30b9ddf527cb69b4a2ffc76c969fbcf345883320791a50ca6f0`
- Policy sha256: `d78e5e952f623f686076e39ef8c101e213d1aaf87f24875f6eed362c58668478`
- Generated: 2026-10-10T08:00:00Z
- Product (the package this SBOM describes, left out of the review): sample-instrument-software@3.2.0

Counts cover the 14 reviewed components; the product is not one of them.

| Verdict | Count |
|---|---|
| Allow | 9 |
| Needs review | 4 |
| Reject | 1 |
| pending review | 13 |

## Components

| Component | Version | Verdict | Status | Reason | Source |
|---|---|---|---|---|---|
| internal-telemetry | 0.4.0 | Needs review | pending | no license declared; no source declared | none declared |
| gemma-2-2b | — | Needs review | pending | SBOM: custom license LicenseRef-Gemma-Terms-of-Use not in policy; model card: custom license LicenseRef-gemma not in policy (quoted: 'license: gemma'); restrictions: Use is subject to the Gemma Prohibited Use Policy; Models may not be used to generate content that infringes intellectual property rights or to facilitate harm; Use restrictions must be passed on to anyone the model or a derivative is distributed to | <https://huggingface.co/google/gemma-2-2b> |
| Llama-3.1-8B | — | Allow (decided Needs review) | overridden | SBOM: custom license LicenseRef-Llama-3.1-Community-License not in policy; model card: custom license LicenseRef-llama3.1 not in policy (quoted: 'license: llama3.1'); restrictions: Attribution: provide a copy of the Agreement with any distributed Llama Materials and prominently display "Built with Llama".; Must comply with applicable laws and regulations, including trade compliance laws, and adhere to the Acceptable Use Policy.; User threshold: licensees with more than 700 million monthly active users must request a license from Meta, which may be granted at Meta's sole discretion.; overridden by A. Reviewer | <https://huggingface.co/meta-llama/Llama-3.1-8B> |
| Mistral-7B-v0.1 | — | Allow | pending | SBOM: Apache-2.0 is allowed by policy; model card: Apache-2.0 is allowed by policy (quoted: 'license: apache-2.0') | <https://huggingface.co/mistralai/Mistral-7B-v0.1> |
| mysql-connector-j | 9.1.0 | Needs review | pending | GPL-2.0-only WITH Universal-FOSS-exception-1.0 not in policy | <https://central.sonatype.com/artifact/com.mysql/mysql-connector-j/9.1.0> |
| slf4j-api | 2.0.13 | Allow | pending | MIT is allowed by policy | <https://central.sonatype.com/artifact/org.slf4j/slf4j-api/2.0.13> |
| @babel/core | 7.26.0 | Allow | pending | MIT is allowed by policy | <https://www.npmjs.com/package/@babel/core/v/7.26.0> |
| lodash | 4.17.21 | Allow | pending | MIT is allowed by policy | <https://www.npmjs.com/package/lodash/v/4.17.21> |
| react | 18.3.1 | Allow | pending | MIT is allowed by policy | <https://www.npmjs.com/package/react/v/18.3.1> |
| numpy | 2.1.3 | Allow | pending | BSD-3-Clause is allowed by policy | <https://pypi.org/project/numpy/2.1.3/> |
| psycopg2 | 2.9.10 | Needs review | pending | custom license LicenseRef-LGPL-with-exceptions not in policy | <https://pypi.org/project/psycopg2/2.9.10/> |
| PyQt5 | 5.15.11 | Reject | pending | GPL-3.0-only is rejected by policy | <https://pypi.org/project/pyqt5/5.15.11/> |
| PyYAML | 6.0.2 | Allow | pending | MIT is allowed by policy | <https://pypi.org/project/pyyaml/6.0.2/> |
| requests | 2.32.3 | Allow | pending | Apache-2.0 is allowed by policy | <https://pypi.org/project/requests/2.32.3/> |

## Reviewer decisions

- Llama-3.1-8B — (decided: Needs review)
  - 2026-10-10T07:31:45Z overridden to Allow by A. Reviewer: Under 700M monthly active users; 'Built with Llama' shown on the about page; AUP accepted
