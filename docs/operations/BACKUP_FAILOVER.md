# Backup And Failover

This is the practical operating culture for Collabio backups and failover.

The rule is simple: a backup does not count until it has a checksum, a restore check, an owner, and a recurring drill.

The second rule is just as important: every new durable component must update this continuity model before it can be treated as production-ready.

## Scope

This model covers the whole suite trajectory:

- PostgreSQL metadata, policies, audit events, vector worker audit events, embedding model approval audit events, migration history, vector metadata, and embedding model version approvals.
- File-backed development policy and registry data.
- Source object metadata, object manifests, object storage, WORM records, office documents, collaborative state, mail messages, attachments, parser artifacts, export packages, and audit snapshots.
- KMS references, secret-manager state, key rotation evidence, and destruction evidence.
- Search indexes, vector indexes, indexing checkpoints, benchmark reports, and rebuild cursors.
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
- PostgreSQL audit event rows, checkpoints, and WORM export evidence must be restored together before an audit chain is trusted.
- Vector worker audit events must remain in the deployment audit chain and survive restore verification before recovered vector indexes are trusted.
- Embedding model approval and retirement audit events must be restored with the registry state before source indexing resumes.
- Source object restores must prove metadata and content still match their canonical manifest and content hashes.
- Storage object restores must prove storage manifest hash, object version ID, bucket profile, KMS reference, object-lock configuration, and legal-hold evidence.
- KMS restores must prove adapter policy, key-reference evidence hashes, rotation evidence, cryptoshred manifests, destruction evidence, and no plaintext key export.
- Encrypted object restores must prove envelope manifest hash, ciphertext hash, AAD hash, wrapped data key hash, rewrap evidence hash where present, and KMS evidence hash before decrypting.
- Cryptoshredded object restore evidence must prove source manifest hash, retention manifest hash, cryptoshred manifest hash, KMS destruction evidence hash, and the no-plaintext-key-export claim.
- Restore drills must produce a restore drill report hash that can be recomputed from the report payload.
- Content hash verification must use the shared verifier so write, read, restore, parser, and export checks produce comparable evidence.
- Retention manifest restores must prove retain-until, policy snapshot hash, WORM requirement, Object Lock mode, and Legal Hold state.
- Legal Hold restores must prove hold decisions, release decisions, matter references, source versions, and retention re-evaluation evidence.
- Object-store failover must preserve bucket profile evidence, version IDs, Object Lock posture, retention configuration, and legal-hold state.
- Rebuildable indexes still require checkpoint, rebuild order, freshness, and integrity checks.
- Vector index rebuilds must verify metadata schema, embedding model version approvals, embedding dimensions, ACL hashes, ACL versions, lifecycle state, source checkpoints, and benchmark report hashes before ANN candidates are trusted.
- Secrets and key material are recovered through KMS/secret-manager mechanisms, never through plaintext dumps.

## Continuity Domains

The machine-readable policy in `docs/operations/backup_failover_policy.json` tracks continuity domains across the roadmap:

- tenant IAM and authorization
- PostgreSQL metadata
- audit evidence
- source object metadata, source-object storage manifests, source-object write receipts, and object storage records
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
- module registry state and tenant module lifecycle
- CRM/ERP business records, GoBD-relevant records, and SQL Server migration evidence
- knowledge-base article versions, source-object write receipt hashes, source attachments, and publication approvals
- LMS courses, enrollments, completion evidence, and certificates
- tasks, activities, assignments, workflow state, and due dates
- incident reports, tickets, SLA state, communications, and escalation evidence
- time entries, corrections, approvals, and export metadata

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

Run the Knowledge Base runtime reconciliation worker after a restore drill or before a production-write activation:

```bash
docker compose run --rm kb-runtime-reconciler
```

The worker emits metadata-only `knowledge_base_runtime_reconciliation_run_report.v1` evidence with selected and skipped tenants, retry attempts, alert severity, runtime reconciliation evidence hashes, and bound restore drill report hashes.

Run the module registry operations drill after migrations, before module API smoke checks, and after restore drills:

```bash
docker compose run --rm module-registry-drill
```

The drill emits metadata-only `module_registry_operations_report.v1` evidence for seed/backfill/repair readiness, required migration versions, worker discovery, lifecycle audit event expectations, and module-registry backup artifacts.

Before LMS package installation approval, call `GET /v1/platform/modules/families/lms/restore-drill-evidence`. The endpoint emits metadata-only `lms_restore_drill_evidence.v1` with an evidence hash for `lms_training_records`, verifies the `0045`/`0046` migration boundary, RLS/tenant isolation, retention, Legal Hold, KMS/audit references, and confirms that no LMS package installation, tenant module state, runtime, worker, or content payload is created.

Before Tickets & Incidents tenant provisioning, business API activation, or worker/runtime activation, call `GET /v1/platform/modules/families/tickets-incidents/storage-migration-evidence`, then `GET /v1/platform/modules/families/tickets-incidents/restore-drill-evidence`. The storage endpoint emits metadata-only `tickets_incidents_storage_migration_evidence.v1`; the restore endpoint emits metadata-only `tickets_incidents_restore_drill_evidence.v1` with an evidence hash for `ticket_incident_records`, verifies migration `0052_tickets_incidents_metadata_schema.sql`, ticket/event metadata tables, RLS/tenant isolation, retention, Legal Hold, KMS/audit references, SLA state, backup evidence, and confirms that no storage execution approval, tenant state, worker, runtime, message body, attachment payload, RAG index, or AI/voice content payload is created. The next gates are `GET /v1/platform/modules/families/tickets-incidents/tenant-admin-activation-approval-gate`, `POST /v1/platform/modules/families/tickets-incidents/tenant-admin-activation-approval-records`, `POST /v1/platform/modules/families/tickets-incidents/activation-execution-boundary`, `POST /v1/platform/modules/families/tickets-incidents/activation-executor-skeleton`, `POST /v1/platform/modules/families/tickets-incidents/activation-dry-run-plan`, `POST /v1/platform/modules/families/tickets-incidents/activation-dry-run-execution-boundary`, `POST /v1/platform/modules/families/tickets-incidents/activation-dry-run-execution-skeleton`, `POST /v1/platform/modules/families/tickets-incidents/activation-dry-run-executor-implementation-review`, `POST /v1/platform/modules/families/tickets-incidents/activation-dry-run-result-contract`, `POST /v1/platform/modules/families/tickets-incidents/activation-dry-run-execution-gate`, `POST /v1/platform/modules/families/tickets-incidents/activation-dry-run-execution-request-boundary`, and `POST /v1/platform/modules/families/tickets-incidents/activation-dry-run-executor-runtime-boundary`; the approval record, activation execution boundary, activation executor skeleton, activation dry-run plan, activation dry-run execution boundary, activation dry-run execution skeleton, activation dry-run executor implementation review, activation dry-run result contract, activation dry-run execution gate, activation dry-run execution request boundary, and activation dry-run executor runtime boundary store only metadata and hashes, and the following step is an activation dry-run execution preflight before any activation path. Restore drill evidence must include the Tickets & Incidents activation dry-run execution gate hash, Tickets & Incidents activation dry-run execution request boundary hash, and Tickets & Incidents activation dry-run executor runtime boundary hash when applicable.

Run the Legacy SQL discovery intake drill before any real SQL metadata worker command is scheduled:

```bash
docker compose run --rm legacy-sql-discovery-intake
```

The drill emits metadata-only `legacy_sql_discovery_intake_operations_report.v1` evidence. It verifies that a
tenant-scoped discovery request, approval reference, connector policy hash, and approved host profile can produce a
redacted metadata-worker command view. The report includes the intake evidence hash and redacted command hash, but no
Secret reference, DSN, real connection execution, import dry-run, import write, raw data import, or destructive action.

Persist Legacy SQL evidence hashes in the tenant-scoped ledger before any real Legacy SQL connection is approved.
`collabio.legacy_sql_evidence_ledger` stores metadata-only `legacy_sql_evidence_ledger_entry.v1` records with RLS,
append-only policies, restore-evidence hashes, evidence type, source-system reference, related evidence hashes, and
status. It must not store report payloads, table data, DSNs, Secret references, sample values, raw rows, or import write
payloads.

The intake and readiness drills can append their report hashes to this ledger by setting
`SUITE_LEGACY_SQL_EVIDENCE_LEDGER_WRITE=true` and providing `SUITE_LEGACY_SQL_EVIDENCE_LEDGER_RESTORE_HASH`. The write path
keeps stdout reports unchanged and persists only hashes plus metadata-only status fields, so restore drills can bind
ledger entries back to the exact report hash chain without storing legacy data.

Run the Legacy SQL evidence ledger backend drill before real Legacy SQL host profiles are approved:

```bash
docker compose run --rm legacy-sql-evidence-ledger-drill
```

The drill emits metadata-only `legacy_sql_evidence_ledger_operations_report.v1` evidence. It writes intake and readiness
report hashes through the JSONL and PostgreSQL ledger backends, reloads entries by tenant, checks restore-evidence hash
binding, rejects duplicate appends, verifies tenant isolation, and keeps real connections, import dry-runs, import writes,
raw SQL rows, and destructive actions outside the path. Its report hash is the release/restore precondition for enabling
real Legacy SQL host profiles later. The Legacy SQL evidence ledger operations report hash must be retained with restore
evidence.

Run the Legacy SQL host-profile release-gate smoke before wiring any real Legacy SQL host profile adapter:

```bash
docker compose run --rm legacy-sql-host-profile-release-gate-smoke
```

The smoke emits metadata-only `legacy_sql_host_profile_release_gate_smoke_report.v1` evidence. It first runs the evidence
ledger operations drill, then persists one ready and one blocked `legacy_sql_host_profile_release_gate.v1` record in the
PostgreSQL/RLS-backed release-gate store. The ready path must pass the wiring guard; the blocked path must be rejected.
The report and stored gate evidence contain no DSN, raw SQL rows, table data, Secret reference, import payload, or
destructive action payload. A real host-profile adapter may only be prepared after this smoke is green.

Run the Legacy SQL host-profile adapter smoke before a metadata worker queue or real host-network profile is connected:

```bash
docker compose run --rm legacy-sql-host-profile-adapter-smoke
```

The smoke emits metadata-only `legacy_sql_host_profile_adapter_smoke_report.v1` evidence. It loads persisted ready
release-gate evidence tenant-scoped, binds the approved egress reference and hashed Secret reference to a redacted
metadata-worker command view, proves the blocked gate cannot be scheduled, and keeps the default Compose path from
opening any Legacy SQL network connection. The schedule evidence is `legacy_sql_host_profile_adapter_schedule.v1`.

Run the Legacy SQL metadata worker queue drill before a real metadata worker lease consumer is connected:

```bash
docker compose run --rm legacy-sql-metadata-worker-queue-drill
```

The drill emits metadata-only `legacy_sql_metadata_worker_queue_operations_report.v1` evidence. It persists
`legacy_sql_host_profile_adapter_schedule.v1` as a tenant-scoped, idempotent
`legacy_sql_metadata_worker_queue_job.v1`, proves duplicate enqueue idempotency, leases the job once, records retry
evidence with restore-hash binding, verifies tenant isolation, and keeps the default Compose path from opening any
Legacy SQL network connection. The persistent table is `collabio.legacy_sql_metadata_worker_queue`.

Run the Legacy SQL metadata worker lease-consumer smoke before any real connector sandbox profile is enabled:

```bash
docker compose run --rm legacy-sql-metadata-worker-lease-consumer-smoke
```

The smoke emits metadata-only `legacy_sql_metadata_worker_lease_consumer_smoke_report.v1` evidence. It acquires a
tenant-scoped queue lease, validates `legacy_sql_metadata_worker_lease_consumer_activation.v1` evidence, rejects queued
or expired jobs, verifies egress/Secret/Fingerprint handles as handles only, and keeps Secret material resolution,
Legacy SQL network connections, raw data reads, import dry-runs, import writes, and destructive actions disabled.

Run the Legacy SQL connector sandbox profile smoke before any real connector network or secret resolver is wired:

```bash
docker compose run --rm legacy-sql-connector-sandbox-profile-smoke
```

The smoke emits metadata-only `legacy_sql_connector_sandbox_profile_smoke_report.v1` evidence. It proves that
`legacy_sql_connector_sandbox_profile.v1` is visible only behind release-gate evidence, queue lease, and lease-consumer
activation, while the profile itself remains default-off. Network profile, Secret resolver profile, and audit profile
are retained as handles only; direct enablement is rejected.

Run the Legacy SQL connector sandbox enablement gate smoke before any real connector connection attempt is prepared:

```bash
docker compose run --rm legacy-sql-connector-sandbox-enablement-gate-smoke
```

The smoke emits metadata-only `legacy_sql_connector_sandbox_enablement_gate_smoke_report.v1` evidence. It binds
`legacy_sql_connector_sandbox_provider_attestation.v1`, `legacy_sql_connector_sandbox_enablement_gate.v1`, explicit
human confirmation, provider-attestation hash, restore-evidence hash, and sandbox-profile hash before a later real
connection-attempt gate can exist. The gate may only allow control-plane preparation; Secret materialization, network
materialization, raw data access, import dry-run, import write, and destructive actions remain disabled.

Run the Legacy SQL connector provider-attestation adapter smoke before any real provider handle is used:

```bash
docker compose run --rm legacy-sql-connector-provider-attestation-adapter-smoke
```

The smoke emits metadata-only `legacy_sql_connector_provider_attestation_adapter_smoke_report.v1` evidence. It validates
`legacy_sql_connector_provider_network_profile.v1`, `legacy_sql_connector_provider_secret_resolver_profile.v1`, and
`legacy_sql_connector_provider_audit_profile.v1` against the default-off sandbox profile, emits
`legacy_sql_connector_provider_attestation_adapter.v1`, and proves that the resulting provider attestation is accepted
by the enablement gate. The adapter does not resolve Secret material, does not open a network connection, does not read
raw data, and does not allow import dry-run or import write.

Run the Legacy SQL connector connection preflight gate smoke before any future real connection executor is implemented:

```bash
docker compose run --rm legacy-sql-connector-connection-preflight-gate-smoke
```

The smoke emits metadata-only `legacy_sql_connector_connection_attempt_preflight_gate_smoke_report.v1` evidence. It binds
`legacy_sql_connector_operator_context.v1`, `legacy_sql_connector_connection_attempt_preflight_gate.v1`, the
enablement-gate hash, provider-attestation-adapter hash, restore-evidence hash, operator authorization, MFA state,
change request, maintenance window, and approval reference. It is a final no-secret/no-socket proof: no Secret material
is resolved, no network socket is opened, no raw data is read, and no import dry-run or import write is allowed.

Run the Legacy SQL real-connection executor contract smoke before any socket or Secret materialization is designed:

```bash
docker compose run --rm legacy-sql-connector-real-connection-executor-smoke
```

The smoke emits metadata-only `legacy_sql_connector_real_connection_executor_smoke_report.v1` evidence. It binds
`legacy_sql_connector_real_connection_timeout_retry_policy.v1`,
`legacy_sql_connector_real_connection_audit_plan.v1`,
`legacy_sql_connector_real_connection_kill_switch_policy.v1`, and
`legacy_sql_connector_real_connection_executor_contract.v1` to the preflight hash and restore evidence. The contract
defines timeout/retry limits, audit event coverage, redaction, manual abort, tenant and global kill-switch refs. It is
still non-executing: no Secret material is resolved, no socket is opened, no raw data is read, and no import dry-run or
import write is allowed.

Run the Legacy SQL real-connection executor policy-store smoke before any executor contract is trusted across restarts:

```bash
docker compose run --rm legacy-sql-connector-real-connection-executor-policy-store-smoke
```

The smoke emits metadata-only `legacy_sql_connector_real_connection_executor_policy_store_smoke_report.v1` evidence. It
persists `legacy_sql_connector_real_connection_executor_policy_bundle.v1` in the tenant-scoped policy store, roundtrips
the bundle, proves duplicate appends are idempotent, and checks tenant isolation. The persisted bundle contains only
`legacy_sql_connector_real_connection_timeout_retry_policy.v1`,
`legacy_sql_connector_real_connection_audit_plan.v1`,
`legacy_sql_connector_real_connection_kill_switch_policy.v1`, and the non-executing executor contract. It still does
not resolve Secret material, open sockets, read raw data, or allow import dry-run/write.

Run the Legacy SQL execution-readiness review gate smoke before any Socket or Secret materialization is even planned:

```bash
docker compose run --rm legacy-sql-connector-execution-readiness-review-gate-smoke
```

The smoke emits metadata-only `legacy_sql_connector_execution_readiness_review_gate_smoke_report.v1` evidence. It binds
`legacy_sql_connector_execution_readiness_human_review.v1`,
`legacy_sql_connector_execution_readiness_change_control.v1`,
`legacy_sql_connector_execution_readiness_restore_drill.v1`, and
`legacy_sql_connector_execution_readiness_review_gate.v1` to the stored executor policy bundle. It proves missing human
review, incomplete change control, disabled kill switches, and materialization-planning requests are blocked. It still
does not resolve Secret material, open sockets, read raw data, or allow import dry-run/write.

Run the Legacy SQL materialization plan gate smoke before any Socket or Secret materialization implementation is designed:

```bash
docker compose run --rm legacy-sql-connector-materialization-plan-gate-smoke
```

The smoke emits metadata-only `legacy_sql_connector_materialization_plan_gate_smoke_report.v1` evidence. It binds
`legacy_sql_connector_materialization_provider_profile_snapshot.v1`,
`legacy_sql_connector_materialization_operator_mfa_snapshot.v1`,
`legacy_sql_connector_materialization_kill_switch_snapshot.v1`, and
`legacy_sql_connector_materialization_plan_gate.v1` to the review gate and stored executor policy bundle. It proves a
missing review gate, missing operator MFA, disabled kill switches, and direct Socket/Secret/execution requests are
blocked. It still does not resolve Secret material, open sockets, read raw data, or allow import dry-run/write.

Run the Legacy SQL socket/secret implementation ADR gate smoke before any executable connector implementation PR is
started:

```bash
docker compose run --rm legacy-sql-connector-socket-secret-implementation-adr-gate-smoke
```

The smoke emits metadata-only `legacy_sql_connector_socket_secret_implementation_adr_gate_smoke_report.v1` evidence. It
binds `legacy_sql_connector_socket_secret_provider_limits_snapshot.v1`,
`legacy_sql_connector_socket_secret_network_route_snapshot.v1`,
`legacy_sql_connector_socket_secret_secret_manager_snapshot.v1`,
`legacy_sql_connector_socket_secret_rollback_runbook_snapshot.v1`,
`legacy_sql_connector_socket_secret_kill_switch_runbook_snapshot.v1`, and
`legacy_sql_connector_socket_secret_implementation_adr_gate.v1` to the materialization plan gate and stored executor
policy bundle. It proves missing materialization-plan evidence, missing provider limits, missing network-route approval,
missing Secret-manager readiness, missing rollback runbook evidence, missing kill-switch runbook evidence, and direct
runtime implementation requests are blocked. It still does not resolve Secret material, open sockets, read raw data,
generate executor code, or allow import dry-run/write.

Run the Legacy SQL runtime PR gate smoke before any executable Socket or Secret runtime code is merged:

```bash
docker compose run --rm legacy-sql-connector-runtime-pr-gate-smoke
```

The smoke emits metadata-only `legacy_sql_connector_runtime_pr_gate_smoke_report.v1` evidence. It binds
`legacy_sql_connector_runtime_pr_code_review_snapshot.v1`,
`legacy_sql_connector_runtime_pr_test_container_snapshot.v1`,
`legacy_sql_connector_runtime_pr_secret_binding_snapshot.v1`,
`legacy_sql_connector_runtime_pr_network_binding_snapshot.v1`,
`legacy_sql_connector_runtime_pr_rollback_probe_snapshot.v1`,
`legacy_sql_connector_runtime_pr_kill_switch_probe_snapshot.v1`, and
`legacy_sql_connector_runtime_pr_gate.v1` to the socket/secret implementation ADR gate. It proves missing ADR evidence,
missing code review, missing hardened test container evidence, missing Secret-manager binding, missing network-route
binding, missing rollback probe, missing kill-switch probe, and direct merge/runtime requests are blocked. It still does
not merge runtime code, resolve Secret material, open sockets, read raw data, or allow import dry-run/write.

Run the Legacy SQL runtime merge gate smoke before executable Socket or Secret code becomes activatable runtime:

```bash
docker compose run --rm legacy-sql-connector-runtime-merge-gate-smoke
```

The smoke emits metadata-only `legacy_sql_connector_runtime_merge_gate_smoke_report.v1` evidence. It binds
`legacy_sql_connector_runtime_merge_branch_protection_snapshot.v1`,
`legacy_sql_connector_runtime_merge_security_scan_snapshot.v1`,
`legacy_sql_connector_runtime_merge_container_provenance_snapshot.v1`,
`legacy_sql_connector_runtime_merge_secret_rotation_plan_snapshot.v1`,
`legacy_sql_connector_runtime_merge_kill_switch_drill_snapshot.v1`, and
`legacy_sql_connector_runtime_merge_gate.v1` to the runtime PR gate. It proves missing PR-gate evidence, missing branch
protection, missing security scan, missing container provenance, missing Secret-rotation plan, missing kill-switch drill,
and direct activation/runtime requests are blocked. It still does not merge runtime code, activate runtime, resolve
Secret material, open sockets, read raw data, or allow import dry-run/write.

Run the Legacy SQL runtime activation gate smoke before real connection probes can be prepared:

```bash
docker compose run --rm legacy-sql-connector-runtime-activation-gate-smoke
```

The smoke emits metadata-only `legacy_sql_connector_runtime_activation_gate_smoke_report.v1` evidence. It binds
`legacy_sql_connector_runtime_activation_tenant_approval_snapshot.v1`,
`legacy_sql_connector_runtime_activation_feature_flag_snapshot.v1`,
`legacy_sql_connector_runtime_activation_secret_rotation_confirmation_snapshot.v1`,
`legacy_sql_connector_runtime_activation_network_authorization_snapshot.v1`,
`legacy_sql_connector_runtime_activation_rollback_freeze_snapshot.v1`,
`legacy_sql_connector_runtime_activation_kill_switch_arming_snapshot.v1`, and
`legacy_sql_connector_runtime_activation_gate.v1` to the runtime merge gate. It proves missing merge-gate evidence,
missing tenant approval, missing feature-flag profile, missing Secret-rotation confirmation, missing network
authorization, missing rollback freeze, missing kill-switch arming, and direct connection/runtime requests are blocked.
It still does not activate runtime, enable runtime feature flags, resolve Secret material, open sockets, read raw data,
or allow import dry-run/write.

Run the Legacy SQL live connection gate smoke before the first real metadata-only connection probe can be implemented:

```bash
docker compose run --rm legacy-sql-connector-live-connection-gate-smoke
```

The smoke emits metadata-only `legacy_sql_connector_live_connection_gate_smoke_report.v1` evidence. It binds
`legacy_sql_connector_live_connection_secret_broker_binding_snapshot.v1`,
`legacy_sql_connector_live_connection_network_egress_policy_snapshot.v1`,
`legacy_sql_connector_live_connection_least_privilege_db_role_snapshot.v1`,
`legacy_sql_connector_live_connection_timeout_circuit_breaker_snapshot.v1`,
`legacy_sql_connector_live_connection_audit_sink_snapshot.v1`,
`legacy_sql_connector_live_connection_emergency_disable_snapshot.v1`, and
`legacy_sql_connector_live_connection_gate.v1` to the runtime activation gate. It proves missing activation-gate
evidence, missing Secret-broker binding, missing network egress policy, missing least-privilege database role, missing
timeout/circuit-breaker rules, missing audit sink, missing emergency disable, and direct probe/runtime requests are
blocked. It still does not execute a metadata-only probe, resolve Secret material, open sockets, read raw data, or allow
import dry-run/write.

Run the Legacy SQL metadata connection probe gate smoke before the first real metadata-only probe implementation starts:

```bash
docker compose run --rm legacy-sql-connector-metadata-connection-probe-gate-smoke
```

The smoke emits metadata-only `legacy_sql_connector_metadata_connection_probe_gate_smoke_report.v1` evidence. It binds
`legacy_sql_connector_metadata_connection_probe_provider_driver_snapshot.v1`,
`legacy_sql_connector_metadata_connection_probe_secret_broker_read_path_snapshot.v1`,
`legacy_sql_connector_metadata_connection_probe_query_allowlist_snapshot.v1`,
`legacy_sql_connector_metadata_connection_probe_timeout_circuit_breaker_execution_snapshot.v1`,
`legacy_sql_connector_metadata_connection_probe_audit_sink_execution_snapshot.v1`,
`legacy_sql_connector_metadata_connection_probe_emergency_disable_execution_snapshot.v1`, and
`legacy_sql_connector_metadata_connection_probe_gate.v1` to the live connection gate. It proves missing live-gate
evidence, missing provider-driver readiness, missing Secret-broker read path, missing metadata-query allowlist, missing
timeout/circuit-breaker execution, missing audit sink, missing emergency disable, and direct provider/Secret/query/socket
or raw-data requests are blocked. It still does not load a provider driver, read a Secret broker, execute metadata
queries, open sockets, resolve Secret material, read raw data, or allow import dry-run/write.

Run the Legacy SQL metadata connection probe skeleton smoke before a live provider adapter is enabled:

```bash
docker compose run --rm legacy-sql-connector-metadata-connection-probe-skeleton-smoke
```

The smoke emits metadata-only `legacy_sql_connector_metadata_connection_probe_skeleton_smoke_report.v1` evidence. It
binds `legacy_sql_connector_metadata_connection_probe_skeleton_command.v1`,
`legacy_sql_connector_metadata_connection_probe_execution_plan.v1`, and
`legacy_sql_connector_metadata_connection_probe_execution_evidence.v1` to the metadata-connection-probe gate. It proves
Default-Off, tenant kill switch, raw-data request blocking, and an explicitly enabled offline fixture path. The fixture
path may invoke the provider-adapter contract and Secret-handle metadata read, but it does not open an external socket,
load a real provider driver, materialize Secret values, expose table or column names, read raw rows, or allow import
work.

Run the Legacy SQL metadata connection probe live adapter smoke before legacy SQL probing is considered available:

```bash
docker compose run --rm legacy-sql-connector-metadata-connection-probe-live-adapter-smoke
```

The smoke emits metadata-only `legacy_sql_connector_metadata_connection_probe_live_adapter_smoke_report.v1` evidence. It
binds `legacy_sql_connector_metadata_connection_probe_live_adapter_command.v1` and
`legacy_sql_connector_metadata_connection_probe_live_adapter_evidence.v1` to the skeleton evidence boundary. It proves
Default-Off, missing Secret materialization, missing network route, and emergency stop block before touching the provider.
The enabled Postgres path opens only the approved internal metadata route, enforces a read-only transaction, returns only
metadata counts and hashes, keeps Secret material inside the worker, and still forbids raw rows, sample values, import
dry-run/write, and destructive actions.

Run the Legacy SQL readiness smoke before real SQL connections, import dry-runs, or CRM/ERP migration readiness claims:

```bash
docker compose run --rm legacy-sql-readiness-smoke
docker compose run --rm legacy-sql-import-dry-run-worker
docker compose run --rm legacy-sql-import-write-approval-gate-smoke
```

The smoke emits metadata-only `legacy_sql_readiness_smoke_report.v1` evidence. It runs the SQL Server metadata worker
against an internal metadata fixture, verifies the discovery/import/mapping/readiness hash chain, proves quarantined
`legacy.row` fallbacks block dry-run, proves approved mapping overrides only unlock metadata-only dry-run, and keeps real
connections, import writes, raw data import, and destructive actions disabled.

Legacy SQL staging metadata profiles are persisted as `crm_erp_legacy_staging_metadata_profile.v1` rows in
`crm_erp_legacy.staging_metadata_profiles`. They bind `persistent_object_metadata.v1` required fields to approved
metadata-only sources before any row materialization exists. Restore evidence must retain the Legacy SQL staging metadata
profile hash; the profile table still forbids raw rows, sample values, DSNs, Secret references, import writes, and
destructive actions.

Legacy SQL import dry-run plans are persisted as `crm_erp_legacy_import_dry_run_plan.v1` rows in
`crm_erp_legacy.import_dry_run_plans`. They bind readiness evidence and staging metadata profile hashes to required
row-count checks, checksum manifest strategy, and audit event types. Restore evidence must retain the Legacy SQL import
dry-run plan hash when applicable; the plan table remains metadata-only and forbids import writes, raw data imports,
and destructive actions.

Legacy SQL import dry-run results are persisted as `legacy_sql_import_dry_run_result.v1` rows in
`crm_erp_legacy.import_dry_run_results`. The metadata-only worker records row-count observations, checksum manifest
hashes, audit event types, plan/result hashes, and block reasons without raw SQL rows or import writes. Restore evidence
must retain the Legacy SQL import dry-run result hash and worker report hash when applicable.

Legacy SQL import write approval gate evidence is persisted as `legacy_sql_import_write_approval_gate.v1` rows in
`crm_erp_legacy.import_write_approval_gates`. The gate binds a completed dry-run result, worker report, human review,
change-control, rollback plan, and restore-drill hashes. It may allow only a future human approval record; import write
execution, raw data access, import payloads, destructive actions, and external side effects stay false. Restore evidence
must retain the Legacy SQL import write approval gate hash and smoke report hash when applicable.

The Legacy SQL import write approval request boundary API is not a persistence domain. It reads stored approval gate
evidence, returns metadata-only request-boundary evidence, and remains recoverable through the audit log plus the
retained approval gate evidence hash. Dedicated approval-record state is handled separately by migration `0043`.

The Legacy SQL import write approval record persistence plan is evidence-only. Migration `0043` adds the future
approval-record store as a new PostgreSQL state domain for `legacy_sql_import_write_approval_record.v1` with RLS,
append-only policies, idempotency-key uniqueness, restore-evidence hashes, audit references, and DB checks that keep
import write execution, raw data access, payloads,
destructive actions, and external side effects forbidden. Restore evidence must retain the Legacy SQL import write
approval record hash when applicable.

Migration `0044` adds the future Legacy SQL migration run registry and metadata-only report skeleton as PostgreSQL
state domains for `legacy_sql_migration_run_registry_entry.v1` and `legacy_sql_migration_report_metadata.v1`. Both
stores are tenant-scoped, append-only, idempotent and RLS-protected. They retain only metadata, hashes, counts, restore
evidence and audit references; run creation, report retrieval, import write execution, raw data access, payloads,
destructive actions and external side effects stay disabled. Restore evidence must retain the migration run registry
hash and metadata-only report hash when applicable.

Run the preview renderer recovery drill after preview decision or renderer evidence changes and after restore drills:

```bash
docker compose run --rm preview-renderer-drill
```

The drill emits metadata-only `source_object_preview_renderer_recovery_drill_report.v1` evidence for preview decision recovery, renderer evidence recovery, worker queue binding replay, idempotency hash replay, tenant isolation smoke checks, and content-boundary checks.

Run the preview renderer API smoke fixture before preview-renderer production-readiness claims:

```bash
docker compose run --rm preview-renderer-smoke
```

The smoke fixture creates preview renderer and preview decision evidence through the API, runs the recovery drill against
the PostgreSQL-backed stores, creates a release gate from both hashes, persists that gate in the configured gate evidence
store, and emits a metadata-only `source_object_preview_renderer_release_gate_smoke_report.v1` report. In Compose this
uses the PostgreSQL/RLS-backed `collabio.source_object_preview_renderer_release_gate_evidence` table. Use
`python -m suite.platform.source_object_preview_renderer_smoke --api-only` only when diagnosing the lower-level API smoke
report.

Before any production renderer, viewer, or content release workflow is connected, create
`source_object_preview_renderer_release_gate.v1` evidence from a fresh API smoke report and its bound recovery drill
report. A blocked release gate keeps renderer, viewer, and content-release wiring disabled even if lower-level evidence
exists.

Local dumps are written to `./backups/`, which is gitignored.

## Minimum Restore Drill

Monthly for active development and before every production-readiness milestone:

1. Run `docker compose run --rm backup`.
2. Run `docker compose run --rm backup-verify`.
3. Run `docker compose run --rm module-registry-drill`.
4. Before CRM/ERP Legacy SQL metadata worker scheduling, run `docker compose run --rm legacy-sql-discovery-intake`.
5. Before CRM/ERP Legacy SQL migration readiness claims, run `docker compose run --rm legacy-sql-readiness-smoke`.
6. Before CRM/ERP Legacy SQL host-profile adapters are prepared, run `docker compose run --rm legacy-sql-host-profile-release-gate-smoke`.
7. Before CRM/ERP Legacy SQL metadata-worker scheduling is wired, run `docker compose run --rm legacy-sql-host-profile-adapter-smoke`.
8. Before CRM/ERP Legacy SQL metadata-worker leases are consumed, run `docker compose run --rm legacy-sql-metadata-worker-queue-drill`.
9. Before CRM/ERP Legacy SQL connector sandbox profiles are enabled, run `docker compose run --rm legacy-sql-metadata-worker-lease-consumer-smoke`.
10. Before CRM/ERP Legacy SQL connector network or secret resolver profiles are wired, run `docker compose run --rm legacy-sql-connector-sandbox-profile-smoke`.
11. Before CRM/ERP Legacy SQL connector connection attempts are prepared, run `docker compose run --rm legacy-sql-connector-sandbox-enablement-gate-smoke`.
12. Before CRM/ERP Legacy SQL provider handles are trusted, run `docker compose run --rm legacy-sql-connector-provider-attestation-adapter-smoke`.
13. Before CRM/ERP Legacy SQL real connection executor contracts are trusted, run `docker compose run --rm legacy-sql-connector-connection-preflight-gate-smoke`.
14. Before CRM/ERP Legacy SQL socket or Secret materialization is designed, run `docker compose run --rm legacy-sql-connector-real-connection-executor-smoke`.
15. Before CRM/ERP Legacy SQL executor contracts are trusted across restarts, run `docker compose run --rm legacy-sql-connector-real-connection-executor-policy-store-smoke`.
16. Before CRM/ERP Legacy SQL Socket or Secret materialization is planned, run `docker compose run --rm legacy-sql-connector-execution-readiness-review-gate-smoke`.
17. Before CRM/ERP Legacy SQL Socket or Secret implementation is designed, run `docker compose run --rm legacy-sql-connector-materialization-plan-gate-smoke`.
18. Before CRM/ERP Legacy SQL executable connector implementation PRs are started, run `docker compose run --rm legacy-sql-connector-socket-secret-implementation-adr-gate-smoke`.
19. Before CRM/ERP Legacy SQL Socket or Secret runtime code is merged, run `docker compose run --rm legacy-sql-connector-runtime-pr-gate-smoke`.
20. Before CRM/ERP Legacy SQL Socket or Secret runtime becomes activatable, run `docker compose run --rm legacy-sql-connector-runtime-merge-gate-smoke`.
21. Before CRM/ERP Legacy SQL first connection probes can be prepared, run `docker compose run --rm legacy-sql-connector-runtime-activation-gate-smoke`.
22. Before CRM/ERP Legacy SQL metadata-only connection probes are planned, run `docker compose run --rm legacy-sql-connector-live-connection-gate-smoke`.
23. Before CRM/ERP Legacy SQL first metadata-only connection probe is implemented, run `docker compose run --rm legacy-sql-connector-metadata-connection-probe-gate-smoke`.
24. Before CRM/ERP Legacy SQL live provider adapter work starts, run `docker compose run --rm legacy-sql-connector-metadata-connection-probe-skeleton-smoke`.
25. Before CRM/ERP Legacy SQL metadata-only live provider probes are trusted, run `docker compose run --rm legacy-sql-connector-metadata-connection-probe-live-adapter-smoke`.
26. Before CRM/ERP Legacy SQL import write approval records are trusted, run `docker compose run --rm legacy-sql-import-write-approval-gate-smoke`.
27. For preview-renderer release gates, run `docker compose run --rm preview-renderer-smoke`.
28. For tenants with preview decision or renderer evidence, run `docker compose run --rm preview-renderer-drill`.
29. For tenants with active Knowledge Base production runtime evidence, run `docker compose run --rm kb-runtime-reconciler`.
30. Record backup filename, SHA-256 checksum, migration versions, operator, date, result, restore drill report hash, module registry operations report hash, Legacy SQL evidence ledger hash, Legacy SQL discovery intake operations report hash, Legacy SQL readiness smoke report hash, Legacy SQL staging metadata profile hash, Legacy SQL import dry-run plan hash, Legacy SQL import dry-run result hash, Legacy SQL import dry-run worker report hash, Legacy SQL import write approval gate hash, Legacy SQL import write approval gate smoke report hash, Legacy SQL import write approval record hash, Legacy SQL migration run registry hash, Legacy SQL migration metadata-only report hash, Legacy SQL host profile release gate evidence hash, Legacy SQL metadata worker queue operations report hash, Legacy SQL metadata worker lease consumer smoke report hash, Legacy SQL connector sandbox profile smoke report hash, Legacy SQL connector sandbox enablement gate smoke report hash, Legacy SQL connector provider attestation adapter smoke report hash, Legacy SQL connector connection preflight gate smoke report hash, Legacy SQL connector real connection executor smoke report hash, Legacy SQL connector real connection executor policy store smoke report hash, Legacy SQL connector execution readiness review gate smoke report hash, Legacy SQL connector materialization plan gate smoke report hash, Legacy SQL connector socket-secret implementation ADR gate smoke report hash, Legacy SQL connector runtime PR gate smoke report hash, Legacy SQL connector runtime merge gate smoke report hash, Legacy SQL connector runtime activation gate smoke report hash, Legacy SQL connector live connection gate smoke report hash, Legacy SQL connector metadata connection probe gate smoke report hash, Legacy SQL connector metadata connection probe skeleton smoke report hash, Legacy SQL connector metadata connection probe live adapter smoke report hash, preview renderer API smoke report hash, preview renderer recovery drill report hash, preview renderer release gate evidence hash, and Knowledge Base runtime reconciliation run report hash when applicable.
31. For production, restore into an isolated environment and run the domain-specific checks from the policy.
32. Update the policy and this runbook when the restore path changes.

Object-storage restore evidence must include the verifier context, expected content hash, actual content hash, byte length, source object version, storage manifest hash, envelope manifest hash, retention manifest hash, cryptoshred manifest hash when present, restore drill report hash, object version ID, bucket profile, object-lock state, legal-hold state, KMS evidence hash, rotation evidence hash when present, and source manifest hash result before data is served to office, mail, parser, search, RAG, or e-discovery flows.

Search and vector restore evidence must include the source checkpoint, ACL checkpoint, benchmark report hash, metadata schema result, and recall baseline result before rebuilt indexes or ANN candidates are trusted.

## Failover Stance

Current development:

- no automatic failover
- manual restart/recreate of local services
- logical dumps for recovery rehearsal

Production target:

- PostgreSQL PITR with WAL archiving
- object storage versioning and object lock for record/evidence classes
- KMS/secret-manager recovery path with no plaintext key export
- KMS adapter policy and key-usage evidence verification before encrypted object restore is trusted
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
- Does module enablement, disablement, suspension, or decommissioning change?
- Does the module registry drill still pass for seed, backfill, repair, worker discovery, audit, and backup evidence?

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
- Which module registry operations report hash was produced?
- Which Legacy SQL host profile release gate evidence hash allowed or blocked host-profile wiring?
- Which Legacy SQL connector sandbox enablement gate evidence hash allowed or blocked connection-attempt preparation?
- Which Legacy SQL connector provider attestation adapter evidence hash validated the deployment handles?
- Which Legacy SQL connector connection preflight gate evidence hash proved the no-secret/no-socket boundary?
- Which Legacy SQL connector socket-secret implementation ADR gate evidence hash allowed or blocked runtime PR preparation?
- Which Legacy SQL connector runtime PR gate evidence hash allowed or blocked executable runtime merge preparation?
- Which Legacy SQL connector runtime merge gate evidence hash allowed or blocked activatable runtime preparation?
- Which Legacy SQL connector runtime activation gate evidence hash allowed or blocked first connection-probe preparation?
- Which Legacy SQL connector live connection gate evidence hash allowed or blocked first metadata-only connection-probe preparation?
- Which Legacy SQL connector metadata connection probe gate evidence hash allowed or blocked first metadata-only probe implementation?
- Which Legacy SQL connector metadata connection probe skeleton evidence hash allowed or blocked live provider adapter preparation?
- Which Legacy SQL connector metadata connection probe live adapter evidence hash proved the metadata-only provider route?
- Which preview renderer API smoke report hash was produced?
- Which preview renderer recovery drill report hash was produced?
- Which preview renderer release gate evidence hash allowed or blocked wiring?
- Which Knowledge Base runtime activations and reconciliation run reports were checked?
