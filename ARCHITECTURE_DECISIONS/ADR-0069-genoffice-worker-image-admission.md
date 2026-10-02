# ADR-0069: GenOffice Worker Image Admission

Status: accepted
Date: 2026-08-12

## Context

ADR-0067 and ADR-0068 allow a tightly bounded development build context after a real external authorization. That
authorization is insufficient for worker execution: a container image adds base operating-system packages, an
installation result, image layers and a new supply-chain artifact that must be reproducible, inventoried, scanned and
independently attested.

The current organization has one accountable founder. Its compensating control may authorize evidence-producing
development, but it must not be reinterpreted as the two-person runtime approval required by ADR-0066.

## Decision

- Build only from the authorized deterministic context and reviewed dependency archives, with no build network,
  ignored lifecycle scripts, pinned build and runtime base image digests, and `SOURCE_DATE_EPOCH=0`.
- Use a reduced Alpine runtime image. Remove package managers and normalize runtime-tree metadata before export.
- Require two independent no-cache builds from identical inputs. Admit evidence only when image configuration, rootfs
  layers, labels, platform, runtime inventory and normalized inputs are identical.
- Save the candidate as an OCI/Docker archive and bind the exact archive bytes to the expected image configuration.
- Generate an authoritative CycloneDX 1.6 runtime-image SBOM from the saved archive. Bind it to the pre-build SBOM,
  source admission and build evidence, then validate it with a digest-pinned CycloneDX validator.
- Run a complete offline vulnerability scan against a fresh, independently updated Trivy database. Record database
  metadata, report hash, all findings and severity counts in the attestation payload.
- Require a detached Ed25519 signature created outside Collabio over the canonical worker-build payload. Suite services
  ingest only the public key and strict signature response; private-key ingestion and signature creation are forbidden.
- Make the final report explicitly non-runtime: `worker_execution_allowed`, `source_import_allowed`,
  `tenant_content_allowed`, `hosted_service_allowed`, `on_prem_distribution_allowed` and `production_use_allowed`
  remain false. A successful report means only that a development-spike image is available for the next controlled
  boundary.
- Keep the image entry point fail closed and status-only until a separate two-person runtime authorization, sandbox,
  fidelity proof, recovery proof and deployment admission have all passed.

## Consequences

- A byte-identifiable and externally attested development image can be evaluated without opening document processing.
- Rebuilding after any source, dependency, base-image, Dockerfile, authorization, scanner-database or policy change
  creates a new generation and a new signature request. Existing generations remain immutable audit evidence.
- Zero findings are time-bound evidence, not a permanent safety claim. Admission expires with its signed validity
  window and does not waive future scanning or dependency review.
- The next Office step can focus on a sandboxed, synthetic-input fidelity spike while tenant content and import remain
  technically unavailable.

## Recovery Contract

Back up the public signer policy and key, exception report, materialized build context, reviewed dependency archives,
both image inspect records, saved image archive, build evidence, raw and normalized SBOMs, schema-validation receipt,
Trivy database metadata, vulnerability report, canonical signing request/message, public signature response, final
admission report and all four committed schemas. Restore verification recalculates every hash, verifies the detached
signature and confirms all runtime flags remain false. The private signing key is never part of Collabio backup or
failover state.

## References

- `docs/operations/GENOFFICE_WORKER_IMAGE_ADMISSION.md`
- `docs/operations/backup_failover_policy.json`
- `app/suite/operations/genoffice_worker_image_admission.py`
- `docker/genoffice-worker/Dockerfile`
