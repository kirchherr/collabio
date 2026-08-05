# Production Continuity Deployment Gate

## Purpose

`production_continuity_deployment_gate.v2` closes the production admission boundary that is intentionally outside the
development restore drill. It evaluates current, hash-bound operator evidence for:

- PostgreSQL physical base backup, complete WAL archive and isolated point-in-time recovery;
- encrypted, immutable offsite backup with independent credentials and a verified offsite restore;
- PostgreSQL HA topology, synchronous durability, TLS replication, fencing, split-brain prevention and manual
  promotion;
- cross-site PostgreSQL, object-storage and KMS recovery while preserving tenant isolation, versions, Object Lock,
  retention and legal hold;
- three distinct change, security and operations approvals.

The gate is provider-neutral. It records implementation IDs only to prove that a reviewed adapter is in use. The
initial open-source reference set includes PostgreSQL native PITR, pgBackRest, Barman/CloudNativePG, Patroni and MinIO
bucket replication. Managed providers may enter through the same evidence contract. Every implementation also carries a
version/provenance hash so evidence from another binary, image or operator release cannot be substituted silently.

Primary implementation references:

- PostgreSQL continuous archiving and PITR: <https://www.postgresql.org/docs/current/continuous-archiving.html>
- pgBackRest encrypted and multiple repositories: <https://pgbackrest.org/user-guide.html>
- Patroni HA and fencing: <https://patroni.readthedocs.io/en/latest/>
- CloudNativePG recovery: <https://cloudnative-pg.io/documentation/current/recovery/>
- MinIO bucket replication requirements: <https://min.io/docs/minio/linux/administration/bucket-replication/bucket-replication-requirements.html>

These are reference implementations, not hard dependencies. Provider changes must preserve the gate fields and
controls.

## Fail-Closed Boundary

Setting `SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED=1` is insufficient. The runtime switch resolves to enabled only when
`SUITE_PRODUCTION_CONTINUITY_GATE_REPORT_PATH` points to a hash-valid report with `deployment_ready=true`.

The gate itself never:

- deploys infrastructure;
- promotes a database;
- changes traffic or DNS;
- opens the productivity pilot;
- writes business data;
- stores endpoint URLs, credentials, key material, tenant content or personal identifiers.

`deployment_execution_allowed` and `failover_execution_allowed` are always `false`. Automatic failover can be admitted
as configured readiness only after a separate automatic-failover drill hash exists; admission still executes nothing.

## Operator Read Model

Security administrators can inspect the current policy-derived requirements and normalized gate state through:

- `GET /v1/platform/production-continuity/evidence-requirements`
- `GET /v1/platform/production-continuity/gate-status`

Both routes require tenant context and the `security-admin` role. They are metadata-only, audit logged and do not
accept evidence. The status response returns `missing`, `invalid`, `expired`, `blocked` or `ready` without exposing the
report path, deployment reference, evidence hashes, KMS references or principal hashes. A ready state remains
non-executing and is separate from the explicit runtime switch.

See `PRODUCTION_CONTINUITY_EVIDENCE_READ_MODEL.md` for the accountable collection workflow and response contract.

## Evidence Bundle

The input schema is `production_continuity_deployment_evidence.v1`. All deployment, implementation-version, site,
repository, target, KMS, operator and approval references are SHA-256 values. Evidence timestamps must be timezone-aware and no older than the
policy window. Unknown fields are rejected, which prevents ad hoc secret or endpoint fields from entering the report.

Required sections:

1. `postgres_pitr`
2. `encrypted_offsite_backup`
3. `ha_promotion`
4. `cross_site_failover`
5. `approvals`

The continuity-domain manifest must contain every domain marked `critical` in
`backup_failover_policy.v4`. RPO and RTO measurements are evaluated against the existing target policy rather than
duplicated in the evidence bundle.

## Docker Execution

Keep the evidence outside the repository and mount it read-only:

```bash
docker compose --profile production-continuity run --rm \
  -v /secure/operator-evidence/production-continuity.json:/evidence/production-continuity.json:ro \
  -v /secure/operator-evidence/production-continuity.dsse.json:/evidence/production-continuity.dsse.json:ro \
  -v /secure/operator-trust/production-continuity-signers.json:/trust/production-continuity-signers.json:ro \
  production-continuity-deployment-gate
```

The service has no network, a read-only root filesystem, no Linux capabilities and `no-new-privileges`. A ready report
is written to `backups/production-continuity-deployment-gate.json`; a blocked report exits with status `2`.

The signed in-toto/DSSE contract, public-key trust boundary, runtime re-verification, rotation and revocation process
are defined in `PRODUCTION_CONTINUITY_ATTESTATIONS.md`.

Never commit a production evidence bundle. The persisted report is metadata-only and may enter release evidence after
operator review.

## Promotion And Failback

Manual promotion is required before automation is trusted. Promotion evidence must prove fencing and split-brain
prevention. Failback remains a separate reviewed runbook and is never performed as an implicit consequence of this
gate or a failover drill.

Any change to PostgreSQL topology, WAL tooling, backup repository, encryption mode, KMS recovery, object replication,
RPO/RTO or site layout invalidates the previous bundle and requires fresh evidence.
