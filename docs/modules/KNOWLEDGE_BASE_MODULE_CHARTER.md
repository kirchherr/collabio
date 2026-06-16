# Knowledge Base Module Charter

Status: proposed
Date: 2026-06-12
Module ID: `knowledge_base`
Module kind: `business_domain`
Owner: platform/product
Implementation contract: `docs/modules/MODULE_IMPLEMENTATION_CONTRACT.md`

## 1. Product Decision

Knowledge Base is a native optional suite module for governed internal articles, procedure snippets, runbooks, versioned sources, and later RAG citations.

The module is optional in normal use, but compliance obligations for existing knowledge base data remain mandatory.

This charter intentionally starts smaller than a full wiki. The first slices prove tenant-safe article metadata, source-version evidence, and restore evidence before article bodies, editing workflows, approvals, search indexing, or RAG are added.

## 2. Lifecycle And Activation

Supported states:

```text
not_installed
installed
available
provisioning
enabled
disabled
suspended
decommission_requested
decommission_blocked
decommissioned
```

Disabled stops normal article browsing and editing. Disabled does not stop retention, Legal Hold, audit, backup, restore, export, decommission evidence, or compliance-only administration for existing data.

## 3. Feature Flags

| Feature ID | Default | Requires approval | Notes |
| --- | --- | --- | --- |
| `knowledge_base.articles.read` | on | no | Metadata-only article list and current version references |
| `knowledge_base.articles.write` | off | yes | Future authoring and approval workflow |
| `knowledge_base.rag_indexing` | off | yes | Future candidate-only indexing after source resolver and ACL checks |
| `knowledge_base.ai_assist` | off | yes | Future assist behind tenant AI policy and Local LLM Gateway |

## 4. API And Worker Gates

Every normal Knowledge Base route must require:

```text
Tenant Context
+ knowledge_base enabled
+ feature permission
+ object authorization
```

Initial API:

- `GET /v1/kb/articles`
- `POST /v1/admin/kb/runtime/activate`
- `POST /v1/admin/kb/runtime/reconcile`
- `GET /v1/admin/kb/evidence`
- `POST /v1/admin/kb/articles/write-dry-run`
- `POST /v1/admin/kb/articles/write-approvals/approve`
- `POST /v1/admin/kb/articles/write-approvals/refresh-preview`
- `POST /v1/admin/kb/articles/write-approvals/execution-skeleton`
- `POST /v1/admin/kb/articles/write-approvals/execute`

`GET /v1/admin/kb/evidence` is a tenant-admin compliance API. It remains available through the compliance module gate while the module is disabled, suspended, or in an active decommission workflow. It returns source-version evidence and restore evidence only, not article bodies or source text.

`POST /v1/admin/kb/runtime/activate` is a tenant-admin compliance API for deployment activation. It requires explicit human confirmation, validates the configured S3-compatible provider profile, source-content recovery evidence, bound restore-drill hash, and `knowledge_base_production_write_deployment_gate.v1`, then persists metadata-only `knowledge_base_runtime_activation.v1` evidence for the current tenant. Request-time Knowledge Base service resolution uses this tenant-scoped activation; it does not use a process-wide runtime tenant.

`POST /v1/admin/kb/runtime/reconcile` is a tenant-admin compliance API and worker trigger. It rebuilds provider-profile, source-content-recovery, and production-gate evidence for the current tenant's active runtime activation. If operational state drifts, it appends `knowledge_base_runtime_reconciliation_evidence.v1` and deactivates the runtime activation so the write path cannot continue on stale evidence.

`docker compose run --rm kb-runtime-reconciler` runs the same reconciliation as a metadata-only compliance worker. `KnowledgeBaseRuntimeReconciliationTenantSelector` selects tenants from Knowledge Base module status plus active runtime activations, `KnowledgeBaseRuntimeReconciliationRunner` writes a `knowledge_base_runtime_reconciliation_run_report.v1` with retry contract, alert severity, selected/skipped tenants, restore-drill report hashes, and runbook evidence. The worker uses the compliance worker gate and does not expose source text, article bodies, prompts, outputs, embeddings, or raw object payloads.

`POST /v1/admin/kb/articles/write-dry-run` validates a write/edit approval command, writes an audit event, and appends metadata-only approval evidence to the write-approval ledger. It does not persist article metadata, source objects, source text, article bodies, embeddings, or RAG index state. It returns command hashes and required evidence for the source-object write guard.

`POST /v1/admin/kb/articles/write-approvals/approve` transitions an existing dry-run ledger row to a new append-only `approved_for_write` ledger row. It requires a new human approval reference, verifies that the current restore evidence and expected version still match the dry-run evidence, and still does not persist article metadata, source objects, source text, article bodies, embeddings, or RAG index state.

`POST /v1/admin/kb/articles/write-approvals/refresh-preview` accepts approved write-approval evidence and returns a metadata-only source/restore evidence projection. It verifies the approved ledger row, current restore evidence, and expected version, then returns current and projected source-version evidence hashes plus a `projected_restore_evidence_preview_hash`. It does not append ledger rows, persist source-version evidence, persist restore evidence, write article metadata, write source objects, index, embed, or update RAG state.

`POST /v1/admin/kb/articles/write-approvals/execution-skeleton` accepts approved write-approval evidence, a metadata-only source-object write-guard decision, the refresh-preview hashes, and an explicit human confirmation reference. It verifies that those inputs bind to the same tenant, article, proposed source version, and restore evidence, then returns an `execution_plan_hash`. It still sets `execution_allowed=false` and does not persist article metadata, source objects, source-version evidence, restore evidence, embeddings, indexes, or RAG state.

`POST /v1/admin/kb/articles/write-approvals/execute` accepts the same approved evidence chain plus the authoritative proposed `SourceObjectRecord`. For edit/create operations it re-evaluates the source-object write guard against that record, verifies the skeleton `execution_plan_hash`, and commits through `KnowledgeBaseWriteUnitOfWork`. The unit of work appends a metadata-only source-object write receipt, persists the source object/source metadata/storage manifest, updates article/current-version metadata, refreshes source-version evidence and restore evidence, and returns `refreshed_restore_evidence_hash` plus `source_object_write_receipt_hash` with `write_unit_of_work_committed=true` and `write_unit_of_work_contract`. Create execution uses article key, title, proposed version label, and source system from trusted approval evidence instead of trusting execution-time metadata. It does not store source text in audit metadata, receipts, or responses, and it keeps search indexing, embeddings, and RAG state disabled.

`PgKnowledgeBaseArticleRepository` is the PostgreSQL transaction adapter for article/version/evidence metadata. Its `apply_write` transaction locks tenant articles, verifies create/edit preconditions, writes `knowledge_base.articles`, `knowledge_base.article_versions`, `knowledge_base.source_version_evidence`, and `knowledge_base.restore_evidence` together, and rolls the transaction back on conflicts. It deliberately does not store source text or article bodies. `PgSourceObjectWriteReceiptStore` supplies the durable metadata-only source-object write boundary, and `PgSourceObjectRepository` supplies the PostgreSQL source metadata/storage-manifest bridge. `PostgresKnowledgeBaseWriteUnitOfWork` coordinates those adapters inside one shared PostgreSQL metadata transaction with `write_unit_of_work_transaction_scope=shared_postgres_metadata_transaction`, and hash-binds source metadata to the persisted receipt. Because source bytes are still written through the content-store interface before metadata commit, the execution response keeps `source_content_recovery_required=true` until `source_object_content_recovery_evidence.v1` shows `api_wiring_allowed=true` for production API writes. When clean recovery evidence, S3/MinIO provider-profile evidence, and bound restore-drill evidence are supplied through `knowledge_base_production_write_deployment_gate.v1`, execution returns `source_content_recovery_evidence_hash`, `production_write_deployment_gate_evidence_hash`, and `source_content_recovery_required=false`. `KnowledgeBaseArticleServiceResolver` selects the activated Postgres/S3 service per request tenant from persisted runtime activation evidence and falls back to the default service for tenants without activation.

`KnowledgeBaseSourceObjectWriteGuard` is the mandatory precondition for future article/source mutations. It validates tenant-scoped ledger evidence, approval state, expected current version, source-object metadata guard results, proposed source-version evidence hash, current restore evidence hash, retention policy, and Legal Hold state before a write can be considered.

Current and future workers:

- runtime reconciliation worker (`docker compose run --rm kb-runtime-reconciler`)
- article source extraction worker
- version approval worker
- candidate-only search indexing worker
- RAG citation rebuild worker

Destructive, external, or compliance-relevant actions require explicit human confirmation.

## 5. Persistent Objects

| Object type | Data class | Retention policy | Legal Hold scope | KMS expectation | Source object? |
| --- | --- | --- | --- | --- | --- |
| `kb.article` | `internal` | `rp-standard` | article and related versions | tenant + class | yes |
| `kb.article_version` | `internal` | `rp-standard` | version and article family | tenant + class | yes |

Every object must carry the required metadata from `docs/modules/MODULE_IMPLEMENTATION_CONTRACT.md`, including tenant, object ID, object type, owner, classification, retention policy, Legal Hold state, lifecycle state, KMS key reference, audit-chain reference, source system, and schema version.

Article bodies are not stored in the first slice. Current article versions are references for future source-object retrieval and RAG citation, not permission to bypass ACL validation.

Current article versions must resolve to authoritative source-object records before the module can move toward authoring or RAG. The source-version evidence captures source object ID, source version ID, manifest hash, content hash, ACL version, classification, retention policy, Legal Hold state, and an evidence hash without storing article body text.

## 6. Search, RAG, AI, And Voice

Initial state:

- keyword search: off
- vector search: off
- RAG: off
- AI assist: off
- voice: off

Future search and RAG must return candidate IDs only, validate authoritative ACLs before source fetch, cite `kb.article` and `kb.article_version` object IDs and versions, and audit retrieved context, model ID, tool calls, and output hashes without writing prompt or output bodies to normal logs.

AI providers must go through the Local LLM Gateway. Cloud AI provider use requires tenant policy enablement.

## 7. Backup, Restore, And Failover

Continuity domain: `knowledge_base_content`

Required evidence:

- module state restore check
- article row-count check
- article-version row-count check
- source-version evidence row-count check
- source-version evidence hashes
- manifest or checksum check
- tenant isolation check after restore
- disabled-state restore check
- Legal Hold restore check
- restore evidence hash for `knowledge_base_content`

New article body storage, source indexes, RAG chunks, embeddings, approvals, or exports must update this continuity domain in the same change.

## 8. Migrations And Imports

Initial migrations:

- `0021_knowledge_base_articles.sql`
- `0022_knowledge_base_source_restore_evidence.sql`
- `0023_knowledge_base_write_approval_evidence.sql`
- `0024_knowledge_base_write_approval_transition_lineage.sql`
- `0025_knowledge_base_write_approval_trusted_article_metadata.sql`
- `0026_source_object_write_receipts.sql`
- `0027_source_object_metadata_storage_bridge.sql`
- `0028_knowledge_base_runtime_activation.sql`
- `0029_knowledge_base_runtime_reconciliation.sql`

The first migration creates `knowledge_base.articles` and `knowledge_base.article_versions` with RLS, no hard delete, required metadata, KMS references, audit-chain references, source-version references, and no body text columns.

The second migration creates append-only tenant-scoped `knowledge_base.source_version_evidence` and `knowledge_base.restore_evidence` tables. These tables are RLS-protected, grant no hard delete, and are the required precondition for later write/edit or RAG expansion.

The third migration creates append-only tenant-scoped `knowledge_base.write_approval_evidence`. Future article/source writes must first persist approval evidence in this ledger, pass the source-object write guard, and refresh source-version plus restore evidence.

The fourth migration adds `transition_source_evidence_hash` so non-dry-run approval states must point back to the dry-run ledger evidence that was approved. This keeps state transitions append-only and auditable.

The fifth migration adds trusted create metadata to `knowledge_base.write_approval_evidence`: article key, title, proposed version label, and source system. This prevents create execution from introducing caller-supplied article metadata after approval.

The refresh-preview, execution-skeleton, and current in-memory execute endpoints are runtime-only until execution. `PgKnowledgeBaseArticleRepository` consumes the same approved evidence contract and persists article/version/source-version/restore metadata in one database transaction. `0026_source_object_write_receipts.sql` adds the durable metadata-only receipt boundary for the proposed source object before article/evidence metadata is committed. `0027_source_object_metadata_storage_bridge.sql` adds source metadata and storage-manifest persistence without storing content bodies. `0028_knowledge_base_runtime_activation.sql` stores one active tenant-scoped `knowledge_base_runtime_activation.v1` record with provider-profile, source-content-recovery, and production-gate evidence JSON plus hashes. `0029_knowledge_base_runtime_reconciliation.sql` stores append-only reconciliation evidence and records runtime deactivation metadata when drift is detected. `KnowledgeBaseRuntimeReconciliationRunner` adds the worker runbook layer on top: tenant selection, retry attempts, alert severity, restore-drill hashes, and `knowledge_base_runtime_reconciliation_run_report.v1` stay metadata-only and can be used by scheduled jobs or incident runbooks. `PostgresKnowledgeBaseWriteUnitOfWork` now coordinates receipt, source metadata, storage manifest, article/version metadata, source-version evidence, and restore evidence in a shared PostgreSQL metadata transaction. `source_object_content_recovery_evidence.v1` verifies content-store inventory against storage manifests, records orphan/missing counts, binds a restore-drill report hash, and gates production API wiring through `source_content_recovery_evidence_hash`. `S3CompatibleSourceObjectContentStore` supplies the S3/MinIO-compatible content-store adapter port with Object Lock/WORM capability checks; `Boto3S3CompatibleObjectStoreClient` supplies the concrete MinIO/AWS-compatible SDK binding behind that port. `s3_compatible_provider_profile_evidence.v1` proves provider capability readiness. `knowledge_base_production_write_deployment_gate.v1` requires clean recovery evidence, ready provider-profile evidence, and bound restore-drill evidence before `production_write_deployment_gate_evidence_hash` can unlock Postgres UoW API wiring. API wiring must not claim atomic source-object content persistence until this evidence is clean for the production content store.

Legacy import is out of scope for the first slice. Future import must run metadata discovery, dry-run validation, row counts, checksums, quarantine, and approval before content import.

## 9. Decommissioning

Decommissioning requires:

- disabled or suspended normal use
- retention evaluation
- Legal Hold check
- export/archive decision
- audit evidence
- backup/restore evidence
- source-version disposition evidence
- explicit approval

Missing or blocked evidence leaves the module in `decommission_blocked`.

## 10. Verification

- `tests/test_knowledge_base.py`
- `tests/test_api.py`
- `tests/test_pgvector_migration.py`
- `tests/test_knowledge_base_docs.py`
