# Source Object Preview Conversion

Status: implemented conversion engine and fail-closed lifecycle; production dispatch remains disabled until deployment
evidence is admitted.

## Security Architecture

Preview conversion is split into three trust zones:

1. The trusted control plane resolves authoritative metadata through `get_metadata()`, performs ACL checks, verifies the
   renderer release gate, and binds a source-specific malware/CDR preflight to an immutable command.
2. A credential-less one-shot worker receives only `request.json` and one source file. It has no database or object-store
   configuration, no network, a read-only root filesystem, dropped capabilities, `no-new-privileges`, resource limits,
   and an ephemeral LibreOffice profile.
3. The trusted importer reads the candidate PDF and worker result, revalidates the content hash, PDF framing, size,
   page count, and raw active-content indicators, then verifies the hash-bound QPDF object-inspection result, gate,
   preflight, image digest, font baseline, and exact source version before it writes a derived SourceObject and
   append-only lineage receipt.

LibreOffice never receives PostgreSQL, S3, KMS, viewer, or tenant credentials. Production execution accepts only an
image reference containing `@sha256:...` and an attested `runsc`, Kata, or Firecracker runtime. Default `runc`, image
tags, stale evidence, missing controls, tenant drift, ACL drift, source-version drift, and output drift fail closed.

## Contracts

- `source_object_preview_conversion_execution_gate.v1` binds the worker digest, stronger sandbox, no-egress policy,
  resource limits, scanner/CDR profiles, QPDF/PDFInfo profile, font baseline, restore evidence, HTTPS viewer origin, and
  CSP evidence.
- `source_object_preview_conversion_source_preflight.v1` binds scanner signatures and CDR disposition to the exact
  tenant, SourceObject, version, manifest hash, and content hash.
- `source_object_preview_conversion_command.v1` contains metadata and hashes only. It has fixed basenames and no source
  bytes, reason text, credentials, or arbitrary command arguments.
- `source_object_preview_conversion_result.v1` contains output hash, byte length, page count, versions, and validation
  booleans. It excludes source bytes, PDF bytes, stdout, and stderr.
- `source_object_derived_preview_receipt.v1` binds the source version to the derived PDF SourceObject and proves that
  classification, ACL, KMS reference, retention, legal hold, and lifecycle were inherited.

## Derived Preview Lifecycle

The PDF is persisted through the normal SourceObject repository and object-storage bridge as an `attachment` with the
authoritative source object as parent. It therefore receives an immutable content hash, SourceObject manifest, write
receipt, storage manifest, versioned object-store entry, retention manifest, encryption mapping, backup coverage, and
restore verification. The separate derived-preview receipt adds exact source-version and conversion-evidence lineage.

Viewer authorization must always re-check the authoritative source ACL. A copied ACL hash on the derived object is an
integrity binding, not permission to bypass the parent check. Regeneration creates a new deterministic derived version;
it never overwrites an existing object version.

## Docker Profiles

`docker compose run --rm preview-conversion-engine-smoke` performs a development-only synthetic RTF conversion with
networking disabled. It validates the installed LibreOffice, QPDF, PDFInfo, and font stack but deliberately does not
claim production execution-gate readiness.

QPDF validation includes an object-level JSON inspection with stream data disabled. Canonicalized action names for
JavaScript, Launch, OpenAction, embedded files, RichMedia, remote navigation, form submission, and URI actions are
rejected even when the original PDF encoded a name to evade raw byte matching. The QPDF JSON stays in the ephemeral
workspace, has a hard size limit, is never logged, and is removed with the job. A raw-token scan remains as a second
layer.

`docker compose --profile preview-execution run --rm preview-conversion-worker` is the production-shaped one-shot
contract. It defaults to `runsc`, reads a staged request and source from the read-only input volume, writes only to the
output volume, and refuses unpinned or mismatched runtime evidence. A trusted stager and importer own those volumes;
the worker owns no durable queue, database connection, storage SDK, or Docker socket.

## Backup And Recovery

Execution-gate evidence and derived-preview receipts are tenant-scoped append-only PostgreSQL records with forced RLS.
The PDF uses the existing SourceObject and S3-compatible backup/restore path. Recovery order is:

1. Restore PostgreSQL metadata, gate evidence, SourceObject write receipts, and derived-preview receipts.
2. Restore versioned object storage and verify storage, retention, legal-hold, manifest, and content hashes.
3. Reconcile every derived receipt to its exact source and derived SourceObject versions.
4. Keep dispatch and viewer access blocked until a fresh execution gate and a successful restore reconciliation exist.
5. Rebuild only previews whose source version still exists and whose tenant policy permits regeneration.

## Remaining Production Admission

The code and real conversion engine are present, but productive dispatch remains intentionally closed until dev001 or
the later orchestrator supplies independently verifiable runsc/Kata/Firecracker evidence, a current malware signature
set and CDR service, a published worker image digest with provenance/SBOM, a derived-preview restore drill, and the
separate-origin PDF.js viewer CSP evidence. These are deployment facts and must not be simulated by application flags.
