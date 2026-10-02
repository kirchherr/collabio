# Productivity Pilot Start Authorization

## Purpose

`productivity_pilot_start_authorization.v1` is the security approval boundary before a designated-user runtime window may admit managed productivity-pilot traffic to an already provisioned business slice. It binds one tenant, the authoritative preflight, human admission, traffic-scope enforcement, policy, monitoring evidence, rollback evidence, and a bounded time window.

The authorization record is metadata-only and append-only. Creating it does not provision or activate a module, change a feature, perform a business write, run a destructive action, or call an external system.

## Default-Closed Runtime

The deployment switch `SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED` defaults to `0`. A start authorization can be created and used only while the switch is explicitly set to `1`. Managed traffic additionally requires an active `productivity_pilot_runtime_window.v1` for the requesting principal. Closing the switch immediately returns `423 productivity_pilot_runtime_disabled` for managed in-scope traffic without deleting the authorization or business/audit evidence.

The switch is independent from the database record. Restoring an authorization therefore never opens traffic by itself.

## Authorization Contract

`POST /v1/platform/productivity-pilot/start-authorizations` requires `security-admin` and:

- a security actor distinct from both the admission actor and traffic-scope actor;
- exact hashes for policy, preflight, admission, traffic scope, and route scope;
- exactly the seven operations from `productivity_pilot_policy.json`;
- all five monitoring controls and all four rollback controls;
- metadata-only evidence hashes observed no later than authorization time;
- control evidence valid through the complete authorization window;
- an authorization timestamp within five minutes of the service clock;
- an effective window longer than zero and no longer than eight hours;
- the exact human confirmation statement and typed change, approval, audit, and idempotency references.

The confirmation body is hashed but never persisted in the authorization record or normal logs.

## Exact Traffic Scope

Only these operations can pass while the authorization, designated-user runtime window, and deployment switch are active:

1. `POST /v1/crm/account-onboardings`
2. `POST /v1/tasks/items`
3. `GET /v1/tasks/items`
4. `GET /v1/tasks/activities`
5. `POST /v1/time-tracking/entries`
6. `GET /v1/time-tracking/entries`
7. `GET /v1/time-tracking/approvals`

Other managed CRM, Tasks, and Time Tracking routes return `403 operation_outside_productivity_pilot_route_scope`. In-scope traffic returns `423` before authorization, before its effective time, after expiry, or while the runtime switch is closed.

All normal tenant, module, feature, role, ACL, idempotency, retention, legal-hold, and audit controls remain in force after the pilot guard permits a request.

## Continuous Controls

The authorization requires evidence for:

- `api_health_and_latency`
- `write_error_and_conflict_rate`
- `authorization_denial_rate`
- `audit_chain_continuity`
- `postgres_capacity_and_backup_age`

Rollback evidence must cover:

- `disable_pilot_module_features`
- `block_pilot_ingress_routes`
- `preserve_business_and_audit_records`
- `restore_verified_recovery`

Rollback is non-destructive. It blocks new pilot use while preserving business and audit records for recovery, retention, legal hold, and investigation.

## Persistence And Recovery

Migration `0063_productivity_pilot_start_authorization.sql` creates the tenant-scoped `collabio.productivity_pilot_start_authorizations` ledger with forced RLS, `SELECT/INSERT` only for `collabio_authz_admin`, no application-role grant, and a mutation-rejecting trigger.

The PostgreSQL restore drill verifies the table, policies, trigger, exact grants, row counts, and state hashes on source and isolated restore target. `backend_foundation_completion_gate.v1` fails closed when these controls are missing or changed.

## Operational Sequence

1. Produce a fresh green business-backend release and productivity-pilot preflight.
2. Record human admission and exact traffic-scope enforcement.
3. Provision only the approved tenant/module features through their existing admin gates.
4. Set `SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED=1` for the controlled deployment window.
5. Submit the start authorization with fresh monitoring and rollback evidence.
6. Activate a bounded designated-user runtime window as documented in `docs/operations/PRODUCTIVITY_PILOT_RUNTIME_WINDOW.md`.
7. Observe only the seven routes until expiry; do not broaden the policy during the window.
8. Close the deployment switch after the proof or immediately on a control breach.
9. Run backup verification, isolated PostgreSQL restore, exact-version object restore, and the backend completion gate.

The designated-user runtime observation boundary is implemented in `docs/operations/PRODUCTIVITY_PILOT_RUNTIME_WINDOW.md`; the next operational step is a real bounded observation followed by kill-switch closure and refreshed restore evidence, not broader module or route expansion.

## Current Technical Runtime Proof

The isolated development proof on 2026-07-31 verified the control without running a business write:

- start authorization `sha256:9306b1e1d2e0706d1236c99792f9a6531747cd73f4acdc3fc399e70fcef32fd7` for `pilot-start-runtime-20260731`;
- four distinct control outcomes: four approved read operations returned `200`, while `GET /v1/crm/accounts` remained outside scope with `403`;
- unchanged CRM account, Task, Time Entry, and start-authorization row counts of `3|1|1|1` before and after the reads;
- immediate `423` for an approved Task route after the deployment switch was closed while the authorization was still unexpired;
- backup SHA-256 `sha256:5078c3687609950ff3bfdf704e2b13e21a83dc0993e24bd2bf3b1eca30690924` and successful checksum verification;
- 63 migrations and 70 tables matched across source and isolated PostgreSQL restore;
- exactly one authorization row with the same evidence hash and no confirmation body on source and restore target;
- PostgreSQL restore report `sha256:0cec6b8bfea24eae57708ef3242b77f1866abb86666bdf67f25f45c1b3dc789f`;
- backend foundation gate `sha256:633fcd6cd938ce355964a721b74c363d983041a32f90a93e8eb7a1a9ca93202c`;
- business backend release gate `sha256:432f84a7a0cf118b47077bd6caace7efd209fba96c4b872022f7a6f889810e28`;
- fresh post-restore safety preflight `sha256:6068d97186d3cae71e1e3186b6f5d3a6ea34e7b67a776f4cb6ae52b418132a7e`.

This is a technical development proof, not the designated-user pilot observation. The runtime switch remains closed after the proof.
