# Tickets & Incidents Module Charter

Status: activation_dry_run_execution_final_readiness_gate_ready_metadata_only
Date: 2026-07-07
Module ID: `tickets_incidents`
Module kind: `business_domain`
Owner: platform/product
Implementation contract: `docs/modules/MODULE_IMPLEMENTATION_CONTRACT.md`

## 1. Product Decision

Tickets & Incidents is a native optional suite module for service tickets, incident summaries, event history, SLA state, and later escalation workflows across CRM, ERP, knowledge, LMS, tasks, office, and mail surfaces.

The module is optional in normal use. Compliance obligations for existing ticket and incident records, Legal Hold, retention, backup, restore, export, and audit remain mandatory.

The first slice is intentionally small: ticket summary metadata with SLA state and ticket event metadata. It does not include ticket creation, comments, attachments, notification delivery, escalation automation, external service desk synchronization, RAG, AI assist, voice commands, or destructive workflow actions.

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

Disabled stops normal ticket and event browsing. Disabled does not stop retention, Legal Hold, audit, backup, restore, export, decommission evidence, or compliance-only administration for existing ticket and incident records.

## 3. Feature Flags

| Feature ID | Default | Requires approval | Notes |
| --- | --- | --- | --- |
| `tickets.items.read` | on | no | Ticket summary metadata, state, priority, and SLA state |
| `tickets.events.read` | on | no | Ticket and incident event-log metadata for authorized objects |
| `tickets.compliance_evidence.read` | off | yes | Compliance read path for held or retained ticket/event evidence |
| `tickets.rag_indexing` | off | yes | Future candidate-only indexing after source resolver and ACL checks |
| `tickets.ai_assist` | off | yes | Future assist behind tenant AI policy and Local LLM Gateway |

The canonical registry lives in `app/suite/platform/tickets_incidents_module.py`.

## 4. API And Worker Gates

Every future normal Tickets & Incidents route must require:

```text
Tenant Context
+ tickets_incidents enabled
+ feature permission
+ object authorization
```

Initial planned API:

- `GET /v1/tickets/items`
- `GET /v1/tickets/events`

Compliance-only later:

- retention evaluation
- Legal Hold enforcement
- ticket evidence export
- incident evidence export
- decommission precheck

No Tickets & Incidents business API route is enabled by this charter. `GET /v1/platform/modules/families/tickets-incidents/catalog-readiness` exposes only the platform catalog-readiness boundary; `GET /v1/platform/modules/families/tickets-incidents/migration-evidence-gate` exposes the metadata-only storage-preparation boundary; `GET /v1/platform/modules/families/tickets-incidents/storage-migration-evidence` exposes the metadata-only schema-evidence result for migration `0052`; `GET /v1/platform/modules/families/tickets-incidents/restore-drill-evidence` exposes the metadata-only restore evidence hash for `ticket_incident_records`; `GET /v1/platform/modules/families/tickets-incidents/tenant-admin-activation-approval-gate` exposes the metadata-only approval boundary before any human approval record; `POST /v1/platform/modules/families/tickets-incidents/tenant-admin-activation-approval-records` records the explicit tenant-admin approval as metadata-only evidence while still executing no activation path; `POST /v1/platform/modules/families/tickets-incidents/activation-execution-boundary` reviews the activation execution boundary and binds the approval gate, approval record, restore evidence, change request, idempotency key, and audit chain as metadata-only evidence without executing activation; `POST /v1/platform/modules/families/tickets-incidents/activation-executor-skeleton` prepares the non-executing activation executor skeleton while deferring business API activation, worker activation, tenant state creation, and ticket content payloads; `POST /v1/platform/modules/families/tickets-incidents/activation-dry-run-plan` prepares the non-executing activation dry-run plan and requires a future dry-run execution boundary before any activation path; `POST /v1/platform/modules/families/tickets-incidents/activation-dry-run-execution-boundary` reviews that boundary while still executing no dry-run, no activation, no worker, no business API, and no result persistence; `POST /v1/platform/modules/families/tickets-incidents/activation-dry-run-execution-skeleton` prepares the non-executing dry-run execution skeleton while deferring executor implementation, dry-run result contract, result persistence, worker/business API runtime, and tenant activation; `POST /v1/platform/modules/families/tickets-incidents/activation-dry-run-executor-implementation-review` reviews the non-executing dry-run executor implementation boundary and still defers result contract, result persistence, worker/business API runtime, dry-run execution, and tenant activation; `POST /v1/platform/modules/families/tickets-incidents/activation-dry-run-result-contract` defines the non-executing dry-run result receipt contract while still deferring dry-run execution, result persistence, worker/business API runtime, tenant state creation, and module activation; `POST /v1/platform/modules/families/tickets-incidents/activation-dry-run-execution-gate` prepares the metadata-only activation dry-run execution gate, requires a future request boundary, and still performs no dry-run execution, result persistence, worker/business API activation, tenant module state creation, tenant provisioning, or module activation; `POST /v1/platform/modules/families/tickets-incidents/activation-dry-run-execution-request-boundary` prepares the metadata-only dry-run execution request boundary, binds the execution-gate hash, requires a future executor runtime boundary, and still performs no dry-run execution, result persistence, worker/business API activation, tenant module state creation, tenant provisioning, or module activation; `POST /v1/platform/modules/families/tickets-incidents/activation-dry-run-executor-runtime-boundary` prepares the metadata-only dry-run executor runtime boundary, binds the request-boundary hash, requires a future dry-run execution preflight, and still performs no dry-run execution, result persistence, worker/business API activation, tenant module state creation, tenant provisioning, or module activation; `POST /v1/platform/modules/families/tickets-incidents/activation-dry-run-execution-preflight` prepares the metadata-only dry-run execution preflight, binds the executor-runtime-boundary hash, requires a future dry-run execution receipt boundary, and still performs no dry-run execution, result persistence, worker/business API activation, tenant module state creation, tenant provisioning, or module activation; `POST /v1/platform/modules/families/tickets-incidents/activation-dry-run-execution-receipt-boundary` prepares the metadata-only dry-run execution receipt boundary, binds the preflight hash, requires a future dry-run result persistence boundary, and still performs no dry-run execution, result persistence, worker/business API activation, tenant module state creation, tenant provisioning, or module activation. `POST /v1/platform/modules/families/tickets-incidents/activation-dry-run-result-persistence-boundary` prepares the metadata-only dry-run result persistence boundary, binds the execution receipt boundary hash, requires a future dry-run execution activation boundary, and still performs no dry-run execution, result persistence, worker/business API activation, tenant module state creation, tenant provisioning, or module activation. `POST /v1/platform/modules/families/tickets-incidents/activation-dry-run-execution-activation-boundary` prepares the metadata-only dry-run execution activation boundary, binds the result persistence boundary hash, requires a future dry-run execution start boundary, and still performs no dry-run execution, result persistence, worker/business API activation, tenant module state creation, tenant provisioning, or module activation. `POST /v1/platform/modules/families/tickets-incidents/activation-dry-run-execution-start-boundary` prepares the metadata-only dry-run execution start boundary, binds the execution activation boundary hash, requires a future dry-run execution dispatch boundary, and still performs no dry-run execution, result persistence, worker/business API activation, tenant module state creation, tenant provisioning, or module activation. `POST /v1/platform/modules/families/tickets-incidents/activation-dry-run-execution-dispatch-boundary` prepares the metadata-only dry-run execution dispatch boundary, binds the start boundary hash, requires a future dry-run execution worker boundary, and still performs no scheduler activation, no scheduler job creation, no worker dispatch, no worker queue enqueue, no worker execution, no dry-run execution, no result persistence, no business API activation, no tenant module state creation, no tenant provisioning, and no module activation. `POST /v1/platform/modules/families/tickets-incidents/activation-dry-run-execution-worker-boundary` prepares the metadata-only dry-run execution worker boundary, binds the dispatch boundary hash, requires a future dry-run execution final readiness gate, and still performs no worker image resolution, no image pull, no digest lookup, no scheduler job, no worker dispatch, no worker queue enqueue, no worker execution, no dry-run execution, no result persistence, no business API activation, no tenant module state creation, no tenant provisioning, and no module activation. `POST /v1/platform/modules/families/tickets-incidents/activation-dry-run-execution-final-readiness-gate` prepares the metadata-only final readiness gate, binds the worker boundary hash, requires a future separate dry-run execution approval boundary, records no explicit execution approval, and still performs no worker image resolution, no image pull, no digest lookup, no scheduler job, no worker dispatch, no worker queue enqueue, no worker execution, no dry-run execution, no result persistence, no business API activation, no tenant module state creation, no tenant provisioning, and no module activation. The module is registered in the platform catalog as `not_installed`; tenant state, business routes, workers, and content must happen in later explicit gates.

## 5. Persistent Objects

First planned object types:

| Object type | Data class | Retention policy | Legal Hold scope | KMS expectation | Source object? |
| --- | --- | --- | --- | --- | --- |
| `ticket.ticket` | `personal` | `rp-standard` | requester, assignee, linked business object, incident owner | tenant + class | yes |
| `ticket.event` | `personal` | `rp-standard` | actor, related ticket, linked business object | tenant + class | yes |

Every object must carry the required metadata from `docs/modules/MODULE_IMPLEMENTATION_CONTRACT.md`, including tenant, object ID, object type, owner, classification, retention policy, Legal Hold state, lifecycle state, KMS key reference, audit-chain reference, source system, and schema version.

The canonical first object-rule contract lives in `app/suite/platform/tickets_incidents_module.py`.

## 6. Search, RAG, AI, And Voice

Initial state:

- keyword search: off
- vector search: off
- RAG: off
- AI assist: off
- voice: off

Future search and RAG must return candidate IDs only, validate authoritative ACLs before source fetch, cite `ticket.ticket`, `ticket.event`, and source versions, and audit retrieved context, model ID, tool calls, and output hashes without writing prompt or output bodies to normal logs.

AI providers must go through the Local LLM Gateway. Cloud AI provider use requires tenant policy enablement.

Voice input is not part of the first Tickets & Incidents slice.

## 7. Backup, Restore, And Failover

Continuity domain: `ticket_incident_records`

Required evidence:

- module state restore check
- ticket row-count check
- ticket event row-count check
- SLA state restore check
- source-version or evidence hashes where external records are referenced
- tenant isolation check after restore
- disabled-state restore check
- Legal Hold restore check
- restore evidence hash for `ticket_incident_records`

New comments, attachments, escalation rules, notification queues, mail integrations, search indexes, RAG chunks, embeddings, approvals, exports, or workflow engines must update this continuity domain in the same change.

## 8. Migrations And Imports

`0051_tickets_incidents_catalog_registration.sql` registers the module as `not_installed` and creates no tenant state, Tickets & Incidents schema, ticket/event tables, content, worker queue, or business API runtime. `0052_tickets_incidents_metadata_schema.sql` creates the tenant-scoped `tickets.ticket_items` and `tickets.ticket_events` metadata tables, RLS policies, no-hard-delete policies, retention/Legal Hold/KMS/audit columns, and module-catalog migration registration while still creating no tenant module state, business API route, worker, message body, attachment payload, RAG index, or AI/voice runtime. `GET /v1/platform/modules/families/tickets-incidents/migration-evidence-gate` confirms the `0051`/`0052` boundary. `GET /v1/platform/modules/families/tickets-incidents/storage-migration-evidence` verifies the metadata schema SQL, migration registration, backup evidence, and no-content-payload constraints. `GET /v1/platform/modules/families/tickets-incidents/restore-drill-evidence` binds those checks into a tenant-scoped restore-evidence hash while still allowing no tenant provisioning, business API, worker, content, search, RAG, AI, or voice runtime. The activation execution boundary review, activation executor skeleton, activation dry-run plan, activation dry-run execution boundary review, activation dry-run execution skeleton, activation dry-run executor implementation review, activation dry-run result contract, activation dry-run execution gate, activation dry-run execution request boundary, activation dry-run executor runtime boundary, activation dry-run execution preflight, activation dry-run execution receipt boundary, activation dry-run result persistence boundary, and activation dry-run execution activation boundary, activation dry-run execution start boundary, activation dry-run execution dispatch boundary, and activation dry-run execution worker boundary are metadata-only ready and still permit no tenant provisioning, business API activation, scheduler job, worker dispatch, worker queue, worker execution, dry-run execution, result persistence, or module activation path. The next gate is a future activation dry-run execution final readiness gate before any executable activation path.

Future imports must run metadata discovery, dry-run validation, row counts, checksums, quarantine, and approval before content import, SLA recalculation, escalation, or workflow activation.

## 9. Decommissioning

Decommissioning requires:

- disabled or suspended normal use
- retention evaluation
- Legal Hold check
- export/archive decision
- audit evidence
- backup/restore evidence
- linked-object dependency review
- explicit approval

Missing or blocked evidence leaves the module in `decommission_blocked`.

## 10. Explicit Non-Goals For The First Slice

- ticket creation or updates
- comments
- attachments
- notification sending
- SLA recalculation
- escalation workflow execution
- external service desk synchronization
- mail send or calendar integration
- cross-module writes
- RAG answer generation
- AI ticket generation
- voice commands
- destructive remediation actions

## 11. Verification

- `tests/test_tickets_incidents_module_foundation.py`
- `tests/test_tickets_incidents_catalog_readiness.py`
- `tests/test_tickets_incidents_migration_evidence_gate.py`
- `tests/test_tickets_incidents_storage_migration_evidence.py`
- `tests/test_tickets_incidents_restore_drill_evidence.py`
- `tests/test_tickets_incidents_tenant_admin_activation_approval_gate.py`
- `tests/test_tickets_incidents_tenant_admin_activation_approval_record.py`
- `tests/test_tickets_incidents_activation_execution_boundary.py`
- `tests/test_tickets_incidents_activation_executor_skeleton.py`
- `tests/test_tickets_incidents_activation_dry_run_plan.py`
- `tests/test_tickets_incidents_activation_dry_run_execution_boundary.py`
- `tests/test_tickets_incidents_activation_dry_run_execution_skeleton.py`
- `tests/test_tickets_incidents_activation_dry_run_executor_implementation_review.py`
- `tests/test_tickets_incidents_activation_dry_run_result_contract.py`
- `tests/test_tickets_incidents_activation_dry_run_execution_gate.py`
- `tests/test_tickets_incidents_activation_dry_run_execution_request_boundary.py`
- `tests/test_tickets_incidents_activation_dry_run_executor_runtime_boundary.py`
- `tests/test_tickets_incidents_activation_dry_run_execution_preflight.py`
- `tests/test_tickets_incidents_activation_dry_run_execution_receipt_boundary.py`
- `tests/test_tickets_incidents_activation_dry_run_result_persistence_boundary.py`
- `tests/test_tickets_incidents_activation_dry_run_execution_activation_boundary.py`
- `tests/test_pgvector_migration.py`
- `tests/test_module_family_backlog.py`
- `tests/test_api.py`
