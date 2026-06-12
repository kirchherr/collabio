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
- RAG-compatible source resolver.
- SourceDocument bridge for existing demo and parser flows.
- Compliance validations for required references, parent objects, mail MIME type, content length, UTC timestamps, and legal-hold lifecycle blocking.

Not implemented yet:

- PostgreSQL-backed source metadata tables.

Note: `PgKnowledgeBaseArticleRepository` persists Knowledge Base article/version metadata and source-version/restore evidence transactionally, but it does not replace the shared source-object metadata/content store. Source object PostgreSQL metadata and object-storage durability remain separate adapter work.
- Concrete S3/MinIO-compatible content-store implementation.
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
