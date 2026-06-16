# Source Object Model

Source objects are the common storage and indexing boundary for office, mail, attachments, comments, wiki content, and procedure documentation.

The rule: no durable object enters storage, parser workers, search, vector indexing, RAG, export, or e-discovery without authoritative metadata.

## Required Metadata

Every source object version carries:

- `tenant_id`
- `object_id`
- `object_type`
- `version_id`
- `title`
- `owner_principal_id`
- `created_by`
- `created_at_utc`
- `updated_at_utc`
- `classification`
- `retention_policy_id`
- `legal_hold_state`
- `kms_key_ref`
- `manifest_hash`
- `audit_chain_ref`
- `source_system`
- `schema_version`
- `mime_type`
- `acl_hash`
- `acl_version`
- `content_hash`
- `content_byte_length`
- `lifecycle_state`

Attachments and comments must also carry `parent_object_id`. Mail objects use `message/rfc822` and may carry `thread_id`.

## Supported Types

The initial model defines:

```text
document
mail
attachment
comment
wiki
procedure_doc
```

These values are intentionally identical to the source-type metadata used by parser workers, vector chunks, RAG source resolution, audit evidence, and later e-discovery exports.

## Lifecycle

The initial lifecycle states are:

```text
working
saved_version
business_record
worm_evidence
restricted
deleted
cryptoshredded
```

Legal hold is enforced at the model boundary: an object under active hold cannot enter `deleted` or `cryptoshredded`.

This is not the full retention engine yet. It is the minimum invariant that prevents later storage adapters, mail processors, editors, and AI flows from inventing incompatible object semantics.

## Storage Write Guard

Every repository write is checked by `SourceObjectWriteGuard`.

The guard requires:

- `tenant_id`
- `classification`
- `retention_policy_id`
- `kms_key_ref`
- `manifest_hash`
- `content_hash`

It also verifies:

- `kms_key_ref` uses the `kms://` scheme.
- `kms_key_ref` is canonical and matches the source object tenant and data class.
- `content_hash` is canonical and matches the stored text or native bytes through the shared content hash verifier.
- `manifest_hash` matches the canonical source object metadata payload.

This guard is the current shared entry point for storage writes. Future PostgreSQL, S3/MinIO, WORM, and KMS adapters must call the same guard or an equivalent stricter policy before accepting object data.

## Durable Write Receipts

`SourceObjectWriteReceipt` is the first durable persistence boundary for source-object writes.

The receipt stores only:

- tenant, object, version, lifecycle, retention, legal-hold, classification, KMS, ACL, source-system, and MIME metadata
- source manifest hash
- content hash and byte length
- audit-chain reference
- receipt reference
- canonical receipt hash

It does not store object text, article bodies, prompts, outputs, transcripts, embeddings, native bytes, or raw payloads.

`collabio.source_object_write_receipts` is created by `0026_source_object_write_receipts.sql`. The table is tenant-scoped, RLS-protected, append-only by policy, unique per tenant/object/version, and grants no hard delete. It belongs to the `postgres_metadata` continuity domain and is also required evidence for Knowledge Base write execution.

Runtime adapters:

- `InMemorySourceObjectWriteReceiptStore` for tests and local in-memory slices.
- `PgSourceObjectWriteReceiptStore` for durable metadata receipts.
- `SUITE_SOURCE_OBJECT_WRITE_RECEIPT_BACKEND=postgres` enables the PostgreSQL store, using `SUITE_SOURCE_OBJECT_WRITE_RECEIPT_DSN` when set, otherwise `SUITE_DATABASE_DSN`.

## PostgreSQL Metadata And Content Bridge

`0027_source_object_metadata_storage_bridge.sql` adds two metadata-only tables:

- `collabio.source_object_metadata`
- `collabio.source_object_storage_manifests`

They store authoritative source metadata, retention manifest hashes, storage manifest hashes, bucket/object-version references, ACL versions, KMS references, Legal Hold state, and content hashes. They do not store source text, article bodies, native bytes, prompts, outputs, transcripts, embeddings, or raw payloads.

`PgSourceObjectRepository` coordinates:

```text
SourceObjectWriteGuard
  -> RetentionManifest
  -> StorageObjectManifest
  -> SourceObjectContentStore
  -> PostgreSQL source metadata + storage manifest insert
```

The local content-store implementation is `InMemorySourceObjectContentStore`. It is a bridge contract for tests and local development, not production object storage. `S3CompatibleSourceObjectContentStore` is the S3/MinIO-compatible adapter port for production-style object storage. It depends on the `S3CompatibleObjectStoreClient` protocol so concrete MinIO/AWS SDK bindings stay outside feature code, and it checks bucket versioning, Object Lock/WORM capability, and legal-hold support before writes. `Boto3S3CompatibleObjectStoreClient` is the concrete MinIO/AWS-compatible SDK adapter behind that protocol. `s3_compatible_provider_profile_evidence.v1` records bucket capability evidence for all bucket profiles and blocks production wiring when versioning, Object Lock, or legal-hold requirements are not met. `knowledge_base_runtime` activates the Postgres/S3 Knowledge Base path only from explicit runtime configuration and binds provider-profile evidence, content-recovery evidence, restore-drill evidence, and deployment-gate evidence before constructing `PostgresKnowledgeBaseWriteUnitOfWork`.

`source_object_content_recovery_evidence.v1` is the API-wiring gate for production Knowledge Base writes. `PgSourceObjectRepository.build_content_recovery_evidence` compares tenant-scoped content-store inventory with `collabio.source_object_storage_manifests`, verifies manifest-backed content hashes through the content-store read path, records orphaned content reference hashes and missing manifest hashes, binds a restore-drill report hash, and returns `api_wiring_allowed=true` only when there are no orphaned or missing content objects. `SourceObjectContentReconciliationWorker` turns that evidence into a metadata-only recommended action: `ready_for_api_wiring` or `manual_reconciliation_required`. The evidence and worker run never include source bytes.

Content hash verification is documented in:

```text
docs/CONTENT_HASH_VERIFICATION.md
```

The first object-storage adapter plan is documented in:

```text
ARCHITECTURE_DECISIONS/ADR-0024-s3-compatible-object-storage.md
docs/STORAGE_ADAPTER_PLAN.md
docs/storage_adapter_policy.json
```

Retention defaults and manifests are documented in:

```text
ARCHITECTURE_DECISIONS/ADR-0025-retention-defaults-and-manifest.md
docs/RETENTION_MANIFEST.md
docs/retention_manifest_policy.json
```

Legal Hold transitions are documented in:

```text
ARCHITECTURE_DECISIONS/ADR-0026-legal-hold-api-and-reevaluation.md
docs/LEGAL_HOLD_API.md
```

KMS adapter rules are documented in:

```text
docs/KMS_ADAPTER.md
docs/kms_adapter_policy.json
```

## RAG And Parser Boundary

`SourceObjectResolver` converts a versioned source object into the existing `ResolvedSource` shape used by source indexing.

The resolver preserves:

- source object type
- classification
- retention policy
- legal-hold state
- ACL hash and version
- MIME type
- native content bytes when present

Vector indexes remain derived data. They receive metadata and chunks, but not permission authority.

## Current Implementation

Code:

```text
app/suite/storage/source_objects.py
```

Tests:

```text
tests/test_source_objects.py
```

Implemented now:

- Pydantic source object metadata model.
- Versioned source object record wrapper.
- Tenant/version-scoped in-memory repository.
- Storage write guard for required metadata, tenant/data-class matching KMS references, shared content hash verification, and canonical manifest hashes.
- Metadata-only source-object write receipt model with in-memory and PostgreSQL/RLS stores.
- PostgreSQL/RLS source-object metadata and storage-manifest bridge with an explicit content-store interface.
- Content-store recovery evidence with inventory comparison, orphan detection, restore-drill hash binding, and API-wiring gate signal.
- Metadata-only source-object content reconciliation worker with explicit API-wiring recommendation.
- S3/MinIO-compatible content-store adapter port with versioning, Object Lock/WORM, legal-hold, and content-hash checks.
- Concrete MinIO/AWS SDK adapter behind `S3CompatibleObjectStoreClient`.
- S3/MinIO provider-profile evidence and Knowledge Base production write deployment gate.
- RAG-compatible source resolver.
- SourceDocument bridge for existing demo and parser flows.
- Compliance validations for required references, parent objects, mail MIME type, content length, UTC timestamps, and legal-hold lifecycle blocking.

Not implemented yet:

Note: `PgKnowledgeBaseArticleRepository` persists Knowledge Base article/version metadata and source-version/restore evidence transactionally, and Knowledge Base execution now also persists a source-object write receipt before article metadata is committed. `PgSourceObjectRepository` proves the shared source metadata/storage-manifest bridge, and `PostgresKnowledgeBaseWriteUnitOfWork` can bind receipts, source metadata, storage manifests, article metadata, source evidence, and restore evidence in one shared PostgreSQL metadata transaction. Clean content-store recovery evidence, S3/MinIO provider-profile evidence, and bound restore-drill evidence now gate the Postgres UoW for production API wiring through `knowledge_base_production_write_deployment_gate.v1` and `production_write_deployment_gate_evidence_hash`. `knowledge_base_runtime` wires that concrete provider path from explicit configuration.
- Tenant-scoped runtime activation endpoint for the Knowledge Base write path.
- Persistent orphan-reconciliation worker for production object storage.
- Runtime WORM/object-lock bucket bootstrap and provider verification.
- Persistent retention-manifest storage and lifecycle worker.
- Persistent legal-matter and legal-hold scope storage.
- KMS adapter and envelope encryption.
- Full production storage write API.

## Continuity

Source object metadata is owned by the `postgres_metadata` continuity domain.

Native content, manifests, WORM records, attachments, parser artifacts, and export packages are owned by `object_storage_records`.

Any change that adds a new durable source object field must update backup/failover evidence if restore verification changes.

Any future read, restore, parser, or export path that serves stored bytes must verify the content hash before trusting those bytes.
