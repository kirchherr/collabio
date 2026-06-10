# Vector Index Model

Every chunk must carry metadata equivalent to:

```json
{
  "tenant_id": "tenant-id",
  "source_object_id": "object-id",
  "source_object_type": "document|mail|attachment|comment|wiki|procedure_doc",
  "source_version_id": "version-id",
  "chunk_id": "chunk-id",
  "classification": "internal",
  "retention_policy_id": "retention-policy-id",
  "legal_hold_state": "none|active",
  "acl_hash": "sha256:...",
  "acl_version": 1,
  "created_at_utc": "2026-06-10T00:00:00Z",
  "embedding_model_id": "embedding-model-id",
  "embedding_model_version": "1",
  "content_hash": "sha256:..."
}
```

Embeddings are classified data. They are not anonymous by default and must follow tenant isolation, retention, legal hold, deletion, and audit policies.

## Backend Decision

`ARCHITECTURE_DECISIONS/ADR-0031-pgvector-vs-qdrant.md` selects pgvector as the first persistent vector backend.

Vector search remains an adapter boundary. Qdrant is retained as the scale-out candidate if pgvector no longer meets volume, latency, throughput, or operational-isolation needs.

## First Persistent Schema

`app/suite/persistence/migrations/0001_pgvector_embeddings.sql` defines the first pgvector-backed metadata schema.

The schema stores candidate vectors and compliance metadata only. It does not store source text, prompts, generated answers, or snippets. RAG source fetch and answer construction must still pass through authoritative ACL validation.

Key guardrails:

- `tenant_id` is mandatory and protected by PostgreSQL RLS using the request-scoped `app.tenant_id` setting.
- `embedding_dimensions` must match `vector_dims(embedding)`.
- `lifecycle_state` is soft-delete oriented: `active`, `reindex_pending`, `restricted`, `deleted`, or `cryptoshredded`.
- hard deletes are denied by policy; deletion, restriction, reindex, legal hold, and cryptoshred workflows update lifecycle fields instead.
- ANN indexes are deferred until a concrete embedding model, dimension, tenant distribution, and benchmark target are known.
