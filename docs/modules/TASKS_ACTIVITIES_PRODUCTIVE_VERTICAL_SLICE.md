# Tasks & Activities Productive Vertical Slice

Status: operational assignment and lifecycle workflow
Date: 2026-09-17
Module: `tasks_activities`

## Scope

The productive slice creates one assigned task and one initial activity, then supports append-only
lifecycle transitions and versioned assignment/due-date amendments. Each command commits its linked
activity, authoritative ACL changes, and immutable evidence in one PostgreSQL transaction.

Productive routes:

- `POST /v1/tasks/items`
- `POST /v1/tasks/items/{task_object_id}/transitions`
- `POST /v1/tasks/items/{task_object_id}/amendments`
- `GET /v1/tasks/items`
- `GET /v1/tasks/activities`

Tenant provisioning and feature activation remain explicit administration operations. The package
being installed does not create tenant state and does not enable runtime use.

## Write Contract

Creation requires:

- authenticated Tenant Context
- enabled `tasks_activities` tenant module
- `tasks_activities.tasks.workflow.write`
- both read dependency features
- server-side `tenant-admin`, `tenant_admin`, `task-manager`, or `task-operator` role
- an active tenant principal when assigning to somebody other than the actor

The transaction writes:

1. one `tasks.items` row
2. one linked `tasks.activities` row
3. two creator ACLs, plus two assignee ACLs when actor and assignee differ
4. one `tasks.creation_receipts` row

The mutation reference is idempotent and bound to the complete command, actor, and resolved assignee.
Reusing it with different input fails with conflict. A collision at any later insert rolls back all
earlier rows.

Receipts contain identifiers, hashes, ACL references, and the shared audit-chain reference. Task
titles and activity summaries are never copied into receipts or normal application logs.

An amendment compares the caller's expected assignee and due date with the current projection. It
stores complete before/after metadata in `tasks.amendments`, appends a linked activity, validates the
target as an active tenant principal, revokes only the prior process-generated assignment ACL, and
grants the target assignee access atomically. Independent manual ACLs are preserved. Terminal tasks
cannot be reassigned or rescheduled.

## Read Contract

Normal reads use the application database role under Forced RLS. Returned rows are intersected with
the authoritative object IDs from `UserContext`.

An activity is returned only when the caller may read both the activity and its linked task. This
prevents activity metadata from revealing a task that is not authorized.

## Persistence Controls

Migrations `0059`, `0077`, `0079`, and `0081` create and protect:

- `tasks.items`
- `tasks.activities`
- `tasks.creation_receipts`
- `tasks.lifecycle_transitions`
- `tasks.amendments`

All five tables are tenant scoped, Forced-RLS protected, and append-only. PostgreSQL validates both
hash chains and the assignment ACL handover. Lifecycle transitions and amendments share one
tenant/task advisory-lock domain, including direct database writes, so terminal-state checks and ACL
handover cannot race. The `collabio_authz_admin` role receives only the writes required by the
transaction; the application and worker roles remain read-only.

## Continuity

The PostgreSQL backup and isolated restore drill verifies:

- all five relations and exact row counts
- migration catalog equality
- Forced RLS and append-only policies
- transition/amendment chain triggers, shared task-mutation serialization, and assignment ACL evidence
- minimal authz-admin and application grants
- complete source/target state equality

A missing relation, policy, or safe role grant blocks `restore_ready`.

## Deliberately Deferred

- bulk reassignment and recurring scheduling
- comments and attachments
- notifications, reminders, calendar, and mail effects
- workflow automation and cross-module writes
- search, RAG, AI, and voice
- destructive disposition

These are separate product slices. Each must extend rights, audit, retention, Legal Hold, and
continuity evidence in the same change.

## Verification

- `tests/test_tasks_activities_productive_migration.py`
- `tests/test_tasks_activities_productive_slice.py`
- `tests/test_tasks_activities_api.py`
- `tests/test_postgres_restore_drill.py`
