# ADR-0073: GenOffice DOCX Fidelity Evidence Verification

- Status: Accepted
- Date: 2026-08-13
- Scope: Office Quick Edit evaluation only
- Supersedes: none
- Extends: ADR-0060, ADR-0070, ADR-0071, ADR-0072

## Context

ADR-0072 defined signed result envelopes for nine future Word, LibreOffice and GenOffice assignments. The envelope binds
hash references for output, preflight, OOXML structure, Open XML validation, CDR pages, font inventory, visual metrics
and execution receipt. Signature and hash-reference validation alone cannot establish that the referenced files exist,
match those hashes or reproduce the claimed security and fidelity observations.

The evidence verifier must remain independent of every Office engine. It cannot trust a runner-generated preflight,
structural report or pixel metric merely because the runner signed it. At the same time, it must not import a second
tenant or production CDR model into the study. The study uses only deterministic synthetic documents and remains unable
to approve compatibility or product use.

## Decision

Collabio introduces a source-blind, no-engine Fidelity Evidence Verifier. It accepts four external inputs:

- one exact evidence directory;
- one ADR-0072 signed result envelope;
- one public, hash-valid engine signer policy;
- one hash-valid study plan.

The evidence directory has an exact top-level inventory. Unknown entries, links, special files, empty files, excessive
individual or aggregate size, duplicate JSON keys and non-strict schema fields fail closed. Every artifact except the
execution receipt is listed by canonical relative path, exact byte length and SHA-256 inside the receipt. The receipt
cannot list or hash itself. Its own hash is bound into the signed result payload.

The verifier performs these independent checks:

1. Recompute the study-plan, signer-policy, payload, envelope and Ed25519 signature bindings.
2. Hash the output DOCX bytes and rerun the canonical ADR-0071 preflight.
3. Recompute the bounded no-extraction OOXML structural fingerprint from the output bytes.
4. Validate the strict metadata-only Open XML SDK report and its output binding.
5. Validate engine, version, runner, environment and normalized font-inventory bindings.
6. Validate every reference and candidate raw-RGB page byte against separate study CDR manifests.
7. Recompute every deterministic RGB page comparison and require exact equality with the manifest.
8. Rebuild the evidence artifact inventory and compare it with the signed execution receipt.
9. Bind every verified internal report hash back to the signed result payload.

The study CDR manifest uses the existing `collabio-pixel-cdr:raw-rgb.v1` profile and 144 DPI, but is tenant-free and
synthetic-only. It has separate source-reference and round-trip-candidate stages. The reference is a same-engine source
render, so the measurement captures round-trip drift without confusing cross-engine rasterizer differences with edit
fidelity. Production `PreviewCdrBundleManifest` remains unchanged.

Open XML validation uses `DocumentFormat.OpenXml`, records exact validator and target-format versions and enables Markup
Compatibility processing. Finding records contain error identity, type, part URI and a path hash, never document text.
Schema conformance is an observed axis. A non-conformant result can still be byte-verified and retained as a failed
study observation; it cannot pass later acceptance.

Font reports never include font names or host paths. Word uses a normalized Windows font inventory, LibreOffice uses a
normalized `fontconfig` inventory and GenOffice uses the admitted worker-image font manifest. The report binds engine
identity and executor environment.

The verification report may set `referenced_evidence_content_verified=true`, but always keeps visual thresholds,
human review, compatibility claim and Quick Edit completion false. Actual engine execution remains blocked until its
runner-specific authorization exists. No evidence bundle is fabricated to prove current readiness.

Two separate no-network Compose controls are used. The schema control has only a write-once output mount. The verifier
has read-only evidence and public-input mounts plus one write-once output mount. Both have read-only roots, dropped
capabilities, no-new-privileges and bounded resources. Neither mounts an Office engine, source object store, tenant
credential, Docker socket or external network.

## Consequences

- A signed runner result cannot satisfy the study with missing, changed or internally inconsistent evidence files.
- Preflight, package structure and visual measurements are independently reproducible from retained bytes.
- Runner attestations remain necessary for operations the verifier cannot reproduce, including actual engine identity,
  authorization and Open XML SDK execution.
- Public schemas and verified metadata reports are durable Office recovery evidence; transient RGB remains excluded.
- Compatibility, Quick Edit completion, tenant processing and production use remain closed.

## References

- [Microsoft Open XML document validation](https://learn.microsoft.com/en-us/office/open-xml/word/how-to-validate-a-word-processing-document)
- [Microsoft Open XML markup compatibility](https://learn.microsoft.com/en-us/office/open-xml/general/introduction-to-markup-compatibility)
- [ECMA-376 Office Open XML](https://ecma-international.org/publications-and-standards/standards/ecma-376/)
- [LibreOffice command-line parameters](https://help.libreoffice.org/latest/en-GB/text/shared/guide/start_parameters.html)
