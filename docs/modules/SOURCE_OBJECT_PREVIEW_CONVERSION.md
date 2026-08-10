# Source Object Preview Conversion

Status: implemented conversion engine and fail-closed lifecycle; production dispatch remains disabled until deployment
evidence is admitted.
A real Collabio-owned ClamAV adapter now feeds the development proof; CDR and signed production evidence remain open.

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
- `source_object_preview_conversion_command.v2` adds the optional Production-Admission-Gate binding to the metadata-
  and hash-only command. Historical `v1` records remain verifiable only in their exact pre-admission field shape.
- `source_object_preview_conversion_result.v2` carries the same optional binding through the worker result. Historical
  `v1` records remain readable without weakening current `v2` hash validation.
- `source_object_preview_conversion_job_evidence.v1` binds the versioned command and result plus lineage hashes in an
  append-only PostgreSQL/RLS ledger without source or output bytes.
Commands retain fixed basenames and contain no source bytes, reason text, credentials, or arbitrary command arguments.
Results retain output hash, byte length, page count, versions, and validation flags, but exclude source bytes, PDF
bytes, stdout, and stderr.
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

Every completed conversion also persists metadata-only job evidence containing the validated command, preflight, and
worker result. The evidence links their hashes to the SourceObject write receipt and derived-preview lineage receipt in
the same PostgreSQL transaction. It contains neither input nor output bytes and is protected by forced RLS.

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

The `preview-proof` profile is the controlled non-empty development proof. Its first service runs the real conversion
engine inside the configured `runsc` runtime, without network or credentials, and writes a metadata-only hash-bound
self-test report. The trusted stager cannot start before that service succeeds. Only then does it atomically persist a
synthetic source receipt, SourceObject, and execution gate for the dedicated `tenant-preview-proof` tenant and stage
the source into a transient volume. A second credential-less, offline `runsc` worker creates the PDF. The trusted
importer independently revalidates and atomically persists the derived SourceObject, write receipt, lineage receipt,
and conversion-job evidence before both transient volumes are cleared.

A missing or unregistered `runsc` runtime therefore fails before PostgreSQL or object-storage writes. Runtime evidence
cannot be supplied through a free-form environment hash. The proof reports contain hashes and counts only, remain
development-only, and explicitly prohibit production admission, conversion dispatch, and preview serving. The exact
execution and recovery sequence is maintained in `docs/operations/BACKUP_FAILOVER.md`.

## Backup And Recovery

Execution-gate evidence and derived-preview receipts are tenant-scoped append-only PostgreSQL records with forced RLS.
The PDF uses the existing SourceObject and S3-compatible backup/restore path. Recovery order is:

1. Restore PostgreSQL metadata, gate evidence, SourceObject write receipts, and derived-preview receipts.
2. Restore versioned object storage and verify storage, retention, legal-hold, manifest, and content hashes.
3. Reconcile every derived receipt to its exact source and derived SourceObject versions.
4. Keep dispatch and viewer access blocked until a fresh execution gate and a successful restore reconciliation exist.
5. Rebuild only previews whose source version still exists and whose tenant policy permits regeneration.

`docker compose --profile restore-drill run --rm derived-preview-recovery-drill` reconciles the restored PostgreSQL
records with the restored exact object versions. It verifies source and derived manifests, PDF bytes, write receipts,
execution gates, command/preflight/result hashes, timestamps, inherited ACL/classification/KMS/retention/Legal-Hold
controls, and one-to-one receipt bindings. Its report is metadata-only and never enables dispatch or content serving.

## Remaining Production Admission

The first real external input is implemented: `preview-malware-scanner` uses the official digest-pinned ClamAV 1.5
image, an internal-only Compose network, bounded `INSTREAM`, metadata-only evidence, and a fresh Clean/EICAR smoke.
The controlled proof stager scans the exact source bytes and binds both scan and smoke hashes before writing the
conversion command. This proves the adapter and fail-closed disposition, but it does not claim CDR, signed signature
database provenance, production HA, or production network-policy evidence. Operational details are in
`docs/operations/PREVIEW_MALWARE_SCANNER.md`.

The code and real conversion engine are present, but productive dispatch remains intentionally closed until dev001 or
the later orchestrator supplies independently verifiable runsc/Kata/Firecracker evidence, a current malware signature
set and CDR service, a published worker image digest with provenance/SBOM, a successful non-empty derived-preview
recovery report, and the separate-origin PDF.js viewer CSP evidence. These are deployment facts and must not be
simulated by application flags.
