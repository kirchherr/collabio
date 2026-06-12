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

Migration `0023_knowledge_base_write_approval_evidence.sql` adds the append-only write-approval ledger. The dry-run path now persists ledger evidence before source-object writes are possible; future approved write paths must verify that evidence and refresh source-version plus restore evidence after approved writes.

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
