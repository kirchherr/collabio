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

`0023_knowledge_base_write_approval_evidence.sql` creates the append-only write-approval ledger. `0024_knowledge_base_write_approval_transition_lineage.sql` requires non-dry-run approval states to point back to the dry-run evidence that was approved. `0025_knowledge_base_write_approval_trusted_article_metadata.sql` pins trusted create metadata into approval evidence before execution. The dry-run endpoint appends metadata-only approval evidence through the ledger port. The approval endpoint appends `approved_for_write` evidence with lineage, but still does not mutate article/source records. `KnowledgeBaseSourceObjectWriteGuard` consumes approved ledger evidence before writes and checks expected version for edits, proposed source-version evidence, restore evidence, retention, Legal Hold, and source-object metadata. The execution skeleton binds approved evidence, source-guard decision, refresh-preview hash, and human confirmation into an audited `execution_plan_hash`. The execute endpoint performs guarded in-memory edit/create commits and refreshes evidence while keeping RAG and indexing disabled.

## Runtime Contract

The API returns only articles for the current tenant where the current user is authorized for both the `kb.article` and current `kb.article_version` object IDs.

Each returned article includes a `source_version_evidence_hash`. The response includes `source_version_evidence_hashes` and a `restore_evidence_hash`, and the audit event records those hashes as metadata only.

`GET /v1/admin/kb/evidence` exposes the full source-version and restore-evidence metadata to tenant admins through the compliance module gate. It remains available while normal article browsing is disabled, and it does not return article bodies or source text.

`POST /v1/admin/kb/articles/write-dry-run` accepts create/edit approval command metadata and produces audit-only dry-run evidence. It does not mutate article rows, source objects, search indexes, embeddings, or RAG state.

`POST /v1/admin/kb/articles/write-approvals/approve` accepts a dry-run evidence hash and a new approval reference. It appends approved ledger evidence only; article rows, source objects, search indexes, embeddings, and RAG state remain unchanged.

`POST /v1/admin/kb/articles/write-approvals/refresh-preview` accepts approved ledger evidence and projects the post-write source/restore evidence metadata. It returns current source-version evidence hashes, projected source-version evidence hashes, and a `projected_restore_evidence_preview_hash`; it does not persist evidence rows, article rows, source objects, search indexes, embeddings, or RAG state.

`POST /v1/admin/kb/articles/write-approvals/execution-skeleton` accepts approved ledger evidence, source-object write-guard decision metadata, refresh-preview hashes, and explicit human confirmation. It returns a blocked `execution_plan_hash` and keeps article rows, source objects, evidence rows, search indexes, embeddings, and RAG state unchanged.

`POST /v1/admin/kb/articles/write-approvals/execute` accepts approved ledger evidence, source-object write-guard decision metadata, refresh-preview hashes, an execution plan hash, explicit human confirmation, and the proposed source object. It commits edit/create writes by persisting the source object, updating article/current-version metadata, refreshing source-version evidence, and returning `refreshed_restore_evidence_hash`. For create operations, article key, title, proposed version label, and source system come from the trusted approval evidence, not the execution request. It does not return source text, article bodies, prompts, outputs, embeddings, or model responses.

`PgKnowledgeBaseArticleRepository` proves the PostgreSQL write boundary for this slice. It persists article metadata, article-version metadata, source-version evidence, and restore evidence in one transaction for create/edit operations. It does not persist source text or article bodies; the source-object content adapter remains separate.

Normal use is blocked unless the tenant has provisioned and enabled `knowledge_base` with `knowledge_base.articles.read` enabled.

## Backup And Restore

The slice belongs to the `knowledge_base_content` continuity domain. Backup and restore evidence must cover article metadata, article-version metadata, source-version evidence, source references, tenant isolation, disabled-state restore behavior, and Legal Hold state before broader authoring or RAG work begins.

## RAG Boundary

This slice intentionally stops before RAG. Later RAG work must use candidate-only search, authoritative ACL validation before source fetch, source object IDs and source versions in citations, Local LLM Gateway enforcement, tenant AI policy, and metadata-only audit.

## Verification

- `tests/test_knowledge_base.py`
- `tests/test_api.py`
- `tests/test_pgvector_migration.py`
- `tests/test_knowledge_base_docs.py`
