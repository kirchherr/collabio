# Production Continuity Evidence Read Model

## Purpose

The evidence read model gives accountable security operators a tenant-bound view of the current production continuity
requirements and gate state. It closes the operator visibility gap without creating an evidence upload service or a
second source of truth.

The read model never collects, stores, edits or approves production evidence. Evidence remains outside the repository
and enters the existing no-network gate only through an explicit read-only mount.

## API

Both routes require an authenticated tenant context and the `security-admin` role:

- `GET /v1/platform/production-continuity/evidence-requirements`
- `GET /v1/platform/production-continuity/gate-status`

The requirements response is derived from the current `backup_failover_policy.v4`. It exposes only:

- required evidence sections and control IDs;
- critical continuity-domain IDs;
- policy RPO, RTO, freshness, topology and drill thresholds;
- allowed provider-neutral implementation adapter IDs;
- the current policy hash and schema version;
- the requirement for three distinct approvals and SHA-256-only references.
- the in-toto/DSSE format, Ed25519 algorithm and required change, security and operations signer roles.

The response does not expose policy descriptions, development commands, endpoints, credentials, deployment
references, KMS references, evidence artifact hashes or principal hashes.

## Gate States

`production_continuity_gate_status.v2` uses five states:

| State | Meaning |
| --- | --- |
| `missing` | No report path is configured or the configured report does not exist. |
| `invalid` | The report is malformed, hash-invalid, future-dated, bound to another policy or violates the runtime contract. |
| `expired` | A previously valid report is outside its evidence-validity window. |
| `blocked` | The report is valid but one or more continuity checks failed. |
| `ready` | The report is hash-valid, policy-bound, fresh, metadata-only and satisfies every gate check. |

A ready state additionally requires three valid role-bound signatures and a report hash bound to the currently mounted
signer policy. The response exposes only verification booleans and signer count, never keys or principal references.

`continuity_gate_ready=true` does not open traffic. `runtime_enablement_allowed=true` requires both a ready gate and an
explicitly requested runtime switch, but it still represents only the deployment-wide continuity prerequisite.
`pilot_traffic_allowed`, deployment, failover and business-write permissions remain `false` in every response. The
separate tenant admission, designated-user, start, route and expiry controls stay authoritative.

## Accountable Collection Workflow

1. A security administrator reads the current requirements endpoint.
2. Accountable operations owners collect real topology, PITR, offsite restore, HA promotion, cross-site recovery and
   approval artifacts outside the repository.
3. The evidence bundle contains only SHA-256 references and the strict fields defined by
   `production_continuity_deployment_evidence.v1`; no endpoint, credential, key material, content or raw principal ID is
   added.
4. Change, security and operations independently sign the same canonical in-toto Statement through external approved
   key custody; no private key enters the Suite.
5. An operator mounts the reviewed bundle, DSSE envelope and public signer policy read-only into the gate.
6. The no-network gate validates the bundle and signatures and writes a metadata-only report.
7. A security administrator reads the gate-status endpoint. Missing, invalid, stale or blocked evidence remains
   fail-closed.
8. Live pilot traffic still requires the separate real-user nomination, privacy, workforce, four-eyes and start chain.

## Audit And Logging

Each successful API read creates a metadata-only audit event. Audit metadata records the schema, state and counts, but
not blocking-reason values, report paths, policy bodies, evidence hashes or evidence content. Invalid report bodies are
never returned and are not written to normal application logs.

## Deliberate Non-Features

- no evidence upload or persistence API;
- no report repair or overwrite API;
- no deployment, promotion, failover, DNS, traffic or business-write action;
- no placeholder generator for production evidence;
- no downgrade from `security-admin` to a general tenant role.

These omissions preserve accountable evidence ownership and prevent the visibility layer from becoming an execution
or secret-ingestion surface.
