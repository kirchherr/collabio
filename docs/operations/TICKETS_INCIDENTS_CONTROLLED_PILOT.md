# Tickets & Incidents Controlled Pilot

Status: operator path ready, pilot not executed

## Purpose

This runbook moves one designated non-production tenant through the first productive Tickets & Incidents slice. It never authorizes workers, AI, RAG, compliance evidence, external actions, destructive actions, comments, attachments, or notification delivery.

## Authoritative Status

Read before every transition:

```text
GET /v1/platform/modules/families/tickets-incidents/controlled-pilot/status
```

Only a tenant admin or security admin may read the status. Continue only when `pilot_state_consistent` is `true`, `blocking_reasons` is empty, and the operator accepts the single reported `required_confirmation_statement`. Do not generate a confirmation on behalf of the accountable human.

The possible stages are:

1. `tenant_approval_required`
2. `execution_approval_required`
3. `admission_required`
4. `enablement_required`
5. `vertical_slice_validation_required`

`evidence_invalid` is a stop condition. Repair the evidence or module-state mismatch before any further write.

## Controlled Sequence

1. Record the tenant activation-readiness approval returned by the status endpoint. This writes hash/reference metadata only to the tenant-scoped append-only PostgreSQL ledger and stores no raw confirmation statement.
2. Read status again and use its `expected_execution_approval_boundary_hash` for the separate execution approval. The server rejects arbitrary boundary hashes.
3. Read status again and admit the package. Verify the returned module state is `disabled`, every feature is off, and `/v1/tickets` remains closed.
4. Read status again and separately approve enablement. Verify exactly `items.read`, `items.write`, `events.read`, and `events.write` are enabled.
5. Run the productive vertical slice with synthetic non-sensitive metadata: create, owner/operator read, allowed transition, immutable event read, stale-transition rejection, cross-tenant denial, and Legal-Hold archival denial.
6. Back up and restore the designated tenant into the isolated recovery target. Re-read status and verify the same trusted approval boundary, receipt chain, module state, four-feature set, ticket/event counts, event ordering, RLS, and append-only controls.
7. Record the evidence hashes and close the pilot before any broader tenant access.

## Stop Conditions

- any untrusted execution-approval boundary
- missing or mismatched admission, authorization, or completion receipt
- enabled module state without the complete receipt chain
- more or fewer than the four approved features
- any worker, AI, RAG, compliance, destructive, content, or external-action surface enabled
- failed RLS, Legal Hold, append-only, backup, or isolated-restore check

The status endpoint is a read model. It creates no task, receipt, module state, or activation and includes no ticket content or principal ID.
