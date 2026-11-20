# ADR-0072: GenOffice DOCX Fidelity Study Control Plane

- Status: Accepted
- Date: 2026-08-13
- Scope: Office Quick Edit evaluation only
- Supersedes: none
- Extends: ADR-0060, ADR-0061, ADR-0070, ADR-0071

## Context

ADR-0071 established a hostile-OOXML preflight and three deterministic fidelity fixtures without executing an Office
engine. The next useful step is to define how real Microsoft Word, LibreOffice and GenOffice outputs will be collected
and compared once their separate execution prerequisites exist. A loose collection of screenshots or one-engine
round trips would not support a compatibility decision.

Microsoft explicitly does not recommend or support unattended server-side Office automation. Office applications
assume an interactive desktop and user profile and can block or become unstable in non-interactive execution. Word is
therefore not a Linux service dependency and must be exercised by a separately controlled interactive Windows client.
LibreOffice documents supported headless and conversion command-line modes, so its runner may be an isolated,
no-network headless worker. GenOffice remains behind ADR-0070's real two-person authorization and a newly attested
executable `runsc-kvm` worker.

OOXML schema validity, markup-compatibility processing, semantic package preservation and rendered layout are distinct
properties. ECMA-376 and Open XML SDK validation can identify package and schema errors, but do not prove that an
application preserved layout or semantics. Pixel differences can be measured reproducibly, but no acceptance threshold
is defensible before real samples are calibrated and reviewed.

## Decision

Collabio introduces `genoffice_docx_fidelity_study_policy.v1` and an exact three-by-three study plan. The engines are
Microsoft Word, LibreOffice and GenOffice. Each receives the same three ADR-0071 fixtures for formatting/tables,
headers/comments/footnotes and unknown-markup passthrough. Every assignment binds the source bytes, runner mode,
policy, preflight policy and corpus manifest by SHA-256.

Runner boundaries are explicit:

- Microsoft Word runs only in an interactive Windows user session. Unattended or server-side Word automation is denied.
- LibreOffice may run headless only in an isolated, no-network worker with exact version and font-baseline evidence.
- GenOffice may run only in a newly attested executable `runsc-kvm` harness after valid two-person runtime authorization.

All runners use synthetic content, no tenant credentials and no external network. They must produce an exact engine and
environment identity, output DOCX hash, source-blind output-preflight and structural-fingerprint hashes, Open XML SDK
validation report hash, CDR and font-baseline hashes, page count, visual-comparison manifest hash and execution receipt.
The result body is metadata-only.

Each runner has one distinct active Ed25519 identity. A signed result is accepted into the matrix only when its policy,
plan, assignment, engine, fixture, source bytes and runner mode match exactly. The canonical result payload is signed;
private keys are never accepted or stored by Collabio. A matrix intake requires all nine ordered assignments and nine
distinct envelopes. It verifies signatures and hash references, not the referenced artifact bytes.

The baseline control performs bounded in-memory ZIP/XML inspection only after ADR-0071 preflight. It records hashes of
part names, content types and relationships plus fixed semantic-feature counters. It stores no document text and does
not extract an archive. Visual comparison consumes fixed-size raw RGB pages from the existing
`collabio-pixel-cdr:raw-rgb.v1` boundary at 144 DPI and records exact integer metrics. It cannot accept or reject layout.

The study remains fail closed even after nine signed result envelopes. Compatibility and Quick Edit completion require:

- validation of every referenced evidence artifact and Open XML report;
- CDR-linked visual pages and an exact font baseline for every runner;
- thresholds calibrated from real cross-engine results rather than selected in advance;
- recorded human fidelity review;
- ADR-0070 authorization and executable-harness evidence for the GenOffice assignments.

The current bundle contains policy, study plan, three structural baselines and a readiness report. It executes no engine,
contains no engine output and records all ten blockers. The Compose control has no network, no GenOffice image or source
mount, a read-only root, dropped capabilities, bounded resources and one private write-once output mount.

## Consequences

- The eventual comparison is reproducible and cannot silently substitute engines, fixtures, fonts or runner identities.
- Word is kept out of the server architecture while still remaining an authoritative interoperability reference.
- A signed matrix cannot be misrepresented as validated fidelity or production readiness.
- The structural and RGB contracts can be tested before the external runners are available.
- Study policy, plan, baselines, signed public results and verification reports become Office recovery evidence.
- Tenant content, Quick Edit writes, production use and compatibility claims remain prohibited.

## References

- [Microsoft considerations for server-side Office automation](https://support.microsoft.com/lt-lt/visio/considerations-for-server-side-automation-of-office)
- [LibreOffice command-line parameters](https://help.libreoffice.org/latest/en-GB/text/shared/guide/start_parameters.html)
- [LibreOffice conversion filters](https://help.libreoffice.org/latest/ast/text/shared/guide/convertfilters.html)
- [Microsoft Open XML markup compatibility](https://learn.microsoft.com/en-us/office/open-xml/general/introduction-to-markup-compatibility)
- [Microsoft Open XML document validation](https://learn.microsoft.com/en-us/office/open-xml/word/how-to-validate-a-word-processing-document)
- [ECMA-376 Office Open XML](https://ecma-international.org/publications-and-standards/standards/ecma-376/)
- [Pinned GenOffice source](https://github.com/genspark-ai/genoffice/commit/fd33934dab1fdf8666af3f88b9794e7b4e19474a)
