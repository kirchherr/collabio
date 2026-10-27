# ADR-0067: Deterministic GenOffice Development Build Context

Status: accepted
Date: 2026-08-11

## Context

ADR-0066 permits exact build-context materialization after the preferred two-person internal OSS admission succeeds.
ADR-0068 adds a narrow, expiring solo-founder compensating control for organizations that cannot yet perform honest
personnel separation. Copying
the complete upstream repository or extracting it into a long-lived checkout would weaken the reviewed source boundary,
make prohibited scopes easier to include accidentally, and create an ambiguous recovery artifact. Starting npm or a
compiler during materialization would also combine source selection with execution before the worker-build gate exists.

The later image build must record all top-level inputs, run without network access, normalize timestamps and generate
authoritative image-derived SBOM and provenance. SLSA provenance treats source, build configuration and resolved
dependencies as materials. BuildKit supports network-disabled builds and `SOURCE_DATE_EPOCH` for reproducible image and
layer metadata. CycloneDX distinguishes the current pre-build inventory from the required build/post-build inventory.

## Decision

- Introduce `genoffice_development_build_context_report.v2`, its v2 embedded manifest and a deterministic uncompressed
  TAR context.
- Require the pinned source admission, automated pre-build SBOM/vulnerability admission, npm cryptographic provenance,
  exactly one explicit development authorization and exact third-party NOTICE before reading selected source bytes.
- Accept either the ADR-0066 two-person admission or an active ADR-0068 solo-founder exception. Reject missing, mixed,
  future or expired authorization evidence.
- Reopen the pinned source archive without extraction, reject non-canonical paths, duplicates, links and special files,
  and verify every selected file against its admitted path, size and SHA-256.
- Materialize exactly the 93 admitted files, `THIRD_PARTY_NOTICES.txt` and a Collabio context manifest. Never include
  `ee/**`, shell, cloud-AI or any other unselected upstream path.
- Quarantine the root `package.json` and `package-lock.json` under `.collabio/upstream/`. Their original paths and bytes
  remain evidence-bound, but the known root `postinstall` hook cannot become an implicit active build entry point.
- Normalize all TAR entries to UID/GID 0, empty owner names, mode `0644`, sorted paths and the configured non-negative
  `SOURCE_DATE_EPOCH`.
- Keep dependency installation, worker-image creation, engine execution, source import, tenant content and production
  false. The context authorizes only a later isolated worker-image build.
- Run the materializer as a no-network, read-only, non-root Compose service with the archive and evidence mounted
  read-only and a dedicated output mount.
- Do not create a real context before either the two named signers produce a valid internal OSS admission or the named
  founder produces a valid, signed, maximum-30-day exception. Neither path authorizes runtime.

## Consequences

- The future builder receives one exact, portable and independently hash-verifiable input instead of a mutable source
  directory.
- Context bytes can be rebuilt and compared before any package manager or compiler is allowed to run.
- A source, NOTICE, policy, decision, vulnerability or provenance change invalidates the context automatically.
- A successful context report is not an image SBOM, build provenance, fidelity result or runtime authorization.
- The later hermetic build still needs exact offline dependency artifacts, a digest-pinned builder image, cache-isolation
  policy, two-build reproducibility evidence, image-derived CycloneDX SBOM, vulnerability review and signed provenance.

## Recovery Contract

Retain the context TAR and report together with every referenced input. Restore verification recalculates the report,
context, embedded manifest, source archive and NOTICE hashes before reuse. Signing keys, package-manager caches and
scratch directories are not context or backup payloads.

## References

- https://slsa.dev/spec/v1.2/build-provenance
- https://slsa.dev/spec/v1.2/build-requirements
- https://docs.docker.com/build/ci/github-actions/reproducible-builds/
- https://docs.docker.com/reference/compose-file/build/
- https://cyclonedx.org/guides/sbom/lifecycle_phases/
