# ADR-0031: First Vector Backend pgvector vs Qdrant

Status: accepted
Date: 2026-06-10

## Context

The suite needs vector search for RAG, semantic search, e-discovery assistance, and AI workflows. Embeddings are classified tenant data, not anonymous telemetry. The first backend must support:

- tenant isolation
- authoritative authorization after candidate retrieval
- deletion and reindex flows tied to source lifecycle
- backup and restore
- auditability
- operational simplicity for self-hosted deployments

Vector search is not an authorization source. It may return candidate IDs and metadata only; source fetch, ACL validation, redaction, and answer construction remain inside our controlled RAG pipeline.

## Decision

Use `pgvector` as the first persistent vector backend.

Reasons:

- It keeps embeddings close to source metadata, tenant IDs, retention fields, ACL versions, lifecycle state, and audit references in PostgreSQL.
- PostgreSQL Row-Level Security can act as defense-in-depth around tenant-scoped rows.
- PostgreSQL transactions, backups, point-in-time recovery, migrations, roles, and observability stay aligned with the rest of the core platform.
- pgvector supports exact and approximate nearest-neighbor search, including HNSW and IVFFlat indexes.
- The MVP and first production pilots need correctness, traceability, and operational coherence more than a separate vector cluster.

Keep a `VectorSearchAdapter` boundary so Qdrant can be introduced later as a scale backend without changing product code or RAG authorization semantics.

Qdrant remains the preferred candidate when one or more of these become true:

- vector volume, recall/latency targets, or write throughput exceed PostgreSQL/pgvector operating limits
- dedicated vector operations need independent scaling
- Qdrant payload filtering, payload indexes, shard keys, or multitenancy features become materially useful
- hybrid/vector workloads require operational isolation from transactional PostgreSQL

## Consequences

Easier:

- Tenant metadata, vector rows, audit references, lifecycle status, and deletion workflows can share one database boundary.
- PostgreSQL RLS can be tested as a defense-in-depth layer.
- Backups, migrations, local development, and self-hosting start simpler.
- Compliance evidence is easier to assemble because vector metadata lives near core records.

Harder:

- Very large vector workloads may hit PostgreSQL memory, index, vacuum, and query-planning tradeoffs earlier than a dedicated vector engine.
- Filtered vector search performance must be benchmarked against realistic tenant distributions.
- Qdrant migration must be planned rather than improvised.

Required guardrails:

- Vector queries return candidate IDs and metadata only.
- Candidate results must be revalidated by authoritative ACL checks before source fetch and RAG context construction.
- Embedding rows must include tenant ID, source object ID, source version ID, chunk ID, classification, retention policy ID, legal hold state, ACL hash/version, embedding model ID/version, and content hash.
- Source deletion, restriction, reindex, cryptoshred, and legal-hold workflows must update vector rows.

## Alternatives Considered

### Qdrant first

Rejected for MVP because it adds a second persistence system before the platform has PostgreSQL roles, migrations, RLS tests, lifecycle workflows, and audit persistence. Qdrant is still a strong scale backend candidate.

### Pluggable vector backend without first default

Rejected because it delays concrete schema, lifecycle, and compliance tests. We still keep an adapter boundary, but pgvector is the first concrete implementation.

### In-memory vector search only

Rejected beyond tests because it cannot prove lifecycle, deletion, audit, backup, or tenant-isolation behavior.

## Compliance Mapping

- `COMPLIANCE_MATRIX.md`: CM-001, CM-003, CM-004, CM-005, CM-007, CM-009, CM-010, CM-011
- `DATA_CLASSIFICATION.md`: `embedding`, `rag_chunk`, `retrieval_trace`
- DSGVO: data minimization, access control, deletion/restriction workflows
- GoBD: traceability for relevant business records
- OWASP LLM/GenAI: vector and embedding weaknesses

## Verification

- Migration tests create pgvector extension and vector tables.
- RLS tests prove tenant isolation for vector rows.
- Adapter tests prove vector search returns candidates only.
- RAG tests prove unauthorized candidates are filtered before source fetch.
- Deletion/reindex tests prove source lifecycle updates vector state.
- Benchmarks compare exact search, HNSW, and IVFFlat with realistic tenant filters before production scale claims.
- ADR review is required before introducing Qdrant into production.

## References

- pgvector repository: https://github.com/pgvector/pgvector
- PostgreSQL Row Security Policies: https://www.postgresql.org/docs/current/ddl-rowsecurity.html
- Qdrant filtering documentation: https://qdrant.tech/documentation/search/filtering/
- Qdrant multitenancy documentation: https://qdrant.tech/documentation/manage-data/multitenancy/
