# Productivity Pilot Closure Report

## Purpose

`productivity_pilot_closure_report.v1` is the append-only completion boundary for one controlled productivity-pilot runtime window. It proves that the deployment kill switch is closed and binds the authoritative window, all seven route observations, the three business-write receipts, and refreshed PostgreSQL recovery evidence.

The report does not delete, update, anonymize, activate, or execute any pilot, business, module, feature, audit, destructive, or external action. Retention and deletion continue to follow their authoritative policies after closure.

## Authoritative Inputs

The server resolves all authoritative evidence. A caller may identify the expected runtime window and submit recovery references, but may not submit observations or business receipts.

- current `productivity_pilot_start_authorization.v1`;
- current `productivity_pilot_runtime_window.v1`;
- all `productivity_pilot_runtime_observation.v1` rows for that window;
- CRM account-onboarding, Task creation, and Time Tracking entry receipts committed inside the closed interval;
- backup checksum, isolated restore report, backend foundation gate, and business backend release gate.

Closure requires exactly one observation for each of the seven authorized operations and exactly one authoritative receipt for each of the three `POST` operations. Every observed or receipt actor must resolve to a designated-principal hash. Raw principal IDs, request bodies, response bodies, business content, and the human confirmation statement are excluded from the report.

## Control Boundary

`POST /v1/platform/productivity-pilot/closure-reports` requires `security-admin` and the exact confirmation statement from the API schema. The actor must differ from the start authorizer, runtime activator, and designated pilot principals. The command is accepted only while `SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED=0`.

The report also requires:

- a closure timestamp at or after the runtime-window start;
- recovery evidence observed at or after closure;
- restored counts matching one window, all observations, and all three domain receipts;
- typed change, approval, owner, recovery-owner, audit, and idempotency references;
- explicit non-mutation and metadata-only flags.

`GET /v1/platform/productivity-pilot/closure-reports/current` returns the current tenant-scoped report to a security administrator. Both routes fail closed when evidence is missing, mismatched, or hash-invalid.

## Persistence And Recovery

Migration `0065_productivity_pilot_closure_report.sql` creates `collabio.productivity_pilot_closure_reports` with:

- forced tenant row-level security;
- `SELECT` and `INSERT` only for `collabio_authz_admin`;
- no application-role grant;
- explicit update and delete denial policies;
- a mutation-rejecting append-only trigger;
- foreign keys to the runtime window and start authorization;
- one closure per tenant runtime window;
- database checks for closed, preserved, metadata-only evidence.

The PostgreSQL restore drill includes the closure table, exact row counts, forced RLS, grants, policies, and trigger. Restoring a report never opens the deployment switch and never authorizes new traffic.

## Operating Sequence

1. Close the deployment switch and verify an in-scope request returns `423 productivity_pilot_runtime_disabled`.
2. Create a fresh backup and complete an isolated restore drill.
3. Run the backend foundation and business backend release gates against the restored state.
4. Submit the closure command as an independent security administrator.
5. Read back and hash-verify the persisted closure report.
6. Create another backup and restore proof that includes the closure report itself.
7. Admit real users only through a new, separately approved pilot chain.

The next milestone is not automatic expansion. It is a separately admitted real-user productivity pilot with newly nominated principals, current control evidence, a new bounded start authorization, and a new runtime window.
