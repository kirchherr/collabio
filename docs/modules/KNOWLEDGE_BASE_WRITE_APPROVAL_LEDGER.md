# Knowledge Base Write Approval Ledger

Status: wired for dry-run persistence, approval lineage, trusted create metadata, and source-object write receipts
Date: 2026-06-12
Module ID: `knowledge_base`
Implementation contract: `docs/modules/MODULE_IMPLEMENTATION_CONTRACT.md`

## Purpose

Knowledge Base create/edit actions require a persistent approval-evidence ledger before article metadata, source objects, search indexes, embeddings, or RAG state may change.

The current implementation remains metadata-only in audit and API responses. It validates approval command metadata, creates command and evidence hashes, writes audit, persists approval evidence through the append-only ledger port, supports approval lineage, projects restore/source evidence before execution, persists metadata-only source-object write receipts during execution, and can commit guarded edit/create metadata writes without enabling search, embeddings, or RAG.

## Ledger Contract

Migration `0023_knowledge_base_write_approval_evidence.sql` creates `knowledge_base.write_approval_evidence`.
Migration `0024_knowledge_base_write_approval_transition_lineage.sql` adds `transition_source_evidence_hash`.
Migration `0025_knowledge_base_write_approval_trusted_article_metadata.sql` adds trusted article metadata for create execution.
Migration `0026_source_object_write_receipts.sql` creates `collabio.source_object_write_receipts` for source-object write receipt persistence.

Each ledger row must carry:

- tenant ID
- approval reference
- operation (`create` or `edit`)
- approval state
- article object ID
- article key
- article title
- expected current version for edits
- proposed version object ID
- proposed version label
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
- source system
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

`POST /v1/admin/kb/articles/write-approvals/refresh-preview` requires tenant context and a tenant admin. It accepts an approved write-approval evidence hash, verifies that the approved evidence and current restore evidence still match, and returns a metadata-only projection containing current source-version evidence hashes, projected source-version evidence hashes, and `projected_restore_evidence_preview_hash`. It does not append ledger rows and does not persist source-version evidence, restore evidence, article metadata, source objects, source text, article bodies, embeddings, or RAG state.

`POST /v1/admin/kb/articles/write-approvals/execution-skeleton` requires tenant context and a tenant admin. It accepts approved ledger evidence, source-object write-guard decision metadata, refresh-preview hashes, and explicit human confirmation. It verifies that the evidence binds to the same article and proposed source version, returns an `execution_plan_hash`, and still blocks execution with `execution_allowed=false`. It does not append ledger rows and does not persist article metadata, source objects, source-version evidence, restore evidence, source text, article bodies, embeddings, or RAG state.

`POST /v1/admin/kb/articles/write-approvals/execute` requires tenant context and a tenant admin. It accepts approved ledger evidence, source-object write-guard decision metadata, refresh-preview hashes, the skeleton execution plan hash, explicit human confirmation, and the proposed source object. The service re-evaluates the guard against the submitted source object, persists the source object, appends a metadata-only source-object write receipt, updates edit/create article/current-version metadata, refreshes source-version evidence and restore evidence, and audits only metadata/hash evidence. Create execution uses article key, title, proposed version label, and source system from approved ledger evidence. It returns `source_object_write_receipt_hash` and keeps RAG and search indexing disabled.

Runtime wiring:

- tests and local in-memory slices use `InMemoryKnowledgeBaseWriteApprovalLedger`.
- the Docker Compose API profile sets `SUITE_KB_WRITE_APPROVAL_LEDGER_BACKEND=postgres` after migrations, so dry-run evidence is inserted into `knowledge_base.write_approval_evidence`.
- the ledger row remains metadata-only and cannot authorize persistence while `approval_state` is `dry_run`.
- `KnowledgeBaseSourceObjectWriteGuard` consumes ledger evidence by exact tenant-scoped evidence hash and returns a metadata-only guard decision before future article/source writes.
- the refresh preview consumes exact tenant-scoped approved ledger evidence and produces hash/count projection only.
- the execution skeleton consumes exact tenant-scoped approved ledger evidence, guard decision metadata, refresh-preview hashes, and human confirmation, then returns a blocked execution plan hash.
- the execute path consumes the same evidence plus the proposed source object, persists a source-object write receipt, commits edit/create writes, and returns refreshed source/restore evidence hashes without enabling RAG or search indexing.
- `PgKnowledgeBaseArticleRepository` provides the PostgreSQL transaction adapter for article metadata, article-version metadata, source-version evidence, and restore evidence.
- `PgSourceObjectWriteReceiptStore` provides the PostgreSQL/RLS receipt adapter for source-object write metadata and hashes.
- `PgSourceObjectRepository` provides the PostgreSQL/RLS source metadata and storage-manifest bridge behind a content-store interface.

Current dry-run persistence inserts the ledger row before any article/source write can exist. Approval transition appends a second lineage-linked ledger row. Refresh preview projects post-write source/restore evidence without persistence. Execution skeleton binds approved evidence, source guard, refresh preview, and human confirmation without persistence. Execute commits approved edit/create writes, records `source_object_write_receipt_hash`, and refreshes source-version plus restore evidence. PostgreSQL-backed article/version/evidence writes now share one database transaction; source-object write receipts, source metadata, and storage manifests are durable metadata evidence. The next boundary is a coordinated Knowledge Base unit-of-work with the production content-store adapter before claiming atomic content persistence.

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

The ledger belongs to the `knowledge_base_content` continuity domain. Source-object write receipts belong to the `postgres_metadata` continuity domain and are referenced by Knowledge Base execution evidence. Backup and restore drills must verify write-approval evidence hashes and source-object write receipt hashes before approved write workflows are allowed.

## Verification

- `tests/test_knowledge_base.py`
- `tests/test_api.py`
- `tests/test_pgvector_migration.py`
- `tests/test_knowledge_base_docs.py`
- `tests/test_knowledge_base_write_approval_ledger.py`
- `tests/test_source_object_write_receipts.py`
- `tests/test_source_object_storage_bridge.py`
