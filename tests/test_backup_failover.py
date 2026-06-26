from pathlib import Path

from suite.operations.backup_failover import backup_policy_summary, load_backup_failover_policy

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = REPO_ROOT / "docs" / "operations" / "backup_failover_policy.json"
RUNBOOK_PATH = REPO_ROOT / "docs" / "operations" / "BACKUP_FAILOVER.md"
MODULE_REGISTRY_RUNBOOK_PATH = REPO_ROOT / "docs" / "operations" / "MODULE_REGISTRY_OPERATIONS.md"
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"

REQUIRED_CONTINUITY_DOMAINS = {
    "tenant_iam_authz",
    "postgres_metadata",
    "audit_evidence",
    "object_storage_records",
    "kms_key_metadata",
    "secrets_configuration",
    "office_documents",
    "mail_messages_threads",
    "mail_attachments",
    "parser_worker_artifacts",
    "search_indexes",
    "vector_indexes",
    "ai_control_plane",
    "model_artifacts",
    "voice_transcripts",
    "ediscovery_exports",
    "observability_operational_logs",
    "repository_and_configuration",
    "background_jobs_queues",
    "module_registry_state",
    "crm_erp_business_records",
    "knowledge_base_content",
    "learning_management_records",
    "task_activity_records",
    "service_ticket_records",
    "time_tracking_records",
}


def test_backup_failover_policy_declares_practical_targets_and_drills() -> None:
    policy = load_backup_failover_policy(POLICY_PATH)

    assert policy.schema_version == "backup_failover_policy.v2"
    assert policy.owner == "platform-operations"
    assert len(policy.targets) == 7
    assert backup_policy_summary(policy) == {
        "schema_version": "backup_failover_policy.v2",
        "owner": "platform-operations",
        "target_count": 7,
        "continuity_domain_count": len(REQUIRED_CONTINUITY_DOMAINS),
        "strictest_rpo_minutes": 15,
        "strictest_rto_hours": 4,
    }

    postgres = policy.target("postgres_primary")
    assert postgres.rpo_minutes <= 15
    assert postgres.rto_hours <= 4
    assert postgres.restore_drill_frequency_days <= 30
    assert "sha256_manifest" in postgres.integrity_checks
    assert "pg_restore_catalog" in postgres.integrity_checks
    assert "vector_metadata_schema_check" in postgres.integrity_checks
    assert "embedding_model_version_approval_check" in postgres.integrity_checks
    assert "acl_version_checkpoint_check" in postgres.integrity_checks
    assert "source_object_storage_manifest_hash_check" in postgres.integrity_checks
    assert "source_object_write_receipt_hash_check" in postgres.integrity_checks
    assert "source_object_preview_decision_evidence_hash_check" in postgres.integrity_checks
    assert "source_object_preview_renderer_evidence_hash_check" in postgres.integrity_checks
    assert "preview_renderer_api_smoke_report_hash_check" in postgres.integrity_checks
    assert "preview_renderer_recovery_drill_report_hash_check" in postgres.integrity_checks
    assert "preview_renderer_release_gate_evidence_hash_check" in postgres.integrity_checks
    assert "legacy_sql_evidence_ledger_hash_check" in postgres.integrity_checks
    assert "legacy_sql_evidence_ledger_operations_report_hash_check" in postgres.integrity_checks
    assert "legacy_sql_staging_metadata_profile_hash_check" in postgres.integrity_checks
    assert "legacy_sql_import_dry_run_plan_hash_check" in postgres.integrity_checks
    assert "legacy_sql_import_dry_run_result_hash_check" in postgres.integrity_checks
    assert "legacy_sql_import_dry_run_worker_report_hash_check" in postgres.integrity_checks
    assert "legacy_sql_import_write_approval_gate_hash_check" in postgres.integrity_checks
    assert "legacy_sql_import_write_approval_gate_smoke_report_hash_check" in postgres.integrity_checks
    assert "legacy_sql_import_write_approval_record_hash_check" in postgres.integrity_checks
    assert "legacy_sql_migration_run_registry_hash_check" in postgres.integrity_checks
    assert "legacy_sql_migration_report_metadata_hash_check" in postgres.integrity_checks
    assert "legacy_sql_host_profile_release_gate_evidence_hash_check" in postgres.integrity_checks
    assert "legacy_sql_metadata_worker_queue_job_hash_check" in postgres.integrity_checks
    assert "legacy_sql_metadata_worker_queue_restore_hash_check" in postgres.integrity_checks
    assert "legacy_sql_metadata_worker_lease_consumer_smoke_report_hash_check" in postgres.integrity_checks
    assert "legacy_sql_connector_sandbox_profile_smoke_report_hash_check" in postgres.integrity_checks
    assert "legacy_sql_connector_sandbox_enablement_gate_smoke_report_hash_check" in postgres.integrity_checks
    assert "legacy_sql_connector_provider_attestation_adapter_smoke_report_hash_check" in postgres.integrity_checks
    assert "legacy_sql_connector_connection_preflight_gate_smoke_report_hash_check" in postgres.integrity_checks
    assert "legacy_sql_connector_real_connection_executor_smoke_report_hash_check" in postgres.integrity_checks
    assert "legacy_sql_connector_real_connection_executor_policy_store_smoke_report_hash_check" in (
        postgres.integrity_checks
    )
    assert "legacy_sql_connector_execution_readiness_review_gate_smoke_report_hash_check" in (postgres.integrity_checks)
    assert "legacy_sql_connector_materialization_plan_gate_smoke_report_hash_check" in postgres.integrity_checks
    assert "legacy_sql_connector_socket_secret_implementation_adr_gate_smoke_report_hash_check" in (
        postgres.integrity_checks
    )
    assert "legacy_sql_connector_runtime_pr_gate_smoke_report_hash_check" in postgres.integrity_checks
    assert "legacy_sql_connector_runtime_merge_gate_smoke_report_hash_check" in postgres.integrity_checks
    assert "legacy_sql_connector_runtime_activation_gate_smoke_report_hash_check" in postgres.integrity_checks
    assert "legacy_sql_connector_live_connection_gate_smoke_report_hash_check" in postgres.integrity_checks
    assert "legacy_sql_connector_metadata_connection_probe_gate_smoke_report_hash_check" in postgres.integrity_checks
    assert (
        "legacy_sql_connector_metadata_connection_probe_skeleton_smoke_report_hash_check" in postgres.integrity_checks
    )
    assert (
        "legacy_sql_connector_metadata_connection_probe_live_adapter_smoke_report_hash_check"
        in postgres.integrity_checks
    )
    assert "legacy_sql_discovery_intake_operations_report_hash_check" in postgres.integrity_checks
    assert "legacy_sql_readiness_smoke_report_hash_check" in postgres.integrity_checks
    assert "knowledge_base_runtime_reconciliation_run_report_hash_check" in postgres.integrity_checks
    assert "benchmark_report_hash_check" in postgres.integrity_checks
    assert "docker compose run --rm backup" in postgres.current_dev_commands
    assert "docker compose run --rm backup-verify" in postgres.current_dev_commands
    assert "docker compose run --rm preview-renderer-smoke" in postgres.current_dev_commands
    assert "docker compose run --rm preview-renderer-drill" in postgres.current_dev_commands
    assert "docker compose run --rm legacy-sql-discovery-intake" in postgres.current_dev_commands
    assert "docker compose run --rm legacy-sql-readiness-smoke" in postgres.current_dev_commands
    assert "docker compose run --rm legacy-sql-import-dry-run-worker" in postgres.current_dev_commands
    assert "docker compose run --rm legacy-sql-import-write-approval-gate-smoke" in postgres.current_dev_commands
    assert "docker compose run --rm legacy-sql-evidence-ledger-drill" in postgres.current_dev_commands
    assert "docker compose run --rm legacy-sql-host-profile-release-gate-smoke" in postgres.current_dev_commands
    assert "docker compose run --rm legacy-sql-host-profile-adapter-smoke" in postgres.current_dev_commands
    assert "docker compose run --rm legacy-sql-metadata-worker-queue-drill" in postgres.current_dev_commands
    assert "docker compose run --rm legacy-sql-metadata-worker-lease-consumer-smoke" in postgres.current_dev_commands
    assert "docker compose run --rm legacy-sql-connector-sandbox-profile-smoke" in postgres.current_dev_commands
    assert "docker compose run --rm legacy-sql-connector-sandbox-enablement-gate-smoke" in postgres.current_dev_commands
    assert "docker compose run --rm legacy-sql-connector-provider-attestation-adapter-smoke" in (
        postgres.current_dev_commands
    )
    assert "docker compose run --rm legacy-sql-connector-connection-preflight-gate-smoke" in (
        postgres.current_dev_commands
    )
    assert (
        "docker compose run --rm legacy-sql-connector-real-connection-executor-smoke" in postgres.current_dev_commands
    )
    assert (
        "docker compose run --rm legacy-sql-connector-real-connection-executor-policy-store-smoke"
        in postgres.current_dev_commands
    )
    assert (
        "docker compose run --rm legacy-sql-connector-execution-readiness-review-gate-smoke"
        in postgres.current_dev_commands
    )
    assert (
        "docker compose run --rm legacy-sql-connector-materialization-plan-gate-smoke" in postgres.current_dev_commands
    )
    assert (
        "docker compose run --rm legacy-sql-connector-socket-secret-implementation-adr-gate-smoke"
        in postgres.current_dev_commands
    )
    assert "docker compose run --rm legacy-sql-connector-runtime-pr-gate-smoke" in postgres.current_dev_commands
    assert "docker compose run --rm legacy-sql-connector-runtime-merge-gate-smoke" in postgres.current_dev_commands
    assert "docker compose run --rm legacy-sql-connector-runtime-activation-gate-smoke" in postgres.current_dev_commands
    assert "docker compose run --rm legacy-sql-connector-live-connection-gate-smoke" in postgres.current_dev_commands
    assert (
        "docker compose run --rm legacy-sql-connector-metadata-connection-probe-gate-smoke"
        in postgres.current_dev_commands
    )
    assert (
        "docker compose run --rm legacy-sql-connector-metadata-connection-probe-skeleton-smoke"
        in postgres.current_dev_commands
    )
    assert (
        "docker compose run --rm legacy-sql-connector-metadata-connection-probe-live-adapter-smoke"
        in postgres.current_dev_commands
    )
    assert "docker compose run --rm kb-runtime-reconciler" in postgres.current_dev_commands

    crm_erp = policy.domain("crm_erp_business_records")
    assert "Legacy SQL evidence ledger entries" in crm_erp.state_artifacts
    assert "Legacy SQL evidence ledger restore evidence hashes" in crm_erp.state_artifacts
    assert "Legacy SQL evidence ledger operations report hashes" in crm_erp.state_artifacts
    assert "Legacy SQL discovery intake evidence" in crm_erp.state_artifacts
    assert "Legacy SQL discovery intake operation report hashes" in crm_erp.state_artifacts
    assert "Legacy SQL import readiness evidence" in crm_erp.state_artifacts
    assert "Legacy SQL staging metadata profiles" in crm_erp.state_artifacts
    assert "Legacy SQL staging metadata profile hashes" in crm_erp.state_artifacts
    assert "Legacy SQL import dry-run plans" in crm_erp.state_artifacts
    assert "Legacy SQL import dry-run plan hashes" in crm_erp.state_artifacts
    assert "Legacy SQL import dry-run results" in crm_erp.state_artifacts
    assert "Legacy SQL import dry-run result hashes" in crm_erp.state_artifacts
    assert "Legacy SQL import dry-run worker report hashes" in crm_erp.state_artifacts
    assert "Legacy SQL import write approval gate evidence" in crm_erp.state_artifacts
    assert "Legacy SQL import write approval gate hashes" in crm_erp.state_artifacts
    assert "Legacy SQL import write approval gate smoke report hashes" in crm_erp.state_artifacts
    assert "Legacy SQL import write approval records" in crm_erp.state_artifacts
    assert "Legacy SQL import write approval record hashes" in crm_erp.state_artifacts
    assert "Legacy SQL migration run registry entries" in crm_erp.state_artifacts
    assert "Legacy SQL migration run registry hashes" in crm_erp.state_artifacts
    assert "Legacy SQL migration metadata-only reports" in crm_erp.state_artifacts
    assert "Legacy SQL migration metadata-only report hashes" in crm_erp.state_artifacts
    assert "Legacy SQL readiness smoke report hashes" in crm_erp.state_artifacts
    assert "Legacy SQL host profile release gate evidence" in crm_erp.state_artifacts
    assert "Legacy SQL metadata worker queue schedule evidence hashes" in crm_erp.state_artifacts
    assert "Legacy SQL metadata worker queue restore evidence hashes" in crm_erp.state_artifacts
    assert "Legacy SQL connector sandbox profile hashes" in crm_erp.state_artifacts
    assert "Legacy SQL connector sandbox enablement gate hashes" in crm_erp.state_artifacts
    assert "Legacy SQL connector provider attestation adapter hashes" in crm_erp.state_artifacts
    assert "Legacy SQL connector connection preflight gate hashes" in crm_erp.state_artifacts
    assert "Legacy SQL connector real connection executor contract hashes" in crm_erp.state_artifacts
    assert "Legacy SQL connector real connection executor policy store hashes" in crm_erp.state_artifacts
    assert "Legacy SQL connector execution readiness review gate hashes" in crm_erp.state_artifacts
    assert "Legacy SQL connector materialization plan gate hashes" in crm_erp.state_artifacts
    assert "Legacy SQL connector socket-secret implementation ADR gate hashes" in crm_erp.state_artifacts
    assert "Legacy SQL connector runtime PR gate hashes" in crm_erp.state_artifacts
    assert "Legacy SQL connector runtime merge gate hashes" in crm_erp.state_artifacts
    assert "Legacy SQL connector runtime activation gate hashes" in crm_erp.state_artifacts
    assert "Legacy SQL connector live connection gate hashes" in crm_erp.state_artifacts
    assert "Legacy SQL connector metadata connection probe gate hashes" in crm_erp.state_artifacts
    assert "Legacy SQL connector metadata connection probe skeleton hashes" in crm_erp.state_artifacts
    assert "Legacy SQL connector metadata connection probe live adapter hashes" in crm_erp.state_artifacts

    object_storage = policy.target("object_storage_records")
    assert "retention_manifest_hash_check" in object_storage.integrity_checks
    assert "retention_policy_snapshot_hash_check" in object_storage.integrity_checks
    assert "legal_hold_decision_check" in object_storage.integrity_checks
    assert "legal_hold_reevaluation_check" in object_storage.integrity_checks
    assert "storage_object_manifest_hash_check" in object_storage.integrity_checks
    assert "envelope_encryption_manifest_hash_check" in object_storage.integrity_checks
    assert "restore_drill_report_hash_check" in object_storage.integrity_checks
    assert "knowledge_base_source_version_evidence_hash_check" in object_storage.integrity_checks
    assert "knowledge_base_restore_evidence_hash_check" in object_storage.integrity_checks
    assert "knowledge_base_runtime_reconciliation_restore_drill_binding_check" in object_storage.integrity_checks
    assert "ciphertext_hash_check" in object_storage.integrity_checks
    assert "aad_hash_check" in object_storage.integrity_checks
    assert "content_hash_verifier_check" in object_storage.integrity_checks
    assert "bucket_profile_policy_export" in object_storage.backup_methods
    assert "docker compose run --rm kb-runtime-reconciler" in object_storage.current_dev_commands

    kms = policy.target("kms_and_secrets")
    assert "kms_adapter_policy_check" in kms.integrity_checks
    assert "key_usage_evidence_hash_check" in kms.integrity_checks
    assert "envelope_rewrap_evidence_hash_check" in kms.integrity_checks
    assert "cryptoshred_manifest_hash_check" in kms.integrity_checks
    assert "restore_drill_report_hash_check" in kms.integrity_checks
    assert "wrapped_data_key_hash_check" in kms.integrity_checks
    assert "rewrapped_data_key_hash_check" in kms.integrity_checks
    assert "no_plaintext_key_export_check" in kms.integrity_checks

    search_derivatives = policy.target("search_and_vector_derivatives")
    assert "recall_baseline_check" in search_derivatives.integrity_checks
    assert "benchmark_report_hash_check" in search_derivatives.integrity_checks

    for target in policy.targets:
        assert target.covered_domains
        assert target.backup_methods
        assert target.integrity_checks
        assert target.failover_mode
        assert target.restore_drill_frequency_days <= 90


def test_backup_failover_policy_covers_future_suite_domains() -> None:
    policy = load_backup_failover_policy(POLICY_PATH)
    domain_ids = {domain.domain_id for domain in policy.continuity_domains}
    covered_domain_ids = {domain_id for target in policy.targets for domain_id in target.covered_domains}
    target_ids = {target.target_id for target in policy.targets}

    assert domain_ids >= REQUIRED_CONTINUITY_DOMAINS
    assert covered_domain_ids >= REQUIRED_CONTINUITY_DOMAINS

    for domain in policy.continuity_domains:
        assert domain.primary_target_id in target_ids
        assert domain.criticality in {"critical", "important", "rebuildable"}
        assert domain.recovery_strategy
        assert domain.state_artifacts

    assert policy.domain("kms_key_metadata").primary_target_id == "kms_and_secrets"
    assert "plaintext key material" in policy.domain("kms_key_metadata").recovery_strategy
    assert "KMS adapter policy" in policy.domain("kms_key_metadata").state_artifacts
    assert "vector worker audit events" in policy.domain("audit_evidence").state_artifacts
    assert "embedding model approval audit events" in policy.domain("audit_evidence").state_artifacts
    assert policy.domain("search_indexes").criticality == "rebuildable"
    assert "benchmark reports" in policy.domain("search_indexes").state_artifacts
    assert "ACL versions" in policy.domain("vector_indexes").state_artifacts
    assert "embedding model version approvals" in policy.domain("vector_indexes").state_artifacts
    assert "embedding model approval audit references" in policy.domain("vector_indexes").state_artifacts
    assert "embedding model dimensions" in policy.domain("vector_indexes").state_artifacts
    assert "vector metadata schema" in policy.domain("vector_indexes").state_artifacts
    assert "benchmark report hashes" in policy.domain("vector_indexes").state_artifacts
    assert "source object write receipts" in policy.domain("postgres_metadata").state_artifacts
    assert "source object preview decision evidence" in policy.domain("postgres_metadata").state_artifacts
    assert "source object storage manifests" in policy.domain("postgres_metadata").state_artifacts
    assert policy.domain("office_documents").criticality == "critical"
    assert policy.domain("mail_messages_threads").criticality == "critical"
    assert policy.domain("module_registry_state").criticality == "critical"
    assert "tenant module states" in policy.domain("module_registry_state").state_artifacts
    assert "module required migration versions" in policy.domain("module_registry_state").state_artifacts
    assert "tenant module migration evidence" in policy.domain("module_registry_state").state_artifacts
    assert "persistent module registry seed/backfill evidence" in policy.domain("module_registry_state").state_artifacts
    assert "module registry operations report hashes" in policy.domain("module_registry_state").state_artifacts
    assert "worker discovery drill results" in policy.domain("module_registry_state").state_artifacts
    assert policy.domain("crm_erp_business_records").criticality == "critical"
    assert "invoices" in policy.domain("crm_erp_business_records").state_artifacts
    assert "SQL Server migration manifests" in policy.domain("crm_erp_business_records").state_artifacts
    assert "knowledge article metadata" in policy.domain("knowledge_base_content").state_artifacts
    assert "knowledge article versions" in policy.domain("knowledge_base_content").state_artifacts
    assert "Knowledge Base source-version evidence hashes" in policy.domain("knowledge_base_content").state_artifacts
    assert "Knowledge Base restore evidence hash" in policy.domain("knowledge_base_content").state_artifacts
    assert "Knowledge Base write-approval evidence hashes" in policy.domain("knowledge_base_content").state_artifacts
    assert (
        "Knowledge Base trusted write-approval article metadata"
        in policy.domain("knowledge_base_content").state_artifacts
    )
    assert "Knowledge Base write-approval transition lineage" in policy.domain("knowledge_base_content").state_artifacts
    assert (
        "Knowledge Base source-object write receipt hashes" in policy.domain("knowledge_base_content").state_artifacts
    )
    assert "Knowledge Base runtime activation evidence" in policy.domain("knowledge_base_content").state_artifacts
    assert "Knowledge Base runtime reconciliation evidence" in policy.domain("knowledge_base_content").state_artifacts
    assert (
        "Knowledge Base runtime reconciliation run reports" in policy.domain("knowledge_base_content").state_artifacts
    )
    assert (
        "Knowledge Base runtime reconciliation retry and alert contract"
        in policy.domain("background_jobs_queues").state_artifacts
    )
    assert "preview renderer worker queue bindings" in policy.domain("background_jobs_queues").state_artifacts
    assert "preview renderer idempotency key hashes" in policy.domain("background_jobs_queues").state_artifacts
    assert "Legacy SQL metadata worker queue jobs" in policy.domain("background_jobs_queues").state_artifacts
    assert (
        "Legacy SQL metadata worker queue idempotency hashes" in policy.domain("background_jobs_queues").state_artifacts
    )
    assert (
        "Legacy SQL metadata worker queue lease and retry evidence"
        in policy.domain("background_jobs_queues").state_artifacts
    )
    assert (
        "Legacy SQL metadata worker lease consumer activation evidence"
        in policy.domain("background_jobs_queues").state_artifacts
    )
    assert (
        "Legacy SQL connector sandbox default-off profile evidence"
        in policy.domain("background_jobs_queues").state_artifacts
    )
    assert (
        "Legacy SQL connector sandbox enablement gate evidence"
        in policy.domain("background_jobs_queues").state_artifacts
    )
    assert (
        "Legacy SQL connector provider attestation adapter evidence"
        in policy.domain("background_jobs_queues").state_artifacts
    )
    assert (
        "Legacy SQL connector connection preflight gate evidence"
        in policy.domain("background_jobs_queues").state_artifacts
    )
    assert (
        "Legacy SQL connector real connection executor contract evidence"
        in policy.domain("background_jobs_queues").state_artifacts
    )
    assert (
        "Legacy SQL connector real connection executor policy store bundles"
        in policy.domain("background_jobs_queues").state_artifacts
    )
    assert (
        "Legacy SQL connector execution readiness review gate evidence"
        in policy.domain("background_jobs_queues").state_artifacts
    )
    assert (
        "Legacy SQL connector materialization plan gate evidence"
        in policy.domain("background_jobs_queues").state_artifacts
    )
    assert (
        "Legacy SQL connector metadata connection probe gate evidence"
        in policy.domain("background_jobs_queues").state_artifacts
    )
    assert (
        "Legacy SQL connector metadata connection probe skeleton evidence"
        in policy.domain("background_jobs_queues").state_artifacts
    )
    assert (
        "Legacy SQL connector metadata connection probe live adapter evidence"
        in policy.domain("background_jobs_queues").state_artifacts
    )
    assert "course completions" in policy.domain("learning_management_records").state_artifacts
    assert "workflow transitions" in policy.domain("task_activity_records").state_artifacts
    assert "ticket SLA state" in policy.domain("service_ticket_records").state_artifacts
    assert "time entries" in policy.domain("time_tracking_records").state_artifacts


def test_backup_failover_policy_requires_change_control_for_new_state() -> None:
    policy = load_backup_failover_policy(POLICY_PATH)
    rules = " ".join(policy.change_control_rules)

    assert "new persistent table" in rules
    assert "object bucket" in rules
    assert "search index" in rules
    assert "mail store" in rules
    assert "office store" in rules
    assert "continuity domain" in rules
    assert "Knowledge Base runtime reconciliation run report hash when applicable" in policy.restore_drill_evidence
    assert "module registry operations report hash when applicable" in policy.restore_drill_evidence
    assert "Legacy SQL evidence ledger hash when applicable" in policy.restore_drill_evidence
    assert "Legacy SQL evidence ledger operations report hash when applicable" in policy.restore_drill_evidence
    assert "Legacy SQL discovery intake operations report hash when applicable" in policy.restore_drill_evidence
    assert "Legacy SQL import dry-run plan hash when applicable" in policy.restore_drill_evidence
    assert "Legacy SQL import dry-run result hash when applicable" in policy.restore_drill_evidence
    assert "Legacy SQL import dry-run worker report hash when applicable" in policy.restore_drill_evidence
    assert "Legacy SQL import write approval gate hash when applicable" in policy.restore_drill_evidence
    assert "Legacy SQL import write approval gate smoke report hash when applicable" in policy.restore_drill_evidence
    assert "Legacy SQL import write approval record hash when applicable" in policy.restore_drill_evidence
    assert "Legacy SQL migration run registry hash when applicable" in policy.restore_drill_evidence
    assert "Legacy SQL migration metadata-only report hash when applicable" in policy.restore_drill_evidence
    assert "Legacy SQL host profile release gate evidence hash when applicable" in policy.restore_drill_evidence
    assert "Legacy SQL metadata worker queue operations report hash when applicable" in policy.restore_drill_evidence
    assert (
        "Legacy SQL metadata worker lease consumer smoke report hash when applicable" in policy.restore_drill_evidence
    )
    assert "Legacy SQL connector sandbox profile smoke report hash when applicable" in policy.restore_drill_evidence
    assert (
        "Legacy SQL connector sandbox enablement gate smoke report hash when applicable"
        in policy.restore_drill_evidence
    )
    assert (
        "Legacy SQL connector provider attestation adapter smoke report hash when applicable"
        in policy.restore_drill_evidence
    )
    assert (
        "Legacy SQL connector connection preflight gate smoke report hash when applicable"
        in policy.restore_drill_evidence
    )
    assert (
        "Legacy SQL connector real connection executor smoke report hash when applicable"
        in policy.restore_drill_evidence
    )
    assert (
        "Legacy SQL connector real connection executor policy store smoke report hash when applicable"
        in policy.restore_drill_evidence
    )
    assert (
        "Legacy SQL connector metadata connection probe gate smoke report hash when applicable"
        in policy.restore_drill_evidence
    )
    assert (
        "Legacy SQL connector metadata connection probe skeleton smoke report hash when applicable"
        in policy.restore_drill_evidence
    )
    assert (
        "Legacy SQL connector metadata connection probe live adapter smoke report hash when applicable"
        in policy.restore_drill_evidence
    )
    assert "module lifecycle audit event metadata for module_registry_state" in policy.restore_drill_evidence
    assert "Knowledge Base runtime reconciliation drift or worker failure is reported" in policy.incident_triggers
    assert "module registry seed, backfill, repair, or worker discovery drill fails" in policy.incident_triggers


def test_backup_failover_runbook_names_restore_culture_and_commands() -> None:
    runbook = RUNBOOK_PATH.read_text(encoding="utf-8")

    assert "a backup does not count until it has a checksum" in runbook
    assert "every new durable component must update this continuity model" in runbook
    assert "docker compose run --rm backup" in runbook
    assert "docker compose run --rm backup-verify" in runbook
    assert "docker compose run --rm module-registry-drill" in runbook
    assert "docker compose run --rm legacy-sql-discovery-intake" in runbook
    assert "docker compose run --rm legacy-sql-readiness-smoke" in runbook
    assert "docker compose run --rm legacy-sql-import-dry-run-worker" in runbook
    assert "docker compose run --rm legacy-sql-evidence-ledger-drill" in runbook
    assert "docker compose run --rm legacy-sql-host-profile-release-gate-smoke" in runbook
    assert "docker compose run --rm legacy-sql-host-profile-adapter-smoke" in runbook
    assert "docker compose run --rm legacy-sql-metadata-worker-queue-drill" in runbook
    assert "docker compose run --rm legacy-sql-metadata-worker-lease-consumer-smoke" in runbook
    assert "docker compose run --rm legacy-sql-connector-sandbox-profile-smoke" in runbook
    assert "docker compose run --rm legacy-sql-connector-sandbox-enablement-gate-smoke" in runbook
    assert "docker compose run --rm legacy-sql-connector-provider-attestation-adapter-smoke" in runbook
    assert "docker compose run --rm legacy-sql-connector-connection-preflight-gate-smoke" in runbook
    assert "docker compose run --rm legacy-sql-connector-real-connection-executor-smoke" in runbook
    assert "docker compose run --rm legacy-sql-connector-real-connection-executor-policy-store-smoke" in runbook
    assert "docker compose run --rm legacy-sql-connector-execution-readiness-review-gate-smoke" in runbook
    assert "docker compose run --rm legacy-sql-connector-materialization-plan-gate-smoke" in runbook
    assert "docker compose run --rm legacy-sql-connector-metadata-connection-probe-gate-smoke" in runbook
    assert "docker compose run --rm legacy-sql-connector-metadata-connection-probe-skeleton-smoke" in runbook
    assert "docker compose run --rm legacy-sql-connector-metadata-connection-probe-live-adapter-smoke" in runbook
    assert "module_registry_operations_report.v1" in runbook
    assert "legacy_sql_discovery_intake_operations_report.v1" in runbook
    assert "legacy_sql_evidence_ledger_entry.v1" in runbook
    assert "legacy_sql_evidence_ledger_operations_report.v1" in runbook
    assert "legacy_sql_host_profile_release_gate.v1" in runbook
    assert "legacy_sql_host_profile_release_gate_smoke_report.v1" in runbook
    assert "legacy_sql_host_profile_adapter_schedule.v1" in runbook
    assert "legacy_sql_host_profile_adapter_smoke_report.v1" in runbook
    assert "legacy_sql_metadata_worker_queue_job.v1" in runbook
    assert "legacy_sql_metadata_worker_queue_operations_report.v1" in runbook
    assert "legacy_sql_metadata_worker_lease_consumer_activation.v1" in runbook
    assert "legacy_sql_metadata_worker_lease_consumer_smoke_report.v1" in runbook
    assert "legacy_sql_connector_sandbox_profile.v1" in runbook
    assert "legacy_sql_connector_sandbox_profile_smoke_report.v1" in runbook
    assert "legacy_sql_connector_sandbox_provider_attestation.v1" in runbook
    assert "legacy_sql_connector_sandbox_enablement_gate.v1" in runbook
    assert "legacy_sql_connector_sandbox_enablement_gate_smoke_report.v1" in runbook
    assert "legacy_sql_connector_provider_network_profile.v1" in runbook
    assert "legacy_sql_connector_provider_secret_resolver_profile.v1" in runbook
    assert "legacy_sql_connector_provider_audit_profile.v1" in runbook
    assert "legacy_sql_connector_provider_attestation_adapter.v1" in runbook
    assert "legacy_sql_connector_provider_attestation_adapter_smoke_report.v1" in runbook
    assert "legacy_sql_connector_operator_context.v1" in runbook
    assert "legacy_sql_connector_connection_attempt_preflight_gate.v1" in runbook
    assert "legacy_sql_connector_connection_attempt_preflight_gate_smoke_report.v1" in runbook
    assert "legacy_sql_connector_real_connection_timeout_retry_policy.v1" in runbook
    assert "legacy_sql_connector_real_connection_audit_plan.v1" in runbook
    assert "legacy_sql_connector_real_connection_kill_switch_policy.v1" in runbook
    assert "legacy_sql_connector_real_connection_executor_contract.v1" in runbook
    assert "legacy_sql_connector_real_connection_executor_smoke_report.v1" in runbook
    assert "legacy_sql_connector_real_connection_executor_policy_bundle.v1" in runbook
    assert "legacy_sql_connector_real_connection_executor_policy_store_smoke_report.v1" in runbook
    assert "legacy_sql_connector_execution_readiness_human_review.v1" in runbook
    assert "legacy_sql_connector_execution_readiness_change_control.v1" in runbook
    assert "legacy_sql_connector_execution_readiness_restore_drill.v1" in runbook
    assert "legacy_sql_connector_execution_readiness_review_gate.v1" in runbook
    assert "legacy_sql_connector_execution_readiness_review_gate_smoke_report.v1" in runbook
    assert "legacy_sql_connector_materialization_provider_profile_snapshot.v1" in runbook
    assert "legacy_sql_connector_materialization_operator_mfa_snapshot.v1" in runbook
    assert "legacy_sql_connector_materialization_kill_switch_snapshot.v1" in runbook
    assert "legacy_sql_connector_materialization_plan_gate.v1" in runbook
    assert "legacy_sql_connector_materialization_plan_gate_smoke_report.v1" in runbook
    assert "legacy_sql_connector_socket_secret_provider_limits_snapshot.v1" in runbook
    assert "legacy_sql_connector_socket_secret_network_route_snapshot.v1" in runbook
    assert "legacy_sql_connector_socket_secret_secret_manager_snapshot.v1" in runbook
    assert "legacy_sql_connector_socket_secret_rollback_runbook_snapshot.v1" in runbook
    assert "legacy_sql_connector_socket_secret_kill_switch_runbook_snapshot.v1" in runbook
    assert "legacy_sql_connector_socket_secret_implementation_adr_gate.v1" in runbook
    assert "legacy_sql_connector_socket_secret_implementation_adr_gate_smoke_report.v1" in runbook
    assert "legacy_sql_connector_runtime_pr_code_review_snapshot.v1" in runbook
    assert "legacy_sql_connector_runtime_pr_test_container_snapshot.v1" in runbook
    assert "legacy_sql_connector_runtime_pr_secret_binding_snapshot.v1" in runbook
    assert "legacy_sql_connector_runtime_pr_network_binding_snapshot.v1" in runbook
    assert "legacy_sql_connector_runtime_pr_rollback_probe_snapshot.v1" in runbook
    assert "legacy_sql_connector_runtime_pr_kill_switch_probe_snapshot.v1" in runbook
    assert "legacy_sql_connector_runtime_pr_gate.v1" in runbook
    assert "legacy_sql_connector_runtime_pr_gate_smoke_report.v1" in runbook
    assert "legacy_sql_connector_runtime_merge_branch_protection_snapshot.v1" in runbook
    assert "legacy_sql_connector_runtime_merge_security_scan_snapshot.v1" in runbook
    assert "legacy_sql_connector_runtime_merge_container_provenance_snapshot.v1" in runbook
    assert "legacy_sql_connector_runtime_merge_secret_rotation_plan_snapshot.v1" in runbook
    assert "legacy_sql_connector_runtime_merge_kill_switch_drill_snapshot.v1" in runbook
    assert "legacy_sql_connector_runtime_merge_gate.v1" in runbook
    assert "legacy_sql_connector_runtime_merge_gate_smoke_report.v1" in runbook
    assert "legacy_sql_connector_runtime_activation_tenant_approval_snapshot.v1" in runbook
    assert "legacy_sql_connector_runtime_activation_feature_flag_snapshot.v1" in runbook
    assert "legacy_sql_connector_runtime_activation_secret_rotation_confirmation_snapshot.v1" in runbook
    assert "legacy_sql_connector_runtime_activation_network_authorization_snapshot.v1" in runbook
    assert "legacy_sql_connector_runtime_activation_rollback_freeze_snapshot.v1" in runbook
    assert "legacy_sql_connector_runtime_activation_kill_switch_arming_snapshot.v1" in runbook
    assert "legacy_sql_connector_runtime_activation_gate.v1" in runbook
    assert "legacy_sql_connector_runtime_activation_gate_smoke_report.v1" in runbook
    assert "legacy_sql_connector_live_connection_secret_broker_binding_snapshot.v1" in runbook
    assert "legacy_sql_connector_live_connection_network_egress_policy_snapshot.v1" in runbook
    assert "legacy_sql_connector_live_connection_least_privilege_db_role_snapshot.v1" in runbook
    assert "legacy_sql_connector_live_connection_timeout_circuit_breaker_snapshot.v1" in runbook
    assert "legacy_sql_connector_live_connection_audit_sink_snapshot.v1" in runbook
    assert "legacy_sql_connector_live_connection_emergency_disable_snapshot.v1" in runbook
    assert "legacy_sql_connector_live_connection_gate.v1" in runbook
    assert "legacy_sql_connector_live_connection_gate_smoke_report.v1" in runbook
    assert "legacy_sql_connector_metadata_connection_probe_provider_driver_snapshot.v1" in runbook
    assert "legacy_sql_connector_metadata_connection_probe_secret_broker_read_path_snapshot.v1" in runbook
    assert "legacy_sql_connector_metadata_connection_probe_query_allowlist_snapshot.v1" in runbook
    assert "legacy_sql_connector_metadata_connection_probe_timeout_circuit_breaker_execution_snapshot.v1" in runbook
    assert "legacy_sql_connector_metadata_connection_probe_audit_sink_execution_snapshot.v1" in runbook
    assert "legacy_sql_connector_metadata_connection_probe_emergency_disable_execution_snapshot.v1" in runbook
    assert "legacy_sql_connector_metadata_connection_probe_gate.v1" in runbook
    assert "legacy_sql_connector_metadata_connection_probe_gate_smoke_report.v1" in runbook
    assert "legacy_sql_connector_metadata_connection_probe_skeleton_command.v1" in runbook
    assert "legacy_sql_connector_metadata_connection_probe_execution_plan.v1" in runbook
    assert "legacy_sql_connector_metadata_connection_probe_execution_evidence.v1" in runbook
    assert "legacy_sql_connector_metadata_connection_probe_skeleton_smoke_report.v1" in runbook
    assert "legacy_sql_connector_metadata_connection_probe_live_adapter_command.v1" in runbook
    assert "legacy_sql_connector_metadata_connection_probe_live_adapter_evidence.v1" in runbook
    assert "legacy_sql_connector_metadata_connection_probe_live_adapter_smoke_report.v1" in runbook
    assert "legacy_sql_readiness_smoke_report.v1" in runbook
    assert "crm_erp_legacy_staging_metadata_profile.v1" in runbook
    assert "crm_erp_legacy_import_dry_run_plan.v1" in runbook
    assert "legacy_sql_import_dry_run_result.v1" in runbook
    assert "legacy_sql_import_write_approval_gate.v1" in runbook
    assert "legacy_sql_import_write_approval_record.v1" in runbook
    assert "legacy_sql_migration_run_registry_entry.v1" in runbook
    assert "legacy_sql_migration_report_metadata.v1" in runbook
    assert "docker compose run --rm kb-runtime-reconciler" in runbook
    assert "knowledge_base_runtime_reconciliation_run_report.v1" in runbook
    assert "Continuity Domains" in runbook
    assert "Pull-Forward Rule" in runbook
    assert "RPO" in runbook
    assert "RTO" in runbook
    assert "Failover" in runbook
    assert "Monthly" in runbook
    assert "restore drill report hash" in runbook
    assert "ACL versions" in runbook
    assert "embedding model version approvals" in runbook
    assert "Embedding model approval" in runbook
    assert "benchmark report hash" in runbook
    assert "Vector worker audit events" in runbook
    assert "module registry state" in runbook
    assert "CRM/ERP business records" in runbook
    assert "knowledge-base article versions" in runbook
    assert "Knowledge Base runtime reconciliation run report hash" in runbook
    assert "Legacy SQL evidence ledger hash" in runbook
    assert "Legacy SQL evidence ledger operations report hash" in runbook
    assert "Legacy SQL discovery intake operations report hash" in runbook
    assert "Legacy SQL readiness smoke report hash" in runbook
    assert "Legacy SQL staging metadata profile hash" in runbook
    assert "Legacy SQL import dry-run plan hash" in runbook
    assert "Legacy SQL import dry-run result hash" in runbook
    assert "Legacy SQL import dry-run worker report hash" in runbook
    assert "Legacy SQL import write approval gate hash" in runbook
    assert "Legacy SQL import write approval gate smoke report hash" in runbook
    assert "Legacy SQL import write approval record hash" in runbook
    assert "Legacy SQL migration run registry hash" in runbook
    assert "Legacy SQL migration metadata-only report hash" in runbook
    assert "Legacy SQL host profile release gate evidence hash" in runbook
    assert "Legacy SQL metadata worker queue operations report hash" in runbook
    assert "Legacy SQL metadata worker lease consumer smoke report hash" in runbook
    assert "Legacy SQL connector sandbox profile smoke report hash" in runbook
    assert "Legacy SQL connector sandbox enablement gate smoke report hash" in runbook
    assert "Legacy SQL connector provider attestation adapter smoke report hash" in runbook
    assert "Legacy SQL connector connection preflight gate smoke report hash" in runbook
    assert "Legacy SQL connector real connection executor smoke report hash" in runbook
    assert "Legacy SQL connector real connection executor policy store smoke report hash" in runbook
    assert "Legacy SQL connector execution readiness review gate smoke report hash" in runbook
    assert "Legacy SQL connector materialization plan gate smoke report hash" in runbook
    assert "Legacy SQL connector socket-secret implementation ADR gate smoke report hash" in runbook
    assert "Legacy SQL connector runtime PR gate smoke report hash" in runbook
    assert "Legacy SQL connector runtime merge gate smoke report hash" in runbook
    assert "Legacy SQL connector runtime activation gate smoke report hash" in runbook
    assert "Legacy SQL connector live connection gate smoke report hash" in runbook
    assert "Legacy SQL connector metadata connection probe gate smoke report hash" in runbook
    assert "Legacy SQL connector metadata connection probe skeleton smoke report hash" in runbook
    assert "Legacy SQL connector metadata connection probe live adapter smoke report hash" in runbook
    assert "source-object storage manifests" in runbook
    assert "source-object write receipt hashes" in runbook
    assert "time entries" in runbook


def test_module_registry_operations_runbook_names_seed_backfill_repair_and_smoke() -> None:
    runbook = MODULE_REGISTRY_RUNBOOK_PATH.read_text(encoding="utf-8")

    assert "Platform Module Registry Operations" in runbook
    assert "module_registry_state" in runbook
    assert "docker compose run --rm module-registry-drill" in runbook
    assert "module_registry_operations_report.v1" in runbook
    assert "Seed" in runbook
    assert "Backfill" in runbook
    assert "Repair" in runbook
    assert "API Smoke" in runbook
    assert "ModuleWorkerGate" in runbook
    assert "continuity_domain=module_registry_state" in runbook
    assert "no hard deletes of tenant module rows" in runbook


def test_compose_exposes_backup_and_verification_commands() -> None:
    compose = COMPOSE_PATH.read_text(encoding="utf-8")

    assert "\n  backup:\n" in compose
    assert "\n  backup-verify:\n" in compose
    assert "\n  kb-runtime-reconciler:\n" in compose
    assert "\n  module-registry-drill:\n" in compose
    assert "\n  legacy-sql-discovery-intake:\n" in compose
    assert "\n  legacy-sql-readiness-smoke:\n" in compose
    assert "\n  legacy-sql-evidence-ledger-drill:\n" in compose
    assert "\n  legacy-sql-host-profile-release-gate-smoke:\n" in compose
    assert "\n  legacy-sql-host-profile-adapter-smoke:\n" in compose
    assert "\n  legacy-sql-metadata-worker-queue-drill:\n" in compose
    assert "\n  legacy-sql-metadata-worker-lease-consumer-smoke:\n" in compose
    assert "\n  legacy-sql-connector-sandbox-profile-smoke:\n" in compose
    assert "\n  legacy-sql-connector-sandbox-enablement-gate-smoke:\n" in compose
    assert "\n  legacy-sql-connector-provider-attestation-adapter-smoke:\n" in compose
    assert "\n  legacy-sql-connector-connection-preflight-gate-smoke:\n" in compose
    assert "\n  legacy-sql-connector-real-connection-executor-smoke:\n" in compose
    assert "\n  legacy-sql-connector-real-connection-executor-policy-store-smoke:\n" in compose
    assert "\n  legacy-sql-connector-execution-readiness-review-gate-smoke:\n" in compose
    assert "\n  legacy-sql-connector-materialization-plan-gate-smoke:\n" in compose
    assert "\n  legacy-sql-connector-socket-secret-implementation-adr-gate-smoke:\n" in compose
    assert "\n  legacy-sql-connector-runtime-pr-gate-smoke:\n" in compose
    assert "\n  legacy-sql-connector-runtime-merge-gate-smoke:\n" in compose
    assert "\n  legacy-sql-connector-runtime-activation-gate-smoke:\n" in compose
    assert "\n  legacy-sql-connector-live-connection-gate-smoke:\n" in compose
    assert "\n  legacy-sql-connector-metadata-connection-probe-gate-smoke:\n" in compose
    assert "\n  legacy-sql-connector-metadata-connection-probe-skeleton-smoke:\n" in compose
    assert "\n  legacy-sql-connector-metadata-connection-probe-live-adapter-smoke:\n" in compose
    assert "pg_dump" in compose
    assert "sha256sum" in compose
    assert "pg_restore --list" in compose
    assert "python -m suite.platform.module_registry_operations --once" in compose
    assert "python -m suite.platform.legacy_sql_discovery_intake_operations --once" in compose
    assert "python -m suite.platform.legacy_sql_readiness_smoke --once" in compose
    assert "python -m suite.platform.legacy_sql_evidence_ledger_operations --once" in compose
    assert "python -m suite.platform.legacy_sql_host_profile_release_gate_smoke --once" in compose
    assert "python -m suite.platform.legacy_sql_host_profile_adapter --once" in compose
    assert "python -m suite.platform.legacy_sql_metadata_worker_queue --once" in compose
    assert "python -m suite.platform.legacy_sql_metadata_worker_lease_consumer --once" in compose
    assert "python -m suite.platform.legacy_sql_connector_sandbox_profile --once" in compose
    assert "python -m suite.platform.legacy_sql_connector_sandbox_enablement_gate --once" in compose
    assert "python -m suite.platform.legacy_sql_connector_provider_attestation_adapter --once" in compose
    assert "python -m suite.platform.legacy_sql_connector_connection_preflight_gate --once" in compose
    assert "python -m suite.platform.legacy_sql_connector_real_connection_executor --once" in compose
    assert "python -m suite.platform.legacy_sql_connector_real_connection_executor --policy-store-once" in compose
    assert "python -m suite.platform.legacy_sql_connector_execution_readiness_review_gate --once" in compose
    assert "python -m suite.platform.legacy_sql_connector_materialization_plan_gate --once" in compose
    assert "python -m suite.platform.legacy_sql_connector_socket_secret_implementation_adr_gate --once" in compose
    assert "python -m suite.platform.legacy_sql_connector_runtime_pr_gate --once" in compose
    assert "python -m suite.platform.legacy_sql_connector_runtime_merge_gate --once" in compose
    assert "python -m suite.platform.legacy_sql_connector_runtime_activation_gate --once" in compose
    assert "python -m suite.platform.legacy_sql_connector_live_connection_gate --once" in compose
    assert "python -m suite.platform.legacy_sql_connector_metadata_connection_probe_gate --once" in compose
    assert "python -m suite.platform.legacy_sql_connector_metadata_connection_probe_skeleton --once" in compose
    assert "python -m suite.platform.legacy_sql_connector_metadata_connection_probe_live_adapter --once" in compose
    assert "python -m suite.platform.knowledge_base_runtime_reconciliation_service --once" in compose
    assert "SUITE_MODULE_REGISTRY_BACKEND: postgres" in compose
    assert "SUITE_MODULE_REGISTRY_DSN: postgresql://collabio_worker:collabio_worker@postgres:5432/collabio" in compose
    assert (
        "SUITE_MODULE_REGISTRY_WORKER_DSN: postgresql://collabio_worker:collabio_worker@postgres:5432/collabio"
        in compose
    )
    assert "SUITE_KB_RUNTIME_RECONCILIATION_STORE_BACKEND: postgres" in compose
    assert "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_DRILL_BACKENDS: jsonl,postgres" in compose
    assert "SUITE_LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_STORE_BACKEND: postgres" in compose
    assert "SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_BACKEND: postgres" in compose
    assert "SUITE_LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_POLICY_STORE_BACKEND: postgres" in compose
    assert (
        "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_DSN: "
        "postgresql://collabio_worker:collabio_worker@postgres:5432/collabio" in compose
    )
    assert "./backups:/backups" in compose
