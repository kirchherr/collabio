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

## Evidence And Retention

Retain the following together in the immutable supply-chain artifact store:

- exact source archive and SHA-256;
- `genoffice_docx_source_admission_report.v1` and its report hash;
- selected-source and runtime-dependency manifest hashes;
- subsequent legal decision, CycloneDX SBOM, vulnerability decision, build digest, and signed provenance.

The report contains no tenant data or Office document content. It is nevertheless release evidence and must be
available for rebuild, audit, rollback, and disaster recovery. Never place source archives or dependency tarballs in
normal application logs.

## Still Blocked

- final legal, NOTICE, trademark, compound-license, and vendored-code provenance approval;
- CycloneDX SBOM and vulnerability review of the exact runtime closure;
- reproducible, signed, isolated worker build;
- malicious OOXML/archive and cross-engine fidelity corpora;
- resource-limited no-egress engine execution;
- candidate revalidation, canonical preview, fresh ACL checks, human confirmation, and append-only edit receipt;
- non-empty backup, restore, reconciliation, and failover drill for durable editing state.
