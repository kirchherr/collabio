# Module Implementation Contract

Status: active
Date: 2026-06-12
Contract ID: `module_vertical_slice_contract`

This contract turns the first CRM/ERP read slices into the reusable implementation rule for every future suite module. It is intentionally broader than ERP: knowledge base, LMS, tasks and activities, incident/ticket systems, time tracking, office, mail, search, and later AI extensions must enter through the same gates.

The short rule:

```text
Modules may be optional in product use.
They are never optional in tenancy, authorization, audit, retention, backup, restore, or compliance.
```

## 1. Scope

This contract applies before a module gets persistent state, API routes, workers, imports, search indexes, RAG, AI assist, exports, or decommission behavior.

It is the implementation companion to:

- `docs/modules/MODULE_CHARTER_TEMPLATE.md`
- `docs/modules/CRM_ERP_MODULE_CHARTER.md`
- `docs/ROADMAP.md`
- `COMPLIANCE_MATRIX.md`

The module charter decides why and what. This contract defines how the first safe vertical slice is built.

The API endpoint `GET /v1/platform/modules/families/backlog` exposes this contract as a tenant-scoped, metadata-only backlog view. It does not activate modules, create persistent tasks, run workers, persist domain data, release content, or allow destructive/external actions. Its purpose is to keep knowledge base, LMS, tasks, tickets, time tracking, and later module families aligned with this contract before implementation starts.

## 2. Required Slice Sequence

Every module slice must move through these steps in order:

1. Module charter and scope
2. Feature and subfeature registry
3. Object rules for classification, retention, Legal Hold, KMS, and source behavior
4. Module-aware migration catalog entry with checksum evidence
5. Persistent tables or stores with required metadata
6. RLS or equivalent tenant isolation, plus no hard delete by default
7. Service or repository layer with object authorization
8. API or worker gate with Tenant Context, module state, feature state, and authorization
9. Audit events that log metadata and hashes only
10. Backup, restore, and failover continuity domain
11. Tests for disabled, enabled, suspended, tenant isolation, RLS, retention, Legal Hold, and restore evidence
12. Roadmap, compliance matrix, and module docs update

No module may skip directly from idea to UI or worker execution.

## 3. Required Object Metadata

Every persistent module object must carry these fields or a documented equivalent enforced by the storage boundary:

```text
tenant_id
object_id
object_type
owner_principal_id
created_by
created_at_utc
updated_at_utc
data_classification
retention_policy_id
legal_hold_state
lifecycle_state
kms_key_ref
audit_chain_ref
source_system
schema_version
```

These fields are not presentation concerns. They are part of the record contract and must be available to authorization, audit, retention, restore, export, search, and decommission workflows.

## 4. API And Worker Gates

Every normal API route and feature worker must require:

```text
Tenant Context
+ module gate
+ feature gate
+ object authorization
```

Rules:

- UI hiding is never authorization.
- Disabled modules block normal user workflows.
- Disabled modules must not block retention, Legal Hold, audit, backup, restore, export, or compliance-admin paths for existing data.
- Suspended modules default to compliance-only or explicitly documented read-only behavior.
- Destructive, external, or compliance-relevant actions require explicit human confirmation.
- Worker entry points must use the same module and feature gate as API routes.
- Containerized API and worker paths must use the persistent module registry unless explicitly running an isolated unit test. The persistent store is `collabio.module_catalog` plus `collabio.tenant_modules`; it carries required migration versions and tenant provisioning evidence.
- Compliance workers may discover tenant module rows only through the worker DB role and must still call `ModuleWorkerGate` per tenant before acting.

## 5. Data, Retention, And Legal Hold

Each object type must map to canonical data classes and retention policies before data is imported or accepted from users.

Required decisions:

- data classification
- retention policy ID
- Legal Hold scope
- lifecycle state model
- cryptoshred eligibility
- WORM or GoBD posture where required
- export and e-discovery behavior
- decommission blockers

Hard deletes are forbidden for module business data unless a policy engine, retention state, Legal Hold state, audit evidence, and confirmation workflow explicitly allow the operation.

## 6. Search, RAG, AI, And Voice

Search and AI features stay behind the core suite boundaries:

- Keyword and vector search return candidate IDs only.
- Candidate-only results must pass authoritative ACL validation before source fetch.
- Vector metadata must include `tenant_id`, `object_id`, `object_type`, `classification`, `retention_policy_id`, `legal_hold_state`, and `acl_version`.
- RAG answers must cite source object IDs and source versions.
- Retrieved context, model ID, tool calls, and output hashes must be audit logged.
- Prompt and output bodies must not be written to normal application logs.
- LLM providers must go through the Local LLM Gateway.
- Cloud AI providers require tenant policy enablement.
- LLM output is untrusted until validated or explicitly accepted.
- LLM output must not directly trigger destructive actions.
- Voice input must be push-to-talk or explicitly activated.
- Raw audio must not be stored unless a tenant policy explicitly allows it.

## 7. Backup, Restore, And Failover

Every module with persistent state must declare a continuity domain before the first table, bucket, index, queue, or import staging area is created.

Required evidence:

- backup target
- restore drill expectation
- RPO and RTO
- row-count, object-count, or manifest-count checks
- checksum or manifest hash checks
- tenant isolation check after restore
- module state restore check
- disabled-state restore check
- Legal Hold restore check
- degraded mode behavior

This requirement follows the module forever. New tables, source types, indexes, queues, exports, AI traces, and imports must update the continuity domain in the same change.

## 8. Migrations And Legacy Imports

Module migrations and legacy imports must be repeatable, checksummed, validated, and auditable.

Required controls:

- module-aware migration catalog entry
- startup mismatch blockade for required migrations
- import dry-run before data import
- source metadata discovery before mapping
- quarantine for unknown or unsafe source tables
- row counts and checksums
- manifest hash
- validation report
- explicit cutover or approval point

Legacy import discovery may collect metadata. It must not infer permission to import personal or regulated content.

## 9. Decommissioning

Decommission is a compliance workflow, not a delete button.

Before completion, the module must provide evidence for:

- disabled or suspended normal use
- retention obligations
- Legal Hold state
- export obligations
- audit trail
- backup and restore evidence
- pending imports or migrations
- source-system archive strategy
- explicit approval

If any evidence is missing or blocked, the module remains in `decommission_blocked`.

## 10. First Non-ERP Module Starts

The next module families should start as small read or metadata slices, not as full products:

| Module family | First objects | First slice | Default feature gate | Continuity domain |
| --- | --- | --- | --- | --- |
| Knowledge base | `kb.article`, `kb.article_version` | authorized article metadata/read slice with source versions | `knowledge_base.articles.read` | `knowledge_base_content` |
| LMS | `lms.course`, `lms.enrollment` | course catalog and enrollment status read slice | `lms.courses.read` | `lms_training_records` |
| Tasks and activities | `task.task`, `task.activity` | assigned task/activity read slice | `tasks.items.read` | `task_activity_records` |
| Tickets and incidents | `ticket.ticket`, `ticket.event` | ticket summary read slice with SLA state | `tickets.items.read` | `ticket_incident_records` |
| Time tracking | `time.entry`, `time.approval` | own time-entry read slice with approval state | `time_tracking.entries.read` | `time_tracking_records` |

LMS now has a catalog-registered, not-installed foundation in `docs/modules/LMS_MODULE_CHARTER.md`, `app/suite/platform/lms_module.py`, `app/suite/persistence/migrations/0045_lms_catalog_registration.sql`, `app/suite/persistence/migrations/0046_lms_metadata_schema.sql`, `app/suite/persistence/migrations/0047_lms_package_install_approval_records.sql`, and the metadata-only readiness endpoints `GET /v1/platform/modules/families/lms/catalog-readiness`, `GET /v1/platform/modules/families/lms/restore-drill-evidence`, `GET /v1/platform/modules/families/lms/tenant-admin-package-approval-gate`, `POST /v1/platform/modules/families/lms/tenant-admin-package-approval-records`, `GET /v1/platform/modules/families/lms/package-installation-readiness`, `POST /v1/platform/modules/families/lms/package-installation-execution-boundary`, `POST /v1/platform/modules/families/lms/package-installation-executor-skeleton`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-plan`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-boundary`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-skeleton`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-executor-implementation-review`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-result-contract`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-gate`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-request-boundary`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-executor-runtime-boundary`, and `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-preflight`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-receipt-boundary`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-result-persistence-boundary`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-activation-boundary`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-start-boundary`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-dispatch-boundary`, `POST /v1/platform/modules/families/lms/package-installation-dry-run-execution-worker-boundary`. Package installation, tenant provisioning, LMS business API routes, workers, content runtime, automations, RAG, and AI assist remain separate gates; the executor skeleton, dry-run plan, dry-run execution boundary, dry-run execution skeleton, dry-run executor implementation review, dry-run result contract, dry-run execution gate, dry-run execution request boundary, and dry-run executor runtime boundary and execution preflight and execution receipt boundary, result persistence boundary, execution start boundary, dispatch boundary, and worker boundary only define future execution shapes.

These starts are intentionally narrow. The goal is to prove the same module contract outside CRM/ERP before adding broad business behavior.

## 11. Verification Checklist

Every module slice must include tests or documented evidence for:

- tenant isolation
- module disabled blocks normal API
- module enabled allows authorized API
- feature disabled blocks feature API or worker
- suspended state behavior
- object read authorization
- RLS or equivalent tenant isolation
- metadata presence
- no hard delete default
- retention policy mapping
- Legal Hold behavior
- metadata-only audit
- backup and restore evidence
- decommission blockers
- candidate-only search if search exists
- authoritative ACL validation before RAG source fetch if RAG exists
- Local LLM Gateway and tenant AI policy if AI exists
- explicit voice activation if voice exists
