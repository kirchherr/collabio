# Time Tracking Module Charter

Status: operational first productive slice
Date: 2026-07-30
Module ID: `time_tracking`
Module kind: `business_domain`
Continuity domain: `time_tracking_records`

## Product Decision

Time Tracking is an optional suite module for governed work-time records and their approval state. It
must remain usable across CRM, ERP, Tasks, Tickets, LMS, Office, and Mail without making any one of
those modules a storage dependency.

The first productive slice creates one `time.entry` and one linked `time.approval` in state
`not_submitted`. Entry, approval, authoritative ACL grants, and a metadata-only receipt commit in one
transaction. Corrections, submission, manager decisions, payroll effects, exports, and external
integrations are separate later slices.

## Lifecycle And Feature Gates

Normal routes require:

```text
Tenant Context
+ time_tracking enabled
+ feature permission
+ authoritative object authorization
```

| Feature ID | Default | Approval | Purpose |
| --- | --- | --- | --- |
| `time_tracking.entries.read` | on | no | Authorized own or delegated entries |
| `time_tracking.approvals.read` | on | no | Approval state for an authorized linked entry |
| `time_tracking.entries.write` | off | yes | Atomic entry, approval, ACL, and receipt creation |
| `time_tracking.compliance_evidence.read` | off | yes | Retention and Legal Hold evidence |
| `time_tracking.exports.execute` | off | yes | Future confirmed export with evidence manifest |

Feature approval controls tenant activation of the capability. It is not a substitute for
authoritative object ACLs or later human confirmation of an export or payroll-relevant action.

## Productive API

- `POST /v1/time-tracking/entries`
- `GET /v1/time-tracking/entries`
- `GET /v1/time-tracking/approvals`

A time worker may create an entry only for themselves. A tenant administrator or time manager may
create for another active tenant principal. Reads return no approval unless both the approval and
its linked entry are authorized.

## Data Contract

The first slice stores governed metadata only:

- worker, work date, start/end UTC, and calculated duration
- optional namespaced project and cost-center references
- lifecycle, classification, retention, Legal Hold, KMS, audit, source, and schema metadata
- linked initial approval state without a decision
- immutable creation receipt containing hashes and identifiers, never free-text work content

Time records are personal data. They are not payroll truth until a later explicitly approved export
or integration contract says so.

## Backup, Restore, And Failover

The `time_tracking_records` domain includes entries, approval records, ACLs, receipts, tenant module
state, and feature state. Restore readiness requires exact row counts, Forced RLS, append-only
policies, minimal role grants, tenant isolation, Legal Hold preservation, and source/target equality.

Any future correction, approval transition, export, payroll bridge, notification, queue, search
index, RAG index, or AI feature must extend backup and restore evidence in the same change.

## Explicit Non-Goals

- entry correction or deletion
- submission and approval decisions
- payroll, invoicing, or ERP posting
- CSV/PDF export
- automatic timers or background capture
- calendar inference
- notifications or workflow automation
- search, RAG, AI, or voice

Destructive, external, payroll-relevant, or compliance-relevant actions require explicit human
confirmation in addition to module and object authorization.

## Verification

- `tests/test_time_tracking_module_foundation.py`
- `tests/test_time_tracking_productive_migration.py`
- `tests/test_time_tracking_productive_slice.py`
- `tests/test_time_tracking_api.py`
- `tests/test_postgres_restore_drill.py`
