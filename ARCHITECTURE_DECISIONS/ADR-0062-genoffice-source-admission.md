# ADR-0062: Reproducible GenOffice DOCX Source Admission

Status: accepted
Date: 2026-08-10

## Context

ADR-0061 selected only `packages/docx-engine/**` for evaluation and kept source import and execution closed. A commit
label and an Apache-2.0 declaration are not enough to admit third-party parser code. The exact source bytes, nested
vendored code, npm runtime closure, registry integrity metadata, lifecycle hooks, prohibited repository scopes, and
remaining legal and supply-chain work must be independently visible before a sandboxed spike can be considered.

The reviewed GenOffice root has an npm `postinstall` hook. Installing the repository root would therefore execute
upstream code during admission. The selected DOCX package currently declares only `fast-xml-parser` and `jszip`, but
the exact npm v3 lock resolves a substantially larger transitive runtime closure. The package also contains a vendored
EMF converter with its own license and attribution material.

## Decision

Pin the GitHub codeload archive for commit `fd33934dab1fdf8666af3f88b9794e7b4e19474a` by SHA-256
`62f4adf92ee3f4b94db2b388a5badc605601c5e56874829e9427c43b95093040`. The machine-readable evaluation policy binds
this digest in addition to the repository and commit.

Introduce `genoffice_docx_source_admission_report.v1`. Its verifier:

- reads the gzip tar archive directly and never extracts it;
- rejects digest drift, a changed archive root, duplicate or non-canonical paths, links, devices, and other special
  files;
- hashes only root evidence and `packages/docx-engine/**` into a deterministic selected-source manifest;
- records but never selects the prohibited `ee/**`, shell, AI-provider, and AI-search trees;
- verifies root, workspace, package, npm lock, direct-dependency, transitive-dependency, registry-integrity, lifecycle,
  and license metadata;
- inventories every vendored source subtree and requires an associated license file;
- records the root lifecycle hook while never invoking npm, Node.js, or upstream code;
- keeps legal approval, SBOM, vulnerability review, reproducible build/provenance, engine execution, source import, and
  production use false.

The verifier runs through the `office-source-admission` Compose profile with no network, a read-only root filesystem,
all capabilities dropped, no-new-privileges, bounded processes/CPU/memory, a read-only archive mount, and a dedicated
evidence output mount. Source acquisition is a separate networked operator action. Admission never downloads content.

No GenOffice source is copied into the Collabio repository, API image, browser bundle, or runtime image by this
decision. The generated report contains paths, sizes, hashes, dependency metadata, and gate state only.

## Self-Review

The codeload digest proves the bytes reviewed by this gate; it does not by itself prove authorship, a signed upstream
commit, or future archive availability. Collabio must retain an immutable internal copy and later bind it to signed
build provenance.

Package-lock license fields are inventory inputs, not legal conclusions. In particular, compound license expressions,
notices, trademarks, and the vendored EMF converter attribution still require human review. The lock is exact for this
upstream commit, but it is not yet Collabio's universal build lock or a CycloneDX SBOM. Vulnerability scanning and a
reproducible isolated build remain separate gates.

Rejecting all links and special files is intentionally stricter than a general Git archive reader. A future upstream
version that legitimately needs a link must receive an explicit policy and verifier change; it may not silently widen
the accepted archive grammar.

## Recovery Contract

The exact archive, digest, selected-source manifest, dependency manifest, admission report, future SBOM, vulnerability
decision, and build provenance are supply-chain recovery artifacts. They must be retained in an immutable artifact
store and restored before rebuilding or promoting the worker. They contain no tenant document data.

The source admission verifier creates no tenant state, draft, candidate version, or editor session. It therefore does
not change current application RPO/RTO. A future content-capable worker must still add non-empty draft/candidate/edit-
receipt recovery and failover evidence before traffic is enabled.

## Consequences

Easier:

- The reviewed third-party byte set and all selected file hashes are reproducible.
- Root install hooks cannot execute during source inventory.
- Direct, transitive, and vendored dependencies are visible before a build exists.
- Prohibited application and enterprise scopes remain outside the selected manifest.

Harder:

- Upstream updates require a new archive digest, report, lock review, and policy version.
- Source acquisition and offline verification are two explicit operator steps.
- The source report cannot be mistaken for legal approval, an SBOM, or production admission.

## Verification

- Unit tests cover deterministic manifests, dependency closure, report tamper detection, digest drift, missing license
  metadata, install-script detection, and hostile tar links.
- Architecture tests reject extraction, process execution, and network clients in the verifier.
- Compose policy tests require no network, read-only operation, capability dropping, and a read-only source mount.
- The exact upstream archive is exercised on `dev001`; its report is retained as metadata-only evidence.

The accepted report contains 1,396 archive members, 93 selected files, 21 runtime dependencies, source manifest
`sha256:27b3ff723354bf3dad848b0f3f781b0c54712fbbb8c1942ceddc346066a4636d`, dependency manifest
`sha256:821aa8dd4d1b647dca34f7f0e8f2daf033ff1cea5b47dd40979ed0d5caffd733`, and report hash
`sha256:7a4eb66cfeefbf6defad574f33b07c904b62c7f076ecb21277e99ae87e2b951d`.

## References

- GenOffice exact commit: https://github.com/genspark-ai/genoffice/tree/fd33934dab1fdf8666af3f88b9794e7b4e19474a
- DOCX package manifest: https://github.com/genspark-ai/genoffice/blob/fd33934dab1fdf8666af3f88b9794e7b4e19474a/packages/docx-engine/package.json
- Root npm manifest: https://github.com/genspark-ai/genoffice/blob/fd33934dab1fdf8666af3f88b9794e7b4e19474a/package.json
- Root license: https://github.com/genspark-ai/genoffice/blob/fd33934dab1fdf8666af3f88b9794e7b4e19474a/LICENSE
- Vendored EMF converter license: https://github.com/genspark-ai/genoffice/blob/fd33934dab1fdf8666af3f88b9794e7b4e19474a/packages/docx-engine/src/vendor/emf-converter/LICENSE
