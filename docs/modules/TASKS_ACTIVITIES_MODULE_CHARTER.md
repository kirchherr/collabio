# Tasks & Activities Module Charter

Status: operational assignment and task lifecycle slice
Date: 2026-09-17
Module ID: `tasks_activities`
Module kind: `business_domain`
Owner: platform/product
Implementation contract: `docs/modules/MODULE_IMPLEMENTATION_CONTRACT.md`

## 1. Product Decision

Tasks & Activities is a native optional suite module for assigned work, follow-up items, activity history, and later workflow automation across CRM, ERP, knowledge, LMS, tickets, and office/mail surfaces.

The module is optional in normal use. Compliance obligations for existing task and activity records, Legal Hold, retention, backup, restore, export, and audit remain mandatory.

The productive scope includes atomic task creation with one initial activity, authoritative ACL grants,
an append-only metadata receipt, ACL-filtered reads, controlled lifecycle transitions, and versioned
assignment/due-date amendments. Every transition or amendment atomically appends an activity and a
per-task hash-chain record; the base task row remains immutable. Reassignment validates an active
tenant principal, revokes only the prior process-generated assignment grant, preserves independent
manual grants, and grants the new assignee access in the same transaction. Cancellation and archival
require an exact human confirmation whose hash, never the raw statement, is persisted. Comments, file
attachments, notifications, workflow automations, calendar sync, email send, RAG, AI assist, voice
commands, and external integrations remain outside this slice.

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

Disabled stops normal task and activity browsing. Disabled does not stop retention, Legal Hold, audit, backup, restore, export, decommission evidence, or compliance-only administration for existing task and activity records.

## 3. Feature Flags

| Feature ID | Default | Requires approval | Notes |
| --- | --- | --- | --- |
| `tasks_activities.tasks.items.read` | on | no | Assigned task metadata and lifecycle state |
| `tasks_activities.tasks.activities.read` | on | no | Activity-log metadata for authorized objects and readable linked tasks |
| `tasks_activities.tasks.compliance_evidence.read` | off | yes | Compliance read path for held or retained task/activity evidence |
| `tasks_activities.tasks.workflow.write` | off | yes | Atomic creation plus append-only lifecycle transitions and activity evidence |
| `tasks_activities.tasks.rag_indexing` | off | yes | Future candidate-only indexing after source resolver and ACL checks |
| `tasks_activities.tasks.ai_assist` | off | yes | Future assist behind tenant AI policy and Local LLM Gateway |

The canonical registry lives in `app/suite/platform/tasks_activities_module.py`.

## 4. API And Worker Gates

Every future normal Tasks & Activities route must require:

```text
Tenant Context
+ tasks_activities enabled
+ feature permission
+ object authorization
```

Productive API:

- `POST /v1/tasks/items`
- `POST /v1/tasks/items/{task_object_id}/transitions`
- `POST /v1/tasks/items/{task_object_id}/amendments`
- `GET /v1/tasks/items`
- `GET /v1/tasks/activities`

Compliance-only later:

- retention evaluation
- Legal Hold enforcement
- activity evidence export
- decommission precheck

The business routes require a provisioned and enabled tenant module. Creation, transitions, and amendments
additionally require `tasks_activities.tasks.workflow.write`, both read dependencies, an operator
role, and authoritative task access. Transition commands use optimistic expected-state checks and an
allowed state graph. Amendment commands compare the expected assignee and due date and are rejected
for completed, cancelled, or archived tasks. The catalog-readiness endpoint remains metadata-only and
performs no tenant provisioning or activation. The transition and amendment routes are outside the
currently approved seven-operation productivity pilot and therefore remain fail-closed until a fresh
traffic-scope approval includes them.

`GET /v1/platform/modules/families/tasks-activities/catalog-readiness` remains the metadata-only package and tenant-state discovery boundary.

## 5. Persistent Objects

First planned object types:

| Object type | Data class | Retention policy | Legal Hold scope | KMS expectation | Source object? |
| --- | --- | --- | --- | --- | --- |
| `task.task` | `personal` | `rp-standard` | assignee, owner, linked business object | tenant + class | yes |
| `task.activity` | `personal` | `rp-standard` | actor, related task, linked business object | tenant + class | yes |

Every object must carry the required metadata from `docs/modules/MODULE_IMPLEMENTATION_CONTRACT.md`, including tenant, object ID, object type, owner, classification, retention policy, Legal Hold state, lifecycle state, KMS key reference, audit-chain reference, source system, and schema version.

`tasks.lifecycle_transitions` is internal compliance evidence linked to `task.task` and the appended
`task.activity`. Its tenant-local sequence and previous-hash pointer are enforced by a PostgreSQL
trigger in addition to service validation. Current task state is a projection of the latest valid
transition; `tasks.items.lifecycle_state` is not updated.

`tasks.amendments` is the append-only source of truth for current assignment and due date after task
creation. Its full before/after values, sequence and previous-hash pointer are database validated.
Current assignment and due date are projections of the latest valid amendment; the base task row is
not updated.

The canonical first object-rule contract lives in `app/suite/platform/tasks_activities_module.py`.

## 6. Search, RAG, AI, And Voice

Initial state:

- keyword search: off
- vector search: off
- RAG: off
- AI assist: off
- voice: off

Future search and RAG must return candidate IDs only, validate authoritative ACLs before source fetch, cite `task.task`, `task.activity`, and source versions, and audit retrieved context, model ID, tool calls, and output hashes without writing prompt or output bodies to normal logs.

AI providers must go through the Local LLM Gateway. Cloud AI provider use requires tenant policy enablement.

Voice input is not part of the first Tasks & Activities slice.

## 7. Backup, Restore, And Failover

Continuity domain: `task_activity_records`

Required evidence:

- module state restore check
- task row-count check
- activity row-count check
- source-version or evidence hashes where external records are referenced
- tenant isolation check after restore
- disabled-state restore check
- Legal Hold restore check
- restore evidence hash for `task_activity_records`
- exact task, activity, transition, amendment, ACL and creation-receipt row counts
- Forced RLS and append-only policy verification on all five Tasks tables
- presence of the database transition-, amendment-chain, and shared task-mutation serialization triggers after restore
- `collabio_authz_admin` write-without-update/delete and `collabio_app` read-only grants
- source/target equality through `postgres_restore_drill_report.v1`

New task comments, file attachments, automation rules, notification queues, calendar/mail integrations, search indexes, RAG chunks, embeddings, approvals, exports, or workflow engines must update this continuity domain in the same change.

## 8. Migrations And Imports

`0050_tasks_activities_catalog_registration.sql` introduced the metadata-only package entry.
`0059_tasks_activities_productive_slice.sql` creates the governed `tasks.items`, `tasks.activities`,
and `tasks.creation_receipts` tables with Forced RLS, append-only policies, minimal service-role
grants, and updates the package to `installed`. `0077_tasks_lifecycle_transitions.sql` adds the
append-only transition chain and database validation trigger and advances the package contract to
`0.3.0`. `0079_task_assignment_due_date_amendments.sql` adds append-only assignment/due-date
amendments, database chain and ACL validation, and advances the package contract to `0.4.0`.
`0081_task_mutation_serialization.sql` serializes lifecycle transitions and amendments on one
tenant/task advisory-lock domain, enforces that boundary for direct PostgreSQL writers, and advances
the package contract to `0.4.1`. None of these migrations creates tenant module state or enables a
feature.

Future imports must run metadata discovery, dry-run validation, row counts, checksums, quarantine, and approval before content import or workflow activation.

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

## 10. Explicit Non-Goals For The Current Slice

- bulk reassignment and recurring-task scheduling
- comments
- attachments
- notifications
- reminders
- workflow automations
- calendar or mail sync
- cross-module writes
- RAG answer generation
- AI task generation
- voice commands
- external task-system synchronization

## 11. Verification

- `tests/test_tasks_activities_module_foundation.py`
- `tests/test_tasks_activities_productive_migration.py`
- `tests/test_tasks_activities_productive_slice.py`
- `tests/test_tasks_activities_api.py`
- `tests/test_postgres_restore_drill.py`
- `tests/test_module_family_backlog.py`
- `tests/test_api.py`
