# Tickets & Incidents Module Charter

Status: productive_vertical_slice_code_ready_controlled_activation_only
Date: 2026-07-29
Module ID: `tickets_incidents`
Module kind: `business_domain`
Owner: platform/product
Implementation contract: `docs/modules/MODULE_IMPLEMENTATION_CONTRACT.md`

## 1. Product Decision

Tickets & Incidents is a native optional suite module for service tickets, incident summaries, event history, SLA state, and later escalation workflows across CRM, ERP, knowledge, LMS, tasks, office, and mail surfaces.

The module is optional in normal use. Compliance obligations for existing ticket and incident records, Legal Hold, retention, backup, restore, export, and audit remain mandatory.

The first productive slice is intentionally small but usable: tenant-scoped ticket creation, owner/operator reads, controlled status transitions, append-only ticket events, SLA metadata, audit evidence, optimistic transition checks, and PostgreSQL RLS persistence. It does not include comments, attachments, notification delivery, escalation automation, external service desk synchronization, RAG, AI assist, voice commands, or destructive workflow actions.

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
| `tickets_incidents.items.read` | on | no | Authorized ticket summary, state, priority, and SLA metadata |
| `tickets_incidents.items.write` | off | yes | Ticket creation and controlled status transitions for ticket operators |
| `tickets_incidents.events.read` | on | no | Authorized append-only ticket and incident event metadata |
| `tickets_incidents.events.write` | off | yes | Initial and transition event writes, atomically coupled to ticket writes |
| `tickets_incidents.compliance_evidence.read` | off | yes | Compliance read path for held or retained ticket/event evidence |
| `tickets_incidents.rag_indexing` | off | yes | Future candidate-only indexing after source resolver and ACL checks |
| `tickets_incidents.ai_assist` | off | yes | Future assist behind tenant AI policy and Local LLM Gateway |

The canonical registry lives in `app/suite/platform/tickets_incidents_module.py`. Write features remain disabled until a tenant-admin-controlled installation and feature approval.
## 4. API And Worker Gates

Every Tickets & Incidents business route requires:

```text
Tenant Context
+ tickets_incidents installed, provisioned, and enabled
+ explicit feature enablement
+ role and object authorization
```

Code-ready productive API:

- `GET /v1/tickets`
- `POST /v1/tickets`
- `GET /v1/tickets/{ticket_id}`
- `GET /v1/tickets/{ticket_id}/events`
- `POST /v1/tickets/{ticket_id}/transitions`

The global catalog remains `not_installed`; these routes therefore return the module gate response in the standard environment. A controlled pilot must install the package, apply migrations `0051` through `0053`, provision and enable the tenant module, and explicitly enable the read/write features. Ticket creation atomically appends a `created` event. Status transitions use an allowed transition matrix plus `expected_status`, atomically update the ticket and append an immutable event, and reject archival under active Legal Hold. Non-operator users can only read tickets they own; ticket operators can read tenant tickets, while writes require an operator role.

Discovery and readiness start with `GET /v1/platform/modules/families/tickets-incidents/catalog-readiness`; the activation control chain remains available under `/v1/platform/modules/families/tickets-incidents/*`. Its final explicit approval endpoint is `POST /v1/platform/modules/families/tickets-incidents/activation-dry-run-execution-approval-records`. The endpoint stores hash/reference metadata only, requires an exact human confirmation statement and tenant-admin role, is tenant scoped and append-only, and does not itself execute a dry-run, install a package, provision tenant state, dispatch a worker, or activate the business API.

Compliance-only later:

- retention evaluation and disposition execution
- Legal Hold administration
- ticket and incident evidence export
- decommission precheck
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

Continuity domain: `ticket_incident_records` (policy domain `service_ticket_records`)

Required evidence:

- module state and feature-flag restore check
- `tickets.ticket_items` row-count and tenant-isolation check
- `tickets.ticket_events` row-count, ordering, immutability, and ticket foreign-key check
- `tickets.activation_dry_run_execution_approval_records` row-count, uniqueness, RLS, and append-only check
- SLA, lifecycle, retention, Legal Hold, KMS, and audit-reference restore checks
- source-version or evidence hashes where external records are referenced
- disabled-state restore check
- restore evidence hash for `ticket_incident_records`

A restored tenant must keep business routes closed until module and feature state are restored and validated. New comments, attachments, escalation rules, notification queues, mail integrations, search indexes, RAG chunks, embeddings, approvals, exports, or workflow engines must update this continuity domain in the same change.
## 8. Migrations And Imports

- `0051_tickets_incidents_catalog_registration.sql` registers the package as `not_installed` and creates no tenant state.
- `0052_tickets_incidents_metadata_schema.sql` creates tenant-scoped ticket and immutable event metadata tables with RLS, no-hard-delete policies, retention, Legal Hold, KMS, audit, and SLA columns.
- `0053_tickets_incidents_dry_run_execution_approval_records.sql` adds the tenant-scoped append-only explicit approval record table and advances the module migration manifest to `0051`/`0052`/`0053`.

The productive service has in-memory and PostgreSQL repository adapters. PostgreSQL writes set tenant context inside each transaction; ticket creation and transitions couple ticket/event persistence atomically. No body, comment, attachment, prompt, output, transcript, audio, password, or raw human confirmation statement is stored in these tables.

The next step is a controlled pilot installation, not another metadata boundary: run migrations, provision one test tenant, explicitly enable all four read/write features, execute the API integration tests and restore drill, then review evidence before widening access.

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

- free-form ticket body or comment storage
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
- `tests/test_tickets_incidents_activation_dry_run_execution_approval_record.py`
- `tests/test_tickets_incidents_service.py`
- `tests/test_tickets_incidents_api.py`
- `tests/test_pgvector_migration.py`
- `tests/test_module_family_backlog.py`
- `tests/test_api.py`
