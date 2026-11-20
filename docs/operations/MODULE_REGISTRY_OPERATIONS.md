# Platform Module Registry Operations

This runbook is the operating contract for `collabio.module_catalog` and `collabio.tenant_modules`.

The rule is simple: module state can hide product surfaces, but it must never hide compliance duties. Every seed, backfill, repair, enablement, disablement, suspension, and decommission transition must leave audit and backup evidence.

## Scope

The module registry owns the `module_registry_state` continuity domain:

- module catalog
- module required migration versions
- tenant module states
- tenant module migration evidence
- module lifecycle audit references
- persistent seed/backfill evidence
- worker discovery drill reports

## Daily Development Drill

Run the metadata-only registry drill after migrations, before API smoke checks, and after restore drills:

```bash
docker compose run --rm module-registry-drill
```

The command emits `module_registry_operations_report.v1`. The report must be retained with release or restore evidence when module lifecycle behavior changed.

The report proves:

- expected catalog entries exist
- required migration versions exist in the startup-blocking manifest
- expected seed tenant rows are present
- worker role can discover tenant module rows
- lifecycle audit event types and backup evidence artifacts are declared
- report hash can be recomputed from the metadata-only payload

## Seed

Seed is allowed only from reviewed migrations or an explicit admin repair change. A seed must define:

- module ID and catalog manifest hash
- required migration versions
- initial tenant module state
- enabled feature defaults
- changed_by identity
- audit_chain_ref
- backup evidence scope

Never seed a tenant module as `enabled`. First seed as `available` or provision through the admin API.

## Backfill

Backfill is required when a known catalog entry or expected tenant seed row is missing after restore, migration, or repair.

Backfill steps:

1. Run `docker compose run --rm module-registry-drill`.
2. Record the report hash and missing module or tenant rows.
3. Open a reviewed migration or admin repair change.
4. Apply the change in Docker Compose through the migrator or approved admin path.
5. Re-run `docker compose run --rm module-registry-drill`.
6. Keep both report hashes with the backup/restore evidence.

## Repair

Repair is required when catalog rows, required migration versions, worker discovery, or seed statuses drift.

Repair rules:

- no hard deletes of tenant module rows
- no direct status flip to `enabled`
- no repair without audit evidence and operator approval
- no repair that bypasses tenant RLS
- no repair that skips worker discovery validation
- no repair that removes decommission evidence

If a tenant state is wrong, prefer an explicit lifecycle API transition over direct SQL. Direct SQL repair is reserved for restore or migration incidents and needs a separate approval reference.

## API Smoke

For each production-readiness milestone, run a Postgres-backed API smoke:

- provision a unique tenant module through `POST /v1/admin/tenant-modules/{module_id}/provision`
- enable it through `POST /v1/admin/tenant-modules/{module_id}/enable`
- verify `GET /v1/platform/modules`
- disable it through `POST /v1/admin/tenant-modules/{module_id}/disable`
- verify worker compliance access with `ModuleWorkerGate`
- verify lifecycle audit metadata includes `continuity_domain=module_registry_state`

## Backup And Restore Evidence

Every module lifecycle change must be recoverable from:

- PostgreSQL backup checksum
- migration manifest versions
- tenant module row
- tenant module migration evidence
- lifecycle audit event
- module registry drill report hash
- worker discovery status

If a restore changes module visibility, run both:

```bash
docker compose run --rm backup-verify
docker compose run --rm module-registry-drill
```

Then run module-specific workers such as:

```bash
docker compose run --rm kb-runtime-reconciler
```
