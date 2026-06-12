# Knowledge Base Write Approval Ledger

Status: wired for dry-run persistence and approval lineage
Date: 2026-06-12
Module ID: `knowledge_base`
Implementation contract: `docs/modules/MODULE_IMPLEMENTATION_CONTRACT.md`

## Purpose

Knowledge Base create/edit actions require a persistent approval-evidence ledger before article metadata, source objects, search indexes, embeddings, or RAG state may change.

The first implementation stage is still metadata-only dry-run. It validates approval command metadata, creates command and evidence hashes, writes audit, persists the approval evidence through the append-only ledger port, and does not persist article or source-object content changes.

## Ledger Contract

Migration `0023_knowledge_base_write_approval_evidence.sql` creates `knowledge_base.write_approval_evidence`.
Migration `0024_knowledge_base_write_approval_transition_lineage.sql` adds `transition_source_evidence_hash`.

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
- transition source evidence hash for non-dry-run states
- requested-by principal
- Legal Hold state through linked source-version evidence
- audit event ID and audit-chain reference
- evidence hash

## Safety Rules

- `proposed_version_object_id` must equal `proposed_source_object_id`.
- Edit approval evidence must name the expected current version.
- Create approval evidence must not name an expected current version.
- Dry-run evidence cannot allow persistence.
- Dry-run evidence cannot reference a transition source.
- `approved_for_write`, `rejected`, and `expired` evidence must reference the source dry-run evidence by hash.
- RAG indexing cannot be allowed before write approval.
- The ledger is append-only by policy: no update and no hard delete.
- RLS is mandatory.
- No article bodies, source text, prompts, outputs, transcripts, raw payloads, embeddings, or model responses are stored in the ledger.

## Runtime Boundary

`POST /v1/admin/kb/articles/write-dry-run` requires tenant context and creates dry-run evidence. The service appends that evidence to the ledger before returning a `write_approval_evidence_hash`.

`POST /v1/admin/kb/articles/write-approvals/approve` requires tenant context and a tenant admin. It accepts a dry-run evidence hash, a new human approval reference, and a reason. The service verifies the dry-run evidence hash, current restore evidence, and expected current article version before appending a new `approved_for_write` ledger row whose `transition_source_evidence_hash` points back to the dry-run evidence. It does not write article metadata, source objects, source text, article bodies, embeddings, or RAG state.

Runtime wiring:

- tests and local in-memory slices use `InMemoryKnowledgeBaseWriteApprovalLedger`.
- the Docker Compose API profile sets `SUITE_KB_WRITE_APPROVAL_LEDGER_BACKEND=postgres` after migrations, so dry-run evidence is inserted into `knowledge_base.write_approval_evidence`.
- the ledger row remains metadata-only and cannot authorize persistence while `approval_state` is `dry_run`.
- `KnowledgeBaseSourceObjectWriteGuard` consumes ledger evidence by exact tenant-scoped evidence hash and returns a metadata-only guard decision before future article/source writes.

Current dry-run persistence inserts the ledger row before any article/source write can exist. Approval transition appends a second lineage-linked ledger row. Future write paths must verify the approved ledger row, pass the source-object write guard, and then refresh source-version evidence plus restore evidence. Actual writes remain blocked until restore evidence refresh and article/source mutation paths are explicitly connected.

## Source-Object Write Guard

The write guard checks:

- the ledger evidence exists for the current tenant and the evidence hash recomputes.
- the approval state is `approved_for_write` and persistence is explicitly allowed.
- edits still match the expected current article version.
- current article Legal Hold and retention policy do not block mutation.
- the proposed source object passes the generic storage write guard.
- proposed source object ID, version, type, manifest hash, content hash, ACL version, retention policy, and Legal Hold state match the proposed source-version evidence hash.
- current restore evidence hash matches and verifies tenant isolation, disabled-state restore behavior, and Legal Hold restore behavior.

The decision stores only metadata, hashes, object IDs, and blocking reason codes. It does not store source text, article bodies, prompts, outputs, raw payloads, embeddings, or model responses.

## Backup And Restore

The ledger belongs to the `knowledge_base_content` continuity domain. Backup and restore drills must verify write-approval evidence hashes before approved write workflows are allowed.

## Verification

- `tests/test_knowledge_base.py`
- `tests/test_api.py`
- `tests/test_pgvector_migration.py`
- `tests/test_knowledge_base_docs.py`
- `tests/test_knowledge_base_write_approval_ledger.py`
