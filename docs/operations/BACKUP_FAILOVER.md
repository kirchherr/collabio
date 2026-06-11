# Backup And Failover

This is the practical operating culture for Collabio backups and failover.

The rule is simple: a backup does not count until it has a checksum, a restore check, an owner, and a recurring drill.

The second rule is just as important: every new durable component must update this continuity model before it can be treated as production-ready.

## Scope

This model covers the whole suite trajectory:

- PostgreSQL metadata, policies, audit events, migration history, and vector metadata.
- File-backed development policy and registry data.
- Source object metadata, object manifests, object storage, WORM records, office documents, collaborative state, mail messages, attachments, parser artifacts, export packages, and audit snapshots.
- KMS references, secret-manager state, key rotation evidence, and destruction evidence.
- Search indexes, vector indexes, indexing checkpoints, and rebuild cursors.
- AI control-plane registries, model artifacts, prompt/tool policy, and approval policy.
- Voice transcripts, e-discovery exports, observability evidence, release artifacts, background jobs, and outbox state.

It is intentionally lightweight. The current repository implements development backup commands and a machine-readable policy. Production PITR, object-store replication, and automated failover remain later deployment work.

## Culture

- Backup and restore are part of feature delivery, not an operations afterthought.
- No new persistent component ships without a continuity domain, backup target, restore drill, and failover mode.
- Restore drills are more important than backup counts.
- RPO and RTO are explicit per target.
- Failover starts manual and documented; automation is added only after the manual path is rehearsed.
- Backups containing tenant data are classified data.
- Production backups must be encrypted, off-host, access-controlled, and covered by retention and legal hold rules.
- Audit and backup evidence must be hashable and exportable.
- Source object restores must prove metadata and content still match their canonical manifest and content hashes.
- Rebuildable indexes still require checkpoint, rebuild order, freshness, and integrity checks.
- Secrets and key material are recovered through KMS/secret-manager mechanisms, never through plaintext dumps.

## Continuity Domains

The machine-readable policy in `docs/operations/backup_failover_policy.json` tracks continuity domains across the roadmap:

- tenant IAM and authorization
- PostgreSQL metadata
- audit evidence
- source object metadata and object storage records
- KMS metadata and secrets configuration
- office documents and collaboration state
- mail messages, threads, attachments, and security evidence
- parser worker artifacts
- search and vector indexes
- AI control plane and model artifacts
- voice transcripts
- e-discovery exports
- observability evidence
- repository and release configuration
- background jobs and outbox state

When a future feature introduces a new stateful subsystem, one of these domains must be updated or a new domain must be added in the same change.

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
4. For production, restore into an isolated environment and run the domain-specific checks from the policy.
5. Update the policy and this runbook when the restore path changes.

## Failover Stance

Current development:

- no automatic failover
- manual restart/recreate of local services
- logical dumps for recovery rehearsal

Production target:

- PostgreSQL PITR with WAL archiving
- object storage versioning and object lock for record/evidence classes
- KMS/secret-manager recovery path with no plaintext key export
- search/vector degraded mode and rebuild plan
- mail journal consistency checks
- office record/WORM integrity checks
- documented manual promotion first
- automated failover only after restore and promotion drills are passing
- failback is a separate runbook step, never an implicit side effect

## Pull-Forward Rule

Any PR or roadmap step that adds persistent state must answer:

- Which continuity domain owns the state?
- Which target backs it up or rebuilds it?
- What is the RPO/RTO?
- What integrity check proves the restored state is trustworthy?
- What is the degraded or failover mode?
- Does retention, legal hold, KMS, audit, tenant isolation, or e-discovery change?

If the answer changes, the policy and runbook move in the same PR.

## Incident Triggers

Start backup/failover procedure when one of these is true:

- primary database corruption is suspected
- migration checksum mismatch appears
- tenant data was accidentally modified or deleted
- audit chain verification fails
- object storage integrity verification fails
- KMS or secret-manager recovery is at risk
- mail journal consistency is at risk
- office record or WORM evidence integrity is at risk
- search or vector indexes cannot be rebuilt within RTO
- RPO/RTO threshold is at risk

## Evidence

Every drill or incident must leave enough evidence to answer:

- What was backed up?
- Which checksum proves it?
- Where was it restored or verified?
- Which migration and audit checks passed?
- Who approved failover or restore?
- What tenant/data scope was affected?
