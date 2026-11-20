# Productivity Pilot Traffic Scope

## Purpose

`productivity_pilot_traffic_scope_enforcement.v1` binds one tenant to one authoritative admission, preflight, policy, and exact route scope. It establishes default deny before pilot start. It does not authorize pilot traffic, activate a module, change tenant state, execute a business write, or perform an external action.

## Authoritative Binding

`POST /v1/platform/productivity-pilot/traffic-scope-enforcements` requires `tenant-admin` or `security-admin`. The service resolves the tenant-visible preflight and admission from server-side stores and requires exact matches for:

- admission ID and evidence hash;
- preflight gate hash;
- policy hash;
- all seven allowed API operations, including order;
- the exact human confirmation statement;
- typed change, ingress-policy, confirmation, idempotency, and audit references.

The response stores only the confirmation-statement hash. The statement itself is neither persisted nor written to normal audit logs.

## Runtime Enforcement

The guard covers every CRM, Tasks, and Time Tracking business endpoint. Its pre-start decisions are:

| Tenant state | Route state | Result |
| --- | --- | --- |
| No traffic-scope enforcement | Any guarded route | Existing authorization and module gates continue unchanged |
| Traffic scope enforced | One of the seven policy operations | `423 productivity_pilot_start_authorization_required` |
| Traffic scope enforced | Any other guarded CRM/Tasks/Time route | `403 operation_outside_productivity_pilot_route_scope` |

The seven policy operations are the CRM onboarding write plus Tasks and Time Tracking read/write slices. Read-only CRM account, contact, activity, note, workspace, and CRM/ERP search routes remain outside the pilot scope and are denied for the managed pilot tenant.

## Storage And Rights

Migration `0062_productivity_pilot_traffic_scope.sql` creates `collabio.productivity_pilot_traffic_scope_enforcements` with forced RLS, tenant-scoped select/insert policies, mutation-rejecting update/delete policies and trigger, and foreign keys to the authoritative admission and preflight evidence.

`collabio_authz_admin` has exactly `SELECT, INSERT`. `collabio_app` has no direct table rights. One admission, preflight, and idempotency reference can produce at most one tenant-scoped enforcement record.

## Audit And Recovery

Creation and denial events contain metadata and evidence hashes only. They never include request bodies, confirmation text, or business content.

PostgreSQL backup and restore evidence must preserve exact row counts, forced RLS, append-only policies and trigger, foreign-key state, and exact role grants. `backend_foundation_completion_gate.v1` blocks when `productivity_pilot_traffic_scope_controls_verified=false`.

The independent start control is implemented as `productivity_pilot_start_authorization.v1`. Managed in-scope traffic is allowed only while a matching, effective, unexpired record exists and the default-closed deployment runtime switch is open; out-of-scope routes remain denied. See `docs/operations/PRODUCTIVITY_PILOT_START_AUTHORIZATION.md`.

## Pre-Start Runtime Proof

The isolated development proof on 2026-07-30 completed with:

- 62 applied migrations and 69 restored PostgreSQL tables;
- backend foundation gate `sha256:74b6e95d5a8a2080725d6818ce9457e075154be363471dca813a398032a71bde`;
- PostgreSQL restore report `sha256:546d4bd2fb177291da32980e529075666ebe3a6e3b5e19d7b15ba9f268546046`;
- business backend release gate `sha256:f53bd394e37ce8faa760fa933f37d709ab06a1fb950d579df1b63ff03b9f1119`;
- bound preflight `sha256:51ce7d873398b80f24144fe0b7dffb847cd1dbb7c40d55331f130c86c798d7ac` and admission `sha256:c0b3f55814dc58d582ba40282d3649100e936e9932d079ee21cac46e5084b839`;
- traffic-scope evidence `sha256:d7c6f68aec0485edaa04cc3b8df6586467493d4b9fafb5f50711a7d3319a0b6a` and route-scope hash `sha256:f15047298d4e482da105036f84ca6621c5cbf053604f86da0dfa70225a18d45d`;
- exactly one matching traffic-scope row and evidence hash in source and isolated restore target;
- idempotent replay against the same evidence hash;
- `423` for an allowed Task pilot route before start authorization and `403` for an out-of-scope CRM route;
- unchanged CRM, Tasks, and Time Tracking row counts of 3, 1, and 1;
- a fresh post-restore safety preflight `sha256:afbeed287682813c089f1324ca6d7fdf4dfd9ce982225a857c47424710934649`;
- pilot start and pilot business traffic still false.

These hashes prove this development run only. Any policy, release, admission, tenant state, route scope, or recovery change requires fresh evidence.

## Start Authorization Technical Proof

On 2026-07-31, start authorization `sha256:9306b1e1d2e0706d1236c99792f9a6531747cd73f4acdc3fc399e70fcef32fd7` opened only the four approved read routes used by the technical proof (`200`) while `GET /v1/crm/accounts` remained denied (`403`). Business row counts stayed unchanged. Closing the runtime switch immediately returned the approved Task read to `423`. The exact authorization row was recovered on the isolated target under PostgreSQL restore report `sha256:0cec6b8bfea24eae57708ef3242b77f1866abb86666bdf67f25f45c1b3dc789f`.
