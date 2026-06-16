# Knowledge Base Source And Restore Evidence

Status: initial
Date: 2026-06-12
Module ID: `knowledge_base`

## Purpose

The Knowledge Base must prove source-version integrity and restore readiness before write/edit workflows, search indexing, embeddings, or RAG are enabled.

This evidence layer is metadata-only. It must not store article bodies, source text, prompts, outputs, transcripts, raw payloads, or model responses.

## Source-Version Evidence

Each `kb.article` current version must resolve to an authoritative source-object record after tenant and object authorization.

Required evidence:

- tenant ID
- article object ID
- article-version object ID
- source object ID
- source version ID
- source object type
- source manifest hash
- source content hash
- ACL version
- data classification
- retention policy
- Legal Hold state
- audit-chain reference
- evidence hash

The source manifest hash, content hash, ACL version, classification, retention policy, and Legal Hold state must match the authoritative source object. Drift blocks the evidence build.

## Restore Evidence

Continuity domain: `knowledge_base_content`

Required restore evidence:

- article row count
- article-version row count
- source-version evidence count
- source-version evidence hashes
- restore drill report hash
- row-count hash
- checksum-manifest hash
- tenant-isolation verification
- disabled-state restore verification
- Legal-Hold restore verification
- audit-chain reference
- restore evidence hash

Restore evidence must cover every returned article version. Missing source evidence blocks the restore evidence build.

## Runtime Boundary

`GET /v1/kb/articles` may return metadata, source-version evidence hashes, and restore evidence hashes only after tenant context, module gate, feature gate, article authorization, and current-version authorization pass.

`GET /v1/admin/kb/evidence` may return source-version evidence records and restore evidence only after tenant context, tenant-admin role validation, and the compliance module gate pass. It is metadata-only and remains available while normal Knowledge Base use is disabled or suspended so retention, Legal Hold, restore, export, and decommission checks can continue.

`POST /v1/admin/kb/articles/write-dry-run` may validate a create/edit approval command and audit its command hash. It is an audit-only dry-run. It must not persist article metadata, source objects, source text, article bodies, embeddings, or RAG index state.

`POST /v1/admin/kb/articles/write-approvals/approve` may transition dry-run evidence to a new append-only `approved_for_write` ledger row only if the current restore evidence still matches. It must not persist article metadata, source objects, source text, article bodies, embeddings, or RAG index state.

`POST /v1/admin/kb/articles/write-approvals/refresh-preview` may project source-version and restore-evidence metadata for approved write evidence. It returns current source-version evidence hashes, projected source-version evidence hashes, and `projected_restore_evidence_preview_hash`. It must not persist source-version evidence, restore evidence, article metadata, source objects, source text, article bodies, embeddings, or RAG index state.

`POST /v1/admin/kb/articles/write-approvals/execution-skeleton` may bind approved write evidence, source-object write-guard decision metadata, refresh-preview hashes, and explicit human confirmation into an `execution_plan_hash`. It must return `execution_allowed=false` and must not persist source-version evidence, restore evidence, article metadata, source objects, source text, article bodies, embeddings, or RAG index state.

`POST /v1/admin/kb/articles/write-approvals/execute` may commit approved edit/create writes after approved evidence, guard decision, refresh preview, execution plan hash, and human confirmation match. Create operations must take article key, title, proposed version label, and source system from trusted approval evidence. The endpoint must commit through `KnowledgeBaseWriteUnitOfWork`, append a metadata-only source-object write receipt, hash-bind receipt-aware source metadata, refresh source-version evidence and restore evidence immediately after the write, return `source_object_write_receipt_hash`, and keep source text out of audit metadata, receipts, and responses. It must not enable embeddings, search indexing, or RAG index state.

Migration `0023_knowledge_base_write_approval_evidence.sql` adds the append-only write-approval ledger. Migration `0024_knowledge_base_write_approval_transition_lineage.sql` adds approval-transition lineage. Migration `0025_knowledge_base_write_approval_trusted_article_metadata.sql` adds trusted article key, title, proposed version label, and source-system metadata to the ledger. Migration `0026_source_object_write_receipts.sql` adds tenant-scoped append-only source-object write receipts. The dry-run path now persists ledger evidence before source-object writes are possible. `KnowledgeBaseSourceObjectWriteGuard` verifies ledger evidence, expected current version for edits, proposed source-version evidence, current restore evidence, retention policy, and Legal Hold state before approved writes. The refresh preview makes the future source/restore evidence update auditable before writes exist. The execution skeleton binds that evidence to human confirmation. Execute refreshes source-version plus restore evidence through `KnowledgeBaseWriteUnitOfWork` after approved edit/create writes and records the source-object write receipt hash. Future PostgreSQL content write paths must keep the article/source/evidence update transactional.

`PgKnowledgeBaseArticleRepository` now makes article/version/source-version/restore evidence updates transactional in PostgreSQL. `PgSourceObjectWriteReceiptStore` makes the source-object write boundary durable before the article metadata transaction is used by API execution. `PgSourceObjectRepository` persists source metadata and storage manifests without content bodies. These adapters exclude source text and article bodies. The next boundary is a coordinated Knowledge Base write unit-of-work plus the production content-store adapter before claiming atomic content persistence.

Future write/edit, search indexing, embedding, RAG, export, and AI-assist work must not bypass this boundary. RAG must still use candidate-only search, authoritative ACL validation, source object IDs, source versions, Local LLM Gateway enforcement, and metadata-only audit.

## Persistence

Migration `0022_knowledge_base_source_restore_evidence.sql` creates:

- `knowledge_base.source_version_evidence`
- `knowledge_base.restore_evidence`

Both tables are tenant-scoped, RLS-protected, append-only by policy, and grant no hard delete.

## Verification

- `tests/test_knowledge_base.py`
- `tests/test_api.py`
- `tests/test_pgvector_migration.py`
- `tests/test_knowledge_base_docs.py`
