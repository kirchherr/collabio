# ADR-0074: GenOffice DOCX LibreOffice Synthetic Runner

- Status: Accepted
- Date: 2026-08-13
- Scope: Synthetic Office Quick Edit fidelity evidence only
- Supersedes: none
- Extends: ADR-0070, ADR-0071, ADR-0072, ADR-0073

## Context

ADR-0072 defines a three-engine by three-fixture fidelity study, while ADR-0073 verifies the bytes referenced by one
signed engine result. Neither decision authorizes an Office engine or defines how a LibreOffice result is produced.
The first executable path must preserve the synthetic-only boundary, run in the verified `runsc-kvm` sandbox and
produce evidence that the independent verifier can consume without giving the worker a signing key.

## Decision

Collabio adds a content-addressed, one-shot LibreOffice runner. A separate no-network control container materializes an
exact assignment containing a canonical run request, study plan, corpus manifest and exactly one synthetic DOCX. The
request is valid for at most four hours and binds the fixture bytes, policy, plan, corpus and immutable runner image.
Tenant content, credentials, persistent product writes, external effects and private keys are explicitly forbidden.

The runtime image pins LibreOffice Writer, Poppler, fontconfig, DejaVu, Liberation fonts and the .NET 8 runtime to exact
Alpine package versions. A separately built .NET 8 validator restores `DocumentFormat.OpenXml` 3.5.1 in locked mode and
validates against Office 2021 with Markup Compatibility processing enabled. Validation output contains only error ID,
type, part URI and a path hash; it never contains source text or SDK error descriptions.

The runner performs, in order:

1. Assignment inventory, hash, expiry and synthetic-only validation.
2. Source preflight using the ADR-0071 bounded no-extraction parser.
3. LibreOffice DOCX round-trip using `Office Open XML Text` and a fresh private user profile.
4. Output preflight and structural OOXML fingerprinting.
5. Open XML SDK validation.
6. Same-engine source and candidate PDF rendering with `writer_pdf_Export`.
7. Raw RGB rasterization at 144 DPI and deterministic integer comparison.
8. Write-once evidence receipt, unsigned result payload and canonical signature-message handoff.

Compose runs the worker with `network_mode: none`, a read-only root, all capabilities dropped, no-new-privileges,
bounded CPU/memory/PIDs, private `tmpfs`, no Docker socket and the verified `runsc-kvm` runtime. The explicit
`SUITE_RUNTIME_UID` and GID preserve private `0600` handoff files across the host/container boundary; effective UID and
GID are included in the executor-environment hash. The input bind is read-only and the empty output bind is the only
persistent writable path.

The worker never signs its result. An external engine signer must sign the canonical handoff, and ADR-0073 must then
verify the retained evidence bytes. Successful execution alone cannot set compatibility, threshold calibration, human
review or Quick Edit completion to true.

## First Synthetic Baseline

The first `dev001` generation used image
`sha256:0d0f6adac9b18f07a213f85f116690051c9b6d38d0be10e9bafea36d636715ab` under `runsc-kvm`. All three fixtures produced
one 1224 by 1584 page and exact same-engine source/candidate pixel equality. The Open XML SDK reported 7 findings for
`formatting-table-fidelity` and 6 findings for each other fixture, primarily schema datatype findings in
`/word/fontTable.xml`. These are retained failed schema-conformance observations, not suppressed or converted into a
compatibility claim. All three outputs remain unsigned and independently unverified.

## Consequences

- LibreOffice execution is now real, reproducible, synthetic-only and separated from signing and verification.
- The OpenXML validator is the Microsoft SDK implementation rather than a Python approximation.
- Known LibreOffice output-schema findings become a measured baseline for later fixture and export-policy work.
- Tenant documents, product saves, cross-engine acceptance, calibrated thresholds and production dispatch remain
  closed.
- Evidence bundles and public schemas are recoverable records; profiles, temporary PDFs and transient RGB buffers are
  excluded from backup.

## References

- [LibreOffice command-line parameters](https://help.libreoffice.org/latest/en-US/text/shared/guide/start_parameters.html)
- [LibreOffice conversion filters](https://help.libreoffice.org/latest/en-US/text/shared/guide/convertfilters.html)
- [Microsoft Open XML validation](https://learn.microsoft.com/en-us/office/open-xml/word/how-to-validate-a-word-processing-document)
- [Microsoft Open XML markup compatibility](https://learn.microsoft.com/en-us/office/open-xml/general/introduction-to-markup-compatibility)
- [DocumentFormat.OpenXml 3.5.1](https://www.nuget.org/packages/DocumentFormat.OpenXml/3.5.1)
