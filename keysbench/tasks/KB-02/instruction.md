# Bug report: SBOM components that are never reviewed

The working directory holds `core/`, a small Python package that reads an SBOM (CycloneDX 1.6 or SPDX
2.3, as parsed JSON) into a flat list of components. `core.sbom.parse_sbom(document)` is the entry
point; it raises `core.sbom.FormatError` for a document it cannot read.

Two problems were reported:

1. **The product's own sub-components get no verdict.** In CycloneDX, the product described by the SBOM
   sits in `metadata.component`, and it can list its own parts under `metadata.component.components`
   (which can nest further, like any `components` list). The product itself is not a component to
   review, but every one of its sub-components is, at any depth. Today they are skipped.
2. **A document that claims both formats is read as one of them.** A JSON object with both
   `bomFormat` (CycloneDX) and `spdxVersion` (SPDX) is read as CycloneDX and its SPDX packages are
   silently ignored. Such a document must be refused with a `FormatError` whose message says the
   document carries **both** formats.

Everything else stays as it is: nested `components` are flattened, SPDX `packages` are read.

You may change `core/sbom.py`. Changes to other files are not kept.
