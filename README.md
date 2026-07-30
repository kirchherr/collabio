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
docs/OFFICE_MAIL_CORE.md
docs/SOURCE_OBJECT_MODEL.md
docs/STORAGE_ADAPTER_PLAN.md
docs/storage_adapter_policy.json
docs/CONTENT_HASH_VERIFICATION.md
docs/STORAGE_MANIFEST.md
docs/KMS_ADAPTER.md
docs/ENVELOPE_ENCRYPTION.md
docs/kms_adapter_policy.json
docs/RETENTION_MANIFEST.md
docs/retention_manifest_policy.json
docs/LEGAL_HOLD_API.md
docs/operations/BACKUP_FAILOVER.md
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
docker compose run --rm backup
docker compose run --rm backup-verify
docker compose run --rm source-object-runtime-bootstrap
docker compose run --rm backend-storage-foundation-gate
docker compose run --rm postgres-restore-drill
docker compose run --rm backend-foundation-completion-gate
docker compose --profile restore-drill run --rm business-backend-release-gate
docker compose --profile restore-drill run --rm productivity-pilot-preflight-gate
docker compose up api
```

The `quality` service is the local and CI gate. It runs Ruff, Ruff format check, Mypy, and Pytest in the development container.

The Compose stack includes PostgreSQL 18 with pgvector on configurable host port `SUITE_POSTGRES_PORT` (default `5433`). Runtime state uses `postgres18_data`; tests and Quality use the isolated `postgres-test` service and `postgres18_test_data` volume.

Local database backups are written to `./backups/`. `postgres-restore-drill` verifies the checksum and restore catalog, recreates an isolated PostgreSQL target, and compares migrations, schema, exact row counts, RLS policies, roles, and grants without emitting row content.

MinIO is part of the default API foundation on configurable ports `SUITE_MINIO_API_PORT`/`SUITE_MINIO_CONSOLE_PORT` (defaults `29000`/`29001`). API startup requires bucket-profile evidence plus a successful `persistent_source_object_runtime_report.v1` covering fresh-instance reads and tenant-scoped content reconciliation.

The opt-in `restore-drill` profile adds independent MinIO and PostgreSQL targets. MinIO uses configurable ports `SUITE_MINIO_RESTORE_API_PORT`/`SUITE_MINIO_RESTORE_CONSOLE_PORT` (defaults `29100`/`29101`); PostgreSQL uses `SUITE_POSTGRES_RESTORE_PORT` (default `55433`). `backend-storage-foundation-gate` proves exact-version object recovery. `backend-foundation-completion-gate` binds that evidence to isolated PostgreSQL recovery plus Tenant/IAM, append-only Audit, Module Registry, migration catalog, and persistent SourceObject controls. All gate output is metadata-only. `business-backend-release-gate` additionally binds the green foundation hash to the live API/OpenAPI contract, installed module and migration catalog, PostgreSQL backend configuration, and restored write controls for CRM onboarding, Tasks, and Time Tracking without activating tenants or executing business writes. `productivity-pilot-preflight-gate` then checks explicitly selected tenant module states, safe feature scope, monitoring, and non-destructive rollback contracts while keeping human admission, traffic enforcement, and pilot start false.

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
- Parser worker boundary for plain text and RFC822 mail extraction behind the TextExtractor interface
- Isolated rich-document parser service for DOCX, ODT, and basic text PDF extraction
- Source object metadata model and RAG resolver for documents, mails, attachments, comments, wiki content, and procedure documentation
- Storage write guard for mandatory compliance metadata, KMS references, content hashes, and manifest hashes
- Reusable content hash verifier for storage writes, reads, restore drills, parser inputs, and future exports
- Storage object manifest model with restore verification for source, retention, content hash, Object Lock, legal hold, KMS, and object-version evidence
- KMS adapter boundary with canonical key references, key-usage evidence, rotation evidence, destruction guards, and no raw key material exposure
- Envelope encryption API with local dev implementation, encryption manifests, AAD binding, wrapped data key hashes, and destroyed-key rejection
- S3/MinIO-compatible object-storage ADR, bucket profile policy, and restore-check plan
- Retention defaults and RetentionManifest model for source, WORM, legal-hold, backup, and e-discovery flows
- Legal Hold service/API boundary for versioned source object transitions and retention re-evaluation
- Hash-chained audit events for vector worker jobs
- Deterministic exact-search benchmark fixtures for pgvector recall baselines
- Suite-wide backup/failover continuity policy, runbook, and Docker backup verification commands
- Prompt-injection and unauthorized-RAG-output regression tests
- Architecture guards that prevent direct LLM provider bypasses outside the gateway
- Voice transcript classification and no-raw-audio default
- Governance documents for Phase -1
