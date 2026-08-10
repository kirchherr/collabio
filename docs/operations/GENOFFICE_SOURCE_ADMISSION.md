# GenOffice DOCX Source Admission

## Purpose

This gate turns the exact GenOffice DOCX evaluation source into deterministic, metadata-only evidence without
extracting the archive, installing dependencies, or executing upstream code. It closes the source-byte and dependency-
inventory part of ADR-0061. It does not admit an engine build or Office content processing.

## Pinned Input

| Property | Reviewed value |
| --- | --- |
| Repository | `https://github.com/genspark-ai/genoffice` |
| Commit | `fd33934dab1fdf8666af3f88b9794e7b4e19474a` |
| Codeload archive SHA-256 | `62f4adf92ee3f4b94db2b388a5badc605601c5e56874829e9427c43b95093040` |
| Selected package | `packages/docx-engine/**` |
| Root/package license metadata | `Apache-2.0` |
| npm lock format | v3 |
| Direct runtime dependencies | `fast-xml-parser`, `jszip` |

The exact lock currently resolves 21 runtime packages. The root repository declares `postinstall`; the selected DOCX
package does not declare a lifecycle install hook. The verifier records these facts and never runs npm or Node.js.

The checked-in report at `docs/operations/genoffice_docx_source_admission_report.json` was reproduced from the pinned
archive on `dev001`. It records 1,396 archive members, 93 selected evidence/source files (1,605,672 bytes), source
manifest `sha256:27b3ff723354bf3dad848b0f3f781b0c54712fbbb8c1942ceddc346066a4636d`, dependency manifest
`sha256:821aa8dd4d1b647dca34f7f0e8f2daf033ff1cea5b47dd40979ed0d5caffd733`, and report
`sha256:7a4eb66cfeefbf6defad574f33b07c904b62c7f076ecb21277e99ae87e2b951d`.

## Acquisition

Acquisition is intentionally separate from admission and is the only networked step. On `dev001`, use the Collabio
coordination locks and place the immutable archive outside tracked source:

```bash
curl -fsSL \
  https://codeload.github.com/genspark-ai/genoffice/tar.gz/fd33934dab1fdf8666af3f88b9794e7b4e19474a \
  -o backups/upstream/genoffice-fd33934dab1fdf8666af3f88b9794e7b4e19474a.tar.gz
sha256sum backups/upstream/genoffice-fd33934dab1fdf8666af3f88b9794e7b4e19474a.tar.gz
```

Stop if the digest differs. Do not run `npm install`, `npm ci`, package scripts, or binaries from this archive.

## Offline Admission

After acquiring the host locks in the order required by `/home/extern/AGENTS.md`, run:

```bash
docker compose -p collabio --profile office-source-admission run --rm --no-deps \
  genoffice-docx-source-admission
```

The default paths are:

- input: `backups/upstream/genoffice-fd33934dab1fdf8666af3f88b9794e7b4e19474a.tar.gz`;
- output: `backups/genoffice-source-admission/genoffice-docx-source-admission-report.json`.

Override them with `SUITE_GENOFFICE_SOURCE_ARCHIVE_HOST_PATH` and
`SUITE_GENOFFICE_SOURCE_EVIDENCE_HOST_DIR`. Admission has `network_mode: none`; the archive is mounted read-only.

Exit code `0` means only that the exact source snapshot, selected manifest, dependency closure, registry integrity
metadata, license metadata, lifecycle state, and vendored license-file presence were verified. Engine import,
execution, content access, and production use remain false in the report. Exit code `2` is fail-closed.

## Pre-Build Supply Chain

The `office-supply-chain` profile extends source inventory without installing npm packages or executing GenOffice
code. Its trust boundaries are deliberately separate:

1. A networked acquisition step retains the exact `emf-converter@2.0.2` npm metadata and tarball outside tracked
   source. The offline provenance verifier binds the tarball to SHA-256
   `acf0927871d783efe2defe4fdf4e66d09915776570aa81c23781199e58424e9b` and its published SHA-512 SRI, rejects
   unsafe archive members, and proves that the vendored license, `index.mjs`, and `index.d.mts` are byte-identical.
2. The offline generator creates a deterministic CycloneDX 1.6 pre-build SBOM for the DOCX engine, 21 locked npm
   dependencies, and the now versioned vendored package. The accepted SBOM has 23 components and SHA-256
   `c5e8678efe9b0dc3f8e64a978eacfe43fd9fae6a9e63c8bb74d94b0c1a8b43f0`.
3. Digest-pinned CycloneDX CLI 0.32.0 validates the document with no network. Its receipt is bound to the exact SBOM
   hash.
4. Vulnerability database acquisition is confined to `genoffice-trivy-db-update`. Digest-pinned Trivy 0.73.0 then
   scans the SBOM with `network_mode: none`, `--offline-scan`, every update disabled, and a read-only DB cache.
5. The offline admission verifier requires an exact 23-PURL match, a fresh DB, the pinned scanner identity, a valid
   schema receipt, and no HIGH or CRITICAL finding. The 2026-08-10 evidence contains zero findings and passes the
   automated SBOM/vulnerability gate.
6. A separate credential-less service uses digest-pinned Node.js 24.18.0 LTS and npm 11.16.0 to install only the exact
   locked `emf-converter@2.0.2` package with lifecycle scripts disabled. `npm audit signatures --json
   --include-attestations` verifies its ECDSA registry signature, npm publish attestation, SLSA v1 provenance, Fulcio
   chain, and Rekor transparency records. This is the only provenance-verification service with network access.
7. The no-network admission service pins the verifier output and receipt hashes, exact package SHA-512 subject,
   GitHub-hosted source workflow, source commit `9aca5abf16662f93a453a07378768ddd87a8541d`, immutable repository and
   owner IDs, Fulcio certificate SHA-256, and both Rekor inclusion records. Admission report
   `sha256:c85feac5fa9788ef10a4076034d2443c230e8536ee5c02de61b8cfe9ea114aa3` passes while every source-import and
   execution flag remains false.

This is a **pre-build** SBOM. Trivy explicitly treats third-party SBOM input as less authoritative than its own image
analysis. The future isolated worker must therefore produce and pass a separate SBOM and vulnerability scan from the
built image before any execution or import boundary can open.

The npm cryptographic result proves that the reviewed tarball was accepted by npm and is linked to the signed build
identity above. It does not prove that the source is benign, that the package is reproducible from that source, or that
GenOffice is legally or operationally admissible. Those remain separate gates.

## Evidence And Retention

Retain the following together in the immutable supply-chain artifact store:

- exact source archive and SHA-256;
- `genoffice_docx_source_admission_report.v1` and its report hash;
- selected-source and runtime-dependency manifest hashes;
- vendored npm metadata/tarball, byte-provenance report, CycloneDX SBOM, schema receipt, Trivy DB metadata,
  vulnerability report, and `genoffice_docx_supply_chain_admission_report.v1`;
- raw npm signature/Sigstore bundle output, pinned verifier receipt, Fulcio/Rekor identity evidence, and
  `genoffice_npm_provenance_admission_report.v1`;
- subsequent legal decision, build digest, runtime-image SBOM, and signed Collabio worker provenance.

The report contains no tenant data or Office document content. It is nevertheless release evidence and must be
available for rebuild, audit, rollback, and disaster recovery. Never place source archives or dependency tarballs in
normal application logs.

## Still Blocked

- final legal, NOTICE, trademark, and compound-license approval;
- reproducible, signed, isolated worker build with an authoritative runtime-image SBOM and vulnerability decision;
- malicious OOXML/archive and cross-engine fidelity corpora;
- resource-limited no-egress engine execution;
- candidate revalidation, canonical preview, fresh ACL checks, human confirmation, and append-only edit receipt;
- non-empty backup, restore, reconciliation, and failover drill for durable editing state.

## References

- CycloneDX 1.6 JSON schema: https://cyclonedx.org/schema/bom-1.6.schema.json
- CycloneDX lifecycle guidance: https://cyclonedx.org/guides/sbom/lifecycle_phases
- CycloneDX CLI: https://github.com/CycloneDX/cyclonedx-cli
- Trivy SBOM scanning: https://trivy.dev/docs/latest/guide/target/sbom/
- Trivy database management: https://trivy.dev/docs/latest/configuration/db/
- Trivy air-gap guidance: https://trivy.dev/docs/latest/guide/advanced/air-gap/
- emf-converter 2.0.2: https://www.npmjs.com/package/emf-converter/v/2.0.2
- npm audit signatures: https://docs.npmjs.com/cli/v11/commands/npm-audit/
- npm provenance: https://docs.npmjs.com/generating-provenance-statements/
- npm provenance verification design: https://github.com/npm/provenance
- Sigstore certificate OIDs: https://github.com/sigstore/fulcio/blob/main/docs/oid-info.md
