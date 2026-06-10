# Compliance-First Enterprise Suite

Initial containerized MVP foundation for a self-hosted enterprise work suite with:

- AI Control Plane
- Local LLM Gateway
- ACL-aware RAG foundation
- Privacy-first voice interaction layer
- Zero-friction command palette architecture notes
- AI, voice, and RAG governance documents

The first implementation is intentionally small and testable. It establishes the security contracts before adding product features.

Merged master roadmap:

```text
docs/ROADMAP.md
```

Research and implementation baseline:

```text
docs/RESEARCH_BASELINE.md
docs/OPEN_SOURCE_STACK.md
docs/ADR_BACKLOG.md
```

Phase -1 foundation:

```text
PRODUCT_CHARTER.md
SECURITY.md
THREAT_MODEL.md
COMPLIANCE_MATRIX.md
DATA_CLASSIFICATION.md
RETENTION_POLICIES.yaml
LEGAL_HOLD_MODEL.md
ARCHITECTURE_DECISIONS/
```

## Development

All development commands are meant to run through Docker Compose.

```bash
docker compose build
docker compose run --rm quality
docker compose run --rm lint
docker compose run --rm typecheck
docker compose run --rm test
docker compose run --rm migrate
docker compose up api
```

The `quality` service is the local and CI gate. It runs Ruff, Ruff format check, Mypy, and Pytest in the development container.

The Compose stack includes PostgreSQL 18 with pgvector on host port `5433`. `migrate` applies packaged SQL migrations with the owner DSN; application and integration tests use the non-owner `collabio_app` role to exercise RLS.

API:

```text
http://localhost:8000
```

Health endpoint:

```text
GET /health
```

## Security posture

- AI is disabled by default unless tenant policy enables it.
- No feature should call an LLM provider directly.
- Vector search only returns candidates.
- Authoritative ACL validation happens before RAG context construction.
- LLM output is untrusted until validated by the caller.
- Sensitive or destructive actions require explicit human approval.
- Raw voice audio is not stored by default.

## Project layout

```text
app/
  main.py
  suite/
    ai_control_plane/
    llm_gateway/
    platform/
    rag/
    voice/
docs/
tests/
.github/
```

## Current scope

This is the MVP skeleton for the roadmap in `konzept_suite_2.md`. It includes:

- Deny-by-default policy engine
- Request-scoped tenant context for tenant data endpoints
- Role-gated admin API for tenant AI settings and allowed models
- File-backed tenant policy, model, prompt, tool-permission, and audit stores
- Append-only audit hash chain with verifier
- Mock LLM provider for local tests
- RAG flow with candidate retrieval, ACL checks, untrusted source framing, citations, and audit
- pgvector/PostgreSQL dev service with live migration runner and vector RLS integration tests
- pgvector adapter for candidate-only search, upsert, and lifecycle transitions
- Worker entry points for vector reindex and deletion propagation
- Source resolver, text extraction, deterministic chunking, and source-to-vector indexing pipeline
- Hash-chained audit events for vector worker jobs
- Deterministic exact-search benchmark fixtures for pgvector recall baselines
- Prompt-injection and unauthorized-RAG-output regression tests
- Architecture guards that prevent direct LLM provider bypasses outside the gateway
- Voice transcript classification and no-raw-audio default
- Governance documents for Phase -1
