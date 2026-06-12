# Knowledge Base Write Approval Ledger

Status: wired for dry-run persistence
Date: 2026-06-12
Module ID: `knowledge_base`
Implementation contract: `docs/modules/MODULE_IMPLEMENTATION_CONTRACT.md`

## Purpose

Knowledge Base create/edit actions require a persistent approval-evidence ledger before article metadata, source objects, search indexes, embeddings, or RAG state may change.

The first implementation stage is still metadata-only dry-run. It validates approval command metadata, creates command and evidence hashes, writes audit, persists the approval evidence through the append-only ledger port, and does not persist article or source-object content changes.

## Ledger Contract

Migration `0023_knowledge_base_write_approval_evidence.sql` creates `knowledge_base.write_approval_evidence`.

Each ledger row must carry:

- tenant ID
- approval reference
- operation (`create` or `edit`)
- approval state
- article object ID
- expected current version for edits
- proposed version object ID
- proposed source object ID and version ID
- proposed source manifest hash
- proposed content hash
- proposed ACL version
- command hash
- proposed source-version evidence hash
- current restore evidence hash
- source-object write-guard reference
- requested-by principal
- Legal Hold state through linked source-version evidence
- audit event ID and audit-chain reference
- evidence hash

## Safety Rules

- `proposed_version_object_id` must equal `proposed_source_object_id`.
- Edit approval evidence must name the expected current version.
- Create approval evidence must not name an expected current version.
- Dry-run evidence cannot allow persistence.
- RAG indexing cannot be allowed before write approval.
- The ledger is append-only by policy: no update and no hard delete.
- RLS is mandatory.
- No article bodies, source text, prompts, outputs, transcripts, raw payloads, embeddings, or model responses are stored in the ledger.

## Runtime Boundary

`POST /v1/admin/kb/articles/write-dry-run` requires tenant context and creates dry-run evidence. The service appends that evidence to the ledger before returning a `write_approval_evidence_hash`.

Runtime wiring:

- tests and local in-memory slices use `InMemoryKnowledgeBaseWriteApprovalLedger`.
- the Docker Compose API profile sets `SUITE_KB_WRITE_APPROVAL_LEDGER_BACKEND=postgres` after migrations, so dry-run evidence is inserted into `knowledge_base.write_approval_evidence`.
- the ledger row remains metadata-only and cannot authorize persistence while `approval_state` is `dry_run`.

Current dry-run persistence inserts the ledger row before any article/source write can exist. Future approved write paths must verify the ledger row, pass the source-object write guard, and then refresh source-version evidence plus restore evidence. Actual writes remain blocked until the source-object write guard and restore evidence refresh are connected.

## Backup And Restore

The ledger belongs to the `knowledge_base_content` continuity domain. Backup and restore drills must verify write-approval evidence hashes before approved write workflows are allowed.

## Verification

- `tests/test_knowledge_base.py`
- `tests/test_api.py`
- `tests/test_pgvector_migration.py`
- `tests/test_knowledge_base_docs.py`
