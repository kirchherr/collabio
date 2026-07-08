# Tickets & Incidents Module Charter

Status: catalog_registered_metadata_only
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

No Tickets & Incidents business API route is enabled by this charter. `GET /v1/platform/modules/families/tickets-incidents/catalog-readiness` exposes only the platform catalog-readiness boundary. The module is registered in the platform catalog as `not_installed`; migration evidence, tenant state, storage, business routes, and workers must happen in later explicit gates.

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

`0051_tickets_incidents_catalog_registration.sql` registers the module as `not_installed` and creates no tenant state, Tickets & Incidents schema, ticket/event tables, content, worker queue, or business API runtime. The first future storage migration must be preceded by migration evidence and restore planning.

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
- `tests/test_pgvector_migration.py`
- `tests/test_module_family_backlog.py`
- `tests/test_api.py`
