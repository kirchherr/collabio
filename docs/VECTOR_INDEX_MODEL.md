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
- vector metadata is validated in Python before worker writes and in PostgreSQL through schema constraints.
- `source_object_type`, `legal_hold_state`, `acl_hash`, `acl_version`, content hashes, and timestamps are schema-validated.
- `acl_version` is copied from authoritative source metadata and must be greater than or equal to 1.
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

The worker can receive a `VectorWorkerAuditSink`. `AuditLoggerVectorWorkerAuditSink` writes hash-chained audit events for started, completed, and failed reindex or deletion-propagation jobs. `build_durable_vector_worker_audit_sink` connects that sink to the deployment audit log under `SUITE_DATA_DIR/audit/events.jsonl` by default and verifies the existing chain before appending new worker events.

These events carry source IDs, source version, lifecycle targets, counts, model IDs, ACL hashes, ACL versions, and upstream audit IDs only. They do not include raw source text, prompts, generated answers, transcripts, raw audio, or raw embedding vectors. The sink rejects unsafe raw-payload metadata keys before writing.

The runtime app role has no `INSERT`, `UPDATE`, or `DELETE` grant on `collabio.vector_embedding_chunks`. This prevents API-side writes or accidental reactivation of deleted/restricted chunks.

## Source Indexing Pipeline

`app/suite/rag/source_indexing.py` is the first source-to-vector orchestration layer.

It separates the pipeline into replaceable contracts:

- `SourceResolver`: resolves tenant, source, version, ACL hash, classification, retention, legal-hold, and source type metadata.
- `TextExtractor`: extracts text from the resolved source. The current implementation handles plain text only.
- `TextChunker`: creates deterministic chunk IDs, content hashes, and byte lengths.
- `EmbeddingProvider`: produces vectors. The current deterministic hash embedder is for local development and tests only.
- `EmbeddingModelVersionRegistry`: resolves the exact model ID and version before indexing.
- `SourceIndexingPipeline`: converts extracted chunks into `VectorEmbeddingRecord` objects and sends them to `VectorIndexWorker.reindex_source`.

Before a source is indexed, the pipeline verifies that the configured embedding model version:

- exists in the registry
- is approved for indexing
- is not retired
- is approved for the source data classification
- declares the same dimensions produced by the embedding provider

`PgvectorEmbeddingModelVersionRegistry` reads the production-facing state from `collabio.embedding_models`, including version, dimensions, checksum, approved data classes, approval timestamp, and retirement timestamp.

The pipeline can receive an expected ACL hash or ACL version. If the resolved source metadata differs, indexing stops before worker writes. The worker also rejects chunk sets with mixed ACL hashes or ACL versions, so one reindex operation cannot accidentally publish stale and current authorization metadata together.

The live integration test proves that the pipeline feeds the pgvector worker and that a later source reindex soft-deletes stale chunks while keeping candidate search source-text-free.

`app/suite/rag/parser_worker.py` adds the parser worker boundary behind `TextExtractor`.

Current local parser support is intentionally narrow:

- `text/plain`
- `text/markdown`
- `message/rfc822` plain-text mail body extraction with attachments skipped
- DOCX text extraction via `word/document.xml`
- ODT text extraction via `content.xml`
- basic text PDF stream extraction

Rich document parsing stays behind the same `TextExtractor` and parser worker boundary. Complex PDFs, scanned PDFs, macros, password-protected documents, and high-fidelity Office compatibility must be handled by dedicated isolated parser worker containers, not inside the API or pgvector adapter.

## Exact Search Benchmarks

`app/suite/rag/vector_benchmarks.py` provides deterministic exact-search fixtures:

- `build_exact_search_benchmark_fixture`: creates stable embedding records and query expectations.
- `rank_exact_vectors`: computes an in-process cosine ranking oracle.
- `assert_exact_search_fixture_consistency`: proves that every expected query result is the exact top result.
- `VectorBenchmarkThresholds`: declares minimum record/query counts, recall thresholds, latency ceilings, and `top_k`.
- `VectorBenchmarkObservation`: records returned chunk IDs and measured latency for each benchmark query.
- `build_vector_benchmark_report`: produces a hashable benchmark report with recall-at-1, recall-at-k, p95/p99 latency, failed checks, and an ANN decision.

The live pgvector integration test loads the fixture through the worker-write path and verifies recall-at-1 against exact pgvector search. ANN indexes remain deferred until benchmark thresholds, tenant distributions, and model dimensions are explicit.

Exact pgvector benchmarks are baseline evidence only. They cannot approve ANN usage by themselves.

HNSW or IVFFlat candidates must produce a `vector_benchmark_report.v1` report with:

- tenant, embedding model, model version, dimensions, record count, query count, and `top_k`
- threshold payload and failed-check names
- observations hash and report hash
- UTC measurement timestamp
- decision `ann_candidate_passed` only when every recall, latency, and fixture-size threshold passes

Benchmark reports are operational evidence. Restore and failover checks for search/vector domains must preserve report hashes so index rebuilds and ANN rollouts can be re-evaluated instead of trusted from memory.
