# Backup And Failover

This is the practical operating culture for Collabio backups and failover.

The rule is simple: a backup does not count until it has a checksum, a restore check, an owner, and a recurring drill.

## Scope

This model covers the early platform:

- PostgreSQL metadata, policies, audit events, migration history, and vector metadata.
- File-backed development policy and registry data.
- Future object storage, WORM records, mail attachments, office documents, and audit snapshots.

It is intentionally lightweight. The current repository implements development backup commands and a machine-readable policy. Production PITR, object-store replication, and automated failover remain later deployment work.

## Culture

- Backup and restore are part of feature delivery, not an operations afterthought.
- Restore drills are more important than backup counts.
- RPO and RTO are explicit per target.
- Failover starts manual and documented; automation is added only after the manual path is rehearsed.
- Backups containing tenant data are classified data.
- Production backups must be encrypted, off-host, access-controlled, and covered by retention and legal hold rules.
- Audit and backup evidence must be hashable and exportable.

## Current Dev Commands

Create a PostgreSQL logical backup:

```bash
docker compose run --rm backup
```

Verify the newest local backup checksum and pg_restore catalog:

```bash
docker compose run --rm backup-verify
```

Local dumps are written to `./backups/`, which is gitignored.

## Minimum Restore Drill

Monthly for active development and before every production-readiness milestone:

1. Run `docker compose run --rm backup`.
2. Run `docker compose run --rm backup-verify`.
3. Record backup filename, SHA-256 checksum, migration versions, operator, date, and result.
4. For production, restore into an isolated database and run migration/audit verification against the restored copy.

## Failover Stance

Current development:

- no automatic failover
- manual restart/recreate of local services
- logical dumps for recovery rehearsal

Production target:

- PostgreSQL PITR with WAL archiving
- object storage versioning and object lock for record/evidence classes
- documented manual promotion first
- automated failover only after restore and promotion drills are passing
- failback is a separate runbook step, never an implicit side effect

## Incident Triggers

Start backup/failover procedure when one of these is true:

- primary database corruption is suspected
- migration checksum mismatch appears
- tenant data was accidentally modified or deleted
- audit chain verification fails
- object storage integrity verification fails
- RPO/RTO threshold is at risk

## Evidence

Every drill or incident must leave enough evidence to answer:

- What was backed up?
- Which checksum proves it?
- Where was it restored or verified?
- Which migration and audit checks passed?
- Who approved failover or restore?
- What tenant/data scope was affected?
