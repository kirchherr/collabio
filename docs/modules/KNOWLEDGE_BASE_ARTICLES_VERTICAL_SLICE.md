# Knowledge Base Articles Vertical Slice

Status: initial
Date: 2026-06-12

This slice proves the reusable module implementation contract outside CRM/ERP. It starts the Knowledge Base with metadata-only article reads, source-version evidence, and restore evidence, not a full wiki and not RAG.

## Scope

- Module: `knowledge_base`
- Feature gate: `knowledge_base.articles.read`
- API: `GET /v1/kb/articles`
- Persistent tables: `knowledge_base.articles`, `knowledge_base.article_versions`, `knowledge_base.source_version_evidence`, `knowledge_base.restore_evidence`
- Object types: `kb.article`, `kb.article_version`
- Classification: `internal`
- Retention policy: `rp-standard`
- Continuity domain: `knowledge_base_content`

## Control Flow

```text
request tenant context
  -> module gate knowledge_base + knowledge_base.articles.read
  -> tenant-scoped article repository
  -> article object authorization
  -> current version object authorization
  -> authoritative source-version resolution
  -> source-version evidence hash generation
  -> restore evidence hash generation for knowledge_base_content
  -> metadata-only response
  -> audit event without prompt, output, source text, article body, or raw payload body
```

## Persistence Contract

`0021_knowledge_base_articles.sql` creates article and article-version tables with:

- tenant RLS and forced RLS
- tenant-scoped primary keys
- required object metadata from `docs/modules/MODULE_IMPLEMENTATION_CONTRACT.md`
- `internal` data classification
- Legal Hold and lifecycle fields
- KMS and audit-chain references
- source version reference metadata
- update timestamp triggers
- no hard-delete policy or grant
- no article body, prompt, output, source text, or raw payload columns

`0022_knowledge_base_source_restore_evidence.sql` creates source-version and restore-evidence tables with:

- tenant RLS and forced RLS
- source object ID and source version ID evidence
- source manifest hash and content hash evidence
- ACL version, classification, retention policy, and Legal Hold state evidence
- row-count, checksum-manifest, disabled-state restore, tenant-isolation restore, and Legal-Hold restore evidence
- no hard-delete policy or grant
- no article body, prompt, output, source text, or raw payload columns

`0023_knowledge_base_write_approval_evidence.sql` creates the append-only write-approval ledger. `0024_knowledge_base_write_approval_transition_lineage.sql` requires non-dry-run approval states to point back to the dry-run evidence that was approved. `0025_knowledge_base_write_approval_trusted_article_metadata.sql` pins trusted create metadata into approval evidence before execution. `0026_source_object_write_receipts.sql` creates the durable metadata-only source-object write receipt boundary. The dry-run endpoint appends metadata-only approval evidence through the ledger port. The approval endpoint appends `approved_for_write` evidence with lineage, but still does not mutate article/source records. `KnowledgeBaseSourceObjectWriteGuard` consumes approved ledger evidence before writes and checks expected version for edits, proposed source-version evidence, restore evidence, retention, Legal Hold, and source-object metadata. The execution skeleton binds approved evidence, source-guard decision, refresh-preview hash, and human confirmation into an audited `execution_plan_hash`. The execute endpoint commits through `KnowledgeBaseWriteUnitOfWork`, persists `source_object_write_receipt_hash`, hash-binds receipt-aware source metadata, and refreshes evidence while keeping RAG and indexing disabled.

## Runtime Contract

The API returns only articles for the current tenant where the current user is authorized for both the `kb.article` and current `kb.article_version` object IDs.

Each returned article includes a `source_version_evidence_hash`. The response includes `source_version_evidence_hashes` and a `restore_evidence_hash`, and the audit event records those hashes as metadata only.

`GET /v1/admin/kb/evidence` exposes the full source-version and restore-evidence metadata to tenant admins through the compliance module gate. It remains available while normal article browsing is disabled, and it does not return article bodies or source text.

`POST /v1/admin/kb/runtime/activate` validates the configured S3-compatible content-store provider, source-content recovery evidence, restore-drill hash, and production deployment gate for the current tenant. It requires explicit human confirmation and persists `knowledge_base_runtime_activation.v1` evidence without source text, article bodies, prompts, outputs, embeddings, or raw payloads.

`POST /v1/admin/kb/articles/write-dry-run` accepts create/edit approval command metadata and produces audit-only dry-run evidence. It does not mutate article rows, source objects, search indexes, embeddings, or RAG state.

`POST /v1/admin/kb/articles/write-approvals/approve` accepts a dry-run evidence hash and a new approval reference. It appends approved ledger evidence only; article rows, source objects, search indexes, embeddings, and RAG state remain unchanged.

`POST /v1/admin/kb/articles/write-approvals/refresh-preview` accepts approved ledger evidence and projects the post-write source/restore evidence metadata. It returns current source-version evidence hashes, projected source-version evidence hashes, and a `projected_restore_evidence_preview_hash`; it does not persist evidence rows, article rows, source objects, search indexes, embeddings, or RAG state.

`POST /v1/admin/kb/articles/write-approvals/execution-skeleton` accepts approved ledger evidence, source-object write-guard decision metadata, refresh-preview hashes, and explicit human confirmation. It returns a blocked `execution_plan_hash` and keeps article rows, source objects, evidence rows, search indexes, embeddings, and RAG state unchanged.

`POST /v1/admin/kb/articles/write-approvals/execute` accepts approved ledger evidence, source-object write-guard decision metadata, refresh-preview hashes, an execution plan hash, explicit human confirmation, and the proposed source object. It commits edit/create writes through `KnowledgeBaseWriteUnitOfWork` by persisting a metadata-only source-object write receipt, persisting the source object/source metadata/storage manifest, updating article/current-version metadata, refreshing source-version evidence, and returning `refreshed_restore_evidence_hash` plus `source_object_write_receipt_hash`. For create operations, article key, title, proposed version label, and source system come from the trusted approval evidence, not the execution request. It does not return source text, article bodies, prompts, outputs, embeddings, or model responses.

`PgKnowledgeBaseArticleRepository` proves the PostgreSQL write boundary for this slice. It persists article metadata, article-version metadata, source-version evidence, and restore evidence in one transaction for create/edit operations. `PgSourceObjectWriteReceiptStore` proves the durable metadata-only source-object write boundary before article metadata is committed. `PgSourceObjectRepository` proves source metadata and storage-manifest persistence behind a `SourceObjectContentStore` interface. `PostgresKnowledgeBaseWriteUnitOfWork` can run those metadata adapters in one shared PostgreSQL transaction. `source_object_content_recovery_evidence.v1` compares content-store inventory with storage manifests, detects orphaned content, binds a restore-drill report hash, and exposes `api_wiring_allowed`; clean evidence is surfaced as `source_content_recovery_evidence_hash` when the Postgres UoW is gated for API wiring. `S3CompatibleSourceObjectContentStore` is the S3/MinIO-compatible content-store adapter port with Object Lock/WORM and legal-hold capability checks. `Boto3S3CompatibleObjectStoreClient` provides the concrete SDK binding behind that port, and `knowledge_base_production_write_deployment_gate.v1` additionally requires ready `s3_compatible_provider_profile_evidence.v1` plus bound restore-drill evidence before exposing `production_write_deployment_gate_evidence_hash`. `knowledge_base_runtime` can activate this Postgres/S3 path from explicit runtime configuration while the default demo path remains in-memory. Request-time selection is tenant-scoped through persisted runtime activation evidence, not a process-wide tenant environment variable. These adapters do not persist source text or article bodies in PostgreSQL.

Normal use is blocked unless the tenant has provisioned and enabled `knowledge_base` with `knowledge_base.articles.read` enabled.

## Backup And Restore

The slice belongs to the `knowledge_base_content` continuity domain. Source-object write receipts belong to `postgres_metadata` and are linked by hash from Knowledge Base execution evidence. Backup and restore evidence must cover article metadata, article-version metadata, source-version evidence, source write receipts, source references, tenant isolation, disabled-state restore behavior, and Legal Hold state before broader authoring or RAG work begins.

## RAG Boundary

This slice intentionally stops before RAG. Later RAG work must use candidate-only search, authoritative ACL validation before source fetch, source object IDs and source versions in citations, Local LLM Gateway enforcement, tenant AI policy, and metadata-only audit.

## Verification

- `tests/test_knowledge_base.py`
- `tests/test_api.py`
- `tests/test_pgvector_migration.py`
- `tests/test_knowledge_base_docs.py`
