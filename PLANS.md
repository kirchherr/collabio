# Plans

This file tracks the active implementation sequence. The canonical roadmap is `docs/ROADMAP.md`.

## Current Journey

Theme: Build proof capability before product surface.

Current sprint:

1. [x] Research baseline, stack candidates, and ADR backlog.
2. [x] Product charter, security policy, threat model, compliance matrix.
3. [x] Data classification, retention policies, legal hold model.
4. [x] ADR template and initial ADRs.
5. [x] Phase 0 engineering tooling.
6. [x] Request-scoped tenant context.
7. [x] Append-only audit model.
8. [x] File-backed policy, registry, and audit stores.
9. [x] Admin API for tenant AI settings and allowed models.
10. [x] Prompt-injection and unauthorized-RAG-output tests.
11. [x] Direct LLM provider bypass architecture guards.
12. [x] ADR for pgvector vs. Qdrant.
13. [x] First pgvector embedding metadata migration and tests.
14. [x] PostgreSQL/pgvector dev service, migration runner, and live RLS tests.
15. [x] pgvector adapter for upsert, lifecycle transitions, and candidate-only search.

## Next Engineering Step

After the pgvector adapter is in place:

- Add API or worker entrypoints for reindex and deletion propagation.
- Add source resolver and text extraction pipeline feeding the pgvector adapter.
- Add benchmark fixtures for exact search before ANN index decisions.
