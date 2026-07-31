# Productivity Pilot Runtime Window

## Purpose

`productivity_pilot_runtime_window.v1` is the designated-user boundary after a valid productivity-pilot start authorization. A start authorization alone no longer permits managed pilot traffic. One tenant-scoped runtime window must additionally bind the exact start-authorization hash, its seven-operation route scope, a bounded time window, and an explicit list of designated pilot principals.

The runtime window activates no module, changes no feature, and performs no business write. It only narrows an already authorized pilot window. The deployment switch `SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED` remains authoritative and can block all managed pilot traffic immediately.

## Activation

`POST /v1/platform/productivity-pilot/runtime-windows` requires a `tenant-admin` runtime operator who is distinct from the `security-admin` that created the start authorization. The runtime operator cannot also be a designated pilot principal.

The command requires:

- the exact current start-authorization ID and evidence hash;
- one to 25 unique designated principal IDs;
- an effective interval fully contained by the start authorization;
- typed idempotency, change, approval, operations-owner, and audit references;
- the exact human confirmation statement;
- explicit confirmation that no module, feature, destructive, external, or business-data action is requested.

The API response contains the designated IDs because tenant administrators need to review the authoritative allowlist. Audit events contain only the principal count and manifest hash, never the list or confirmation body.

## Request Enforcement

For managed CRM, Tasks, and Time Tracking routes, every request must pass these controls in order:

1. tenant and principal resolution;
2. exact seven-operation traffic scope;
3. effective and unexpired start authorization;
4. open deployment kill switch;
5. effective and unexpired runtime window;
6. designated-principal membership;
7. normal module, feature, role, ACL, retention, legal-hold, and business validation.

Missing runtime evidence returns `423 productivity_pilot_runtime_window_required`. A non-designated principal receives `403 principal_not_designated_for_productivity_pilot`. Expired or disabled windows fail closed.

## Observation Ledger

Each request admitted at the runtime boundary writes `productivity_pilot_runtime_observation.v1` before the business handler executes. The record contains only:

- tenant, runtime-window, and start-authorization evidence references;
- an observation ID and timestamp;
- the canonical API operation;
- a tenant-bound hash of the designated principal ID;
- authorization, route-scope, and designated-principal verification flags.

Request bodies, response bodies, business payloads, raw principal IDs, secrets, and content are forbidden. The observation proves admission at the guard; it is not evidence that the downstream business transaction succeeded. Domain receipts and audit events remain authoritative for business outcomes.

## Persistence And Recovery

Migration `0064_productivity_pilot_runtime_window.sql` creates:

- `collabio.productivity_pilot_runtime_windows`;
- `collabio.productivity_pilot_runtime_observations`.

Both tables use forced RLS, tenant-scoped `SELECT`/`INSERT`, explicit no-update/no-delete policies, and mutation-rejecting triggers. The PostgreSQL restore drill includes both tables in the productivity-pilot start-control proof and verifies exact row counts, state hashes, policies, triggers, and grants.

## Operational Sequence

1. Produce fresh release, preflight, admission, traffic-scope, and start-authorization evidence.
2. Open `SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED` only for the approved deployment window.
3. Activate one runtime window for the designated principals and a subset of the start interval.
4. Observe only the seven policy operations and correlate runtime observations with domain receipts, denials, health, latency, audit continuity, capacity, and backup age.
5. Close the deployment switch at expiry or immediately on a control breach.
6. Verify backup integrity, isolated PostgreSQL restore, exact-version object restore, and the backend completion gate.

The controlled development execution from 2026-07-31 is recorded in `PRODUCTIVITY_PILOT_DEVELOPMENT_PROOF_20260731.md`. It proves all seven operations, immediate kill-switch closure, and refreshed isolated restore evidence without claiming a real-user or production pilot.

The next boundary is a tenant-scoped, append-only closure report that proves the switch is closed and binds the observed window to its observation manifest, domain receipts, and refreshed backup and restore evidence. It must not auto-delete or rewrite pilot, business, or audit records.
