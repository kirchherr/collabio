# Tasks & Activities Productive Vertical Slice

Status: operational
Date: 2026-07-30
Module: `tasks_activities`

## Scope

The first productive slice creates one assigned task and one initial activity. The task, activity,
authoritative ACL grants, and metadata-only creation receipt commit in one PostgreSQL transaction.

Productive routes:

- `POST /v1/tasks/items`
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

## Read Contract

Normal reads use the application database role under Forced RLS. Returned rows are intersected with
the authoritative object IDs from `UserContext`.

An activity is returned only when the caller may read both the activity and its linked task. This
prevents activity metadata from revealing a task that is not authorized.

## Persistence Controls

Migration `0059_tasks_activities_productive_slice.sql` creates:

- `tasks.items`
- `tasks.activities`
- `tasks.creation_receipts`

All three tables are tenant scoped, Forced-RLS protected, and append-only in this slice. The
`collabio_authz_admin` role receives only `SELECT` and `INSERT`; the application and worker roles
receive only `SELECT`.

## Continuity

The PostgreSQL backup and isolated restore drill verifies:

- all three relations and exact row counts
- migration catalog equality
- Forced RLS and append-only policies
- minimal authz-admin and application grants
- complete source/target state equality

A missing relation, policy, or safe role grant blocks `restore_ready`.

## Deliberately Deferred

- status and due-date transitions after creation
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
