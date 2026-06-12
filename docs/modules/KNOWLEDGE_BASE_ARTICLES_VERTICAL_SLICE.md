# Knowledge Base Articles Vertical Slice

Status: initial
Date: 2026-06-12

This slice proves the reusable module implementation contract outside CRM/ERP. It starts the Knowledge Base with metadata-only article reads and source-version references, not a full wiki and not RAG.

## Scope

- Module: `knowledge_base`
- Feature gate: `knowledge_base.articles.read`
- API: `GET /v1/kb/articles`
- Persistent tables: `knowledge_base.articles`, `knowledge_base.article_versions`
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

## Runtime Contract

The API returns only articles for the current tenant where the current user is authorized for both the `kb.article` and current `kb.article_version` object IDs.

Normal use is blocked unless the tenant has provisioned and enabled `knowledge_base` with `knowledge_base.articles.read` enabled.

## Backup And Restore

The slice belongs to the `knowledge_base_content` continuity domain. Backup and restore evidence must cover article metadata, article-version metadata, source references, tenant isolation, disabled-state restore behavior, and Legal Hold state before broader authoring or RAG work begins.

## RAG Boundary

This slice intentionally stops before RAG. Later RAG work must use candidate-only search, authoritative ACL validation before source fetch, source object IDs and source versions in citations, Local LLM Gateway enforcement, tenant AI policy, and metadata-only audit.

## Verification

- `tests/test_knowledge_base.py`
- `tests/test_api.py`
- `tests/test_pgvector_migration.py`
