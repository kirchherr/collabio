# Legal Hold Model

Status: initial
Date: 2026-06-10

## Purpose

Legal Hold prevents deletion, mutation, cryptographic shredding, or lifecycle expiry of records relevant to a legal, audit, regulatory, or investigation matter.

Legal Hold is not a UI flag. It is a policy, storage, lifecycle, export, search, and audit concept.

## Hold States

| State | Meaning |
| --- | --- |
| `none` | No active hold applies |
| `active` | Object is protected by one or more holds |
| `released_pending_lifecycle` | Hold was lifted; retention/lifecycle must be re-evaluated |
| `expired_after_release` | Object may be deleted or restricted if all other policies permit |

## Required Hold Metadata

```text
hold_id
tenant_id
matter_id
scope
reason
created_by
created_at_utc
approved_by
released_by
released_at_utc
affected_object_ids
policy_snapshot_id
audit_event_ids
```

## Enforcement Points

Legal Hold must be checked in:

- API delete/update flows.
- Retention worker.
- KMS key destruction workflows.
- WORM storage adapter.
- Export/e-discovery.
- Search and RAG source resolution.
- Admin workflows.
- AI tool permissions.

## Current Implementation

Runtime boundary:

```text
app/suite/storage/legal_hold.py
```

The current service supports placing and releasing Legal Hold on source objects. Both actions create a new source object version, rebuild the source object manifest hash, write through the guarded source object repository, and re-evaluate the `RetentionManifest`.

Detailed API notes:

```text
docs/LEGAL_HOLD_API.md
```

## Decision Rule

```text
if legal_hold_state == active:
  deny delete
  deny cryptoshred
  deny retention expiry
  deny destructive AI tool call
  require privileged role for export/search access
  write audit event
```

## Release Rule

Releasing a hold does not delete data. It moves affected objects to `released_pending_lifecycle`, where the lifecycle worker re-evaluates:

1. Tenant isolation.
2. Other active holds.
3. Regulatory retention.
4. Contractual retention.
5. Data subject rights.
6. Business policy.
7. Default deny.

## Audit Requirements

Every hold action must write an audit event:

- hold created
- hold scope changed
- object added to hold
- object removed from hold
- hold released
- lifecycle decision after release
- denied deletion due to hold
- denied cryptoshred due to hold

## Open Questions

- Exact role names for legal and records administrators.
- Four-eyes requirement for hold release.
- Tenant-specific retention overrides.
- Export package rules for held data.
