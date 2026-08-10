# ADR-0063: GenOffice Pre-Build Supply-Chain Admission

Status: accepted
Date: 2026-08-10

## Context

ADR-0062 binds the exact GenOffice source archive and 21-package npm runtime closure but intentionally does not create
an SBOM or vulnerability decision. The selected runtime source also vendors an EMF converter. Treating that code as an
anonymous file would leave both provenance and vulnerability coverage incomplete.

Source-manifest scanning alone is insufficient. Networked database acquisition and scanning untrusted dependency
metadata in the same process would also make the evidence harder to reproduce and audit. A future worker image will
need its own authoritative runtime inventory, so the source-stage evidence must identify itself as pre-build.

## Decision

- Bind the vendored files to `emf-converter@2.0.2` from the npm registry. Pin its SHA-256 and published SHA-512 SRI,
  reject unsafe archive members, and compare the used license, MJS runtime, and declaration bytes without extraction
  or execution.
- Generate a deterministic CycloneDX 1.6 pre-build SBOM from the admitted source report and vendored provenance
  report. It contains the DOCX engine, 21 locked dependencies, and `emf-converter@2.0.2` as 23 exact npm PURLs.
- Validate the SBOM in a no-network container using CycloneDX CLI 0.32.0 pinned by image digest.
- Give network access only to a short-lived Trivy DB updater. Run Trivy 0.73.0 in a separate no-network container with
  update checks, telemetry, remote lookups, and VEX downloads disabled and the DB cache mounted read-only.
- Admit the automated result only when schema receipt, scanner identity, exact PURL inventory, DB freshness, and the
  no-HIGH/no-CRITICAL policy all pass.
- Keep npm registry signature/SLSA verification, human legal review, reproducible worker build, runtime-image SBOM,
  source import, engine execution, and production use false.

## Evidence

The accepted run proves byte provenance report
`sha256:5ac1fdfa83034db3a8da06985b5f96e87a8eb0acfe3614f05b4fb3afe8e3dd04`, CycloneDX SBOM
`sha256:c5e8678efe9b0dc3f8e64a978eacfe43fd9fae6a9e63c8bb74d94b0c1a8b43f0`, exact `23/23` scanner
coverage, zero vulnerability findings, and admission report
`sha256:580bd646106d79b712d42ecef490a8165435525a1feaeb52c10999274584767f`.

## Consequences

- Vendored runtime code can no longer disappear from dependency and vulnerability evidence.
- Re-running the pre-build inventory is deterministic; time-varying DB and scan evidence remains separately hashed.
- A green automated gate is not legal approval and cannot enable source import or execution.
- The eventual worker build must generate and pass a separate image-derived SBOM and signed provenance.

## References

- https://cyclonedx.org/schema/bom-1.6.schema.json
- https://cyclonedx.org/guides/sbom/lifecycle_phases
- https://github.com/CycloneDX/cyclonedx-cli
- https://trivy.dev/docs/latest/guide/target/sbom/
- https://trivy.dev/docs/latest/configuration/db/
- https://trivy.dev/docs/latest/guide/advanced/air-gap/
- https://www.npmjs.com/package/emf-converter/v/2.0.2
