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

## Live Migration Path

Docker Compose provides PostgreSQL 18 with pgvector through the `postgres` service. The database is exposed locally on port `5433` for development diagnostics.

Run migrations with:

```bash
docker compose run --rm migrate
```

The migration runner records applied SQL files in `collabio.schema_migrations` with a SHA-256 checksum. If a previously applied migration changes, the runner fails instead of silently rewriting history.

Live integration tests use:

- `SUITE_MIGRATION_DATABASE_DSN` for owner-level migration/setup work.
- `SUITE_DATABASE_DSN` for the non-owner `collabio_app` runtime role.

`tests/test_pgvector_integration.py` proves the first migration installs pgvector, records migration state, enforces tenant-scoped RLS, hides non-active lifecycle states from candidate reads, blocks cross-tenant inserts, and denies hard deletes.

## Adapter Boundary

`app/suite/rag/pgvector_store.py` implements the first persistent vector adapter.

Runtime split:

- `collabio_app` performs candidate-only search.
- `collabio_worker` performs upserts, reindex state changes, stale chunk cleanup, and deletion propagation under tenant-scoped RLS.

The adapter returns `VectorCandidate` objects only. It does not return embeddings, snippets, source text, prompts, or answers. Source text is still resolved later by the RAG pipeline after authoritative ACL validation.

Implemented operations:

- `upsert_embedding`: writes or refreshes vector metadata for one chunk.
- `search` / `search_by_embedding`: returns active candidates ordered by cosine similarity.
- `transition_lifecycle`: moves chunks to `restricted`, `deleted`, `cryptoshredded`, `reindex_pending`, or `active` using the worker role.
- `mark_source_for_reindex`: marks active chunks as `reindex_pending`.
- `delete_reindex_orphans`: soft-deletes chunks left behind after a reindex.
- `transition_source_lifecycle`: propagates deletion or cryptoshred state to all chunks for one source version.

`app/suite/rag/vector_worker.py` exposes worker entry points:

- `reindex_source`: marks existing active chunks for reindex, upserts the new chunk set, and soft-deletes stale reindex leftovers.
- `propagate_deletion`: moves all chunks for a source version to `deleted` or `cryptoshredded`.

The worker can receive an optional `VectorWorkerAuditSink`. `AuditLoggerVectorWorkerAuditSink` writes hash-chained audit events for started, completed, and failed reindex or deletion-propagation jobs. These events carry source IDs, source version, lifecycle targets, counts, model IDs, and upstream audit IDs only. They do not include raw source text, prompts, generated answers, or raw embedding vectors.

The runtime app role has no `INSERT`, `UPDATE`, or `DELETE` grant on `collabio.vector_embedding_chunks`. This prevents API-side writes or accidental reactivation of deleted/restricted chunks.

## Source Indexing Pipeline

`app/suite/rag/source_indexing.py` is the first source-to-vector orchestration layer.

It separates the pipeline into replaceable contracts:

- `SourceResolver`: resolves tenant, source, version, ACL hash, classification, retention, legal-hold, and source type metadata.
- `TextExtractor`: extracts text from the resolved source. The current implementation handles plain text only.
- `TextChunker`: creates deterministic chunk IDs, content hashes, and byte lengths.
- `EmbeddingProvider`: produces vectors. The current deterministic hash embedder is for local development and tests only.
- `SourceIndexingPipeline`: converts extracted chunks into `VectorEmbeddingRecord` objects and sends them to `VectorIndexWorker.reindex_source`.

The live integration test proves that the pipeline feeds the pgvector worker and that a later source reindex soft-deletes stale chunks while keeping candidate search source-text-free.

Binary and rich document formats must be added behind `TextExtractor` through sandboxed parser workers, not inside the API or pgvector adapter.

## Exact Search Benchmarks

`app/suite/rag/vector_benchmarks.py` provides deterministic exact-search fixtures:

- `build_exact_search_benchmark_fixture`: creates stable embedding records and query expectations.
- `rank_exact_vectors`: computes an in-process cosine ranking oracle.
- `assert_exact_search_fixture_consistency`: proves that every expected query result is the exact top result.

The live pgvector integration test loads the fixture through the worker-write path and verifies recall-at-1 against exact pgvector search. ANN indexes remain deferred until benchmark thresholds, tenant distributions, and model dimensions are explicit.
