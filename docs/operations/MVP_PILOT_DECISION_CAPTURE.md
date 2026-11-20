# MVP Pilot Decision Capture

Status: implemented foundation boundary

The MVP pilot decision path replaces further nested dry-run/skeleton expansion with one operational,
tenant-scoped vertical slice. It records an explicit `go`, `no_go`, or `defer` decision. It does not
admit a tenant or user, activate a module, authorize traffic, start a pilot, execute a business write,
or perform an external or destructive action.

## API Flow

1. An authenticated `tenant-admin` or `security-admin` reads
   `GET /v1/platform/cockpit/mvp-pilot-decision-context`.
2. The server builds the current metadata-only cockpit snapshot and derives a stable context hash from
   readiness, module, source-flow, work-item, and foundation-gap manifests. Transient audit event IDs and
   the reviewing principal are excluded from that hash.
3. The reviewer submits `POST /v1/platform/cockpit/mvp-pilot-decision-capture-submit` with the exact
   context hash, explicit decision, typed change/approval/idempotency references, current authenticated
   principal and roles, a reason, and the exact confirmation statement.
4. The server rejects stale context, cross-tenant input, role spoofing, reused idempotency keys with a
   different command, and `go` when the current metadata-only safety gates are closed.
5. The latest tenant decision is available at
   `GET /v1/platform/cockpit/mvp-pilot-decisions/current`.

The decision reason and confirmation statement are hashed before persistence and are not returned in the
record or written to normal audit metadata. Audit events contain identifiers, decisions, hashes, boundary
booleans, and no content payload.

## Persistence And Recovery

Migration `0076_mvp_pilot_decision_records.sql` creates
`collabio.mvp_pilot_decision_records` with forced tenant RLS, tenant-scoped select/insert policies, no
update/delete policies, an append-only mutation trigger, unique idempotency hashes, and least-privilege
`collabio_authz_admin` grants. The runtime API uses PostgreSQL on the Compose deployment and memory only
for isolated unit/API tests unless configured otherwise.

The PostgreSQL restore drill treats this table as a productivity-pilot control table and verifies table
presence, forced RLS, append-only policies and trigger, grants, migration checksums, and exact row counts.
The backup policy includes the table, context hashes, and record schema. After restore, decision-record
hashes must validate before the current decision is trusted. Restoring a `go` record never opens runtime,
traffic, module activation, or pilot start; those remain separate explicit boundaries with their own
current evidence.

## Roadmap Rule

Compatibility endpoints from the former decision-capture preparation chain remain read-only. They do not
define new roadmap milestones. New work after this slice must either complete a user-visible vertical
capability, remove material risk, or close a required operational evidence gap.
