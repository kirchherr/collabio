from pathlib import Path

from suite.operations.backup_failover import backup_policy_summary, load_backup_failover_policy

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = REPO_ROOT / "docs" / "operations" / "backup_failover_policy.json"
RUNBOOK_PATH = REPO_ROOT / "docs" / "operations" / "BACKUP_FAILOVER.md"
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
    assert "source_object_write_receipt_hash_check" in postgres.integrity_checks
    assert "benchmark_report_hash_check" in postgres.integrity_checks
    assert "docker compose run --rm backup" in postgres.current_dev_commands
    assert "docker compose run --rm backup-verify" in postgres.current_dev_commands

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
    assert "ciphertext_hash_check" in object_storage.integrity_checks
    assert "aad_hash_check" in object_storage.integrity_checks
    assert "content_hash_verifier_check" in object_storage.integrity_checks
    assert "bucket_profile_policy_export" in object_storage.backup_methods

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
    assert policy.domain("office_documents").criticality == "critical"
    assert policy.domain("mail_messages_threads").criticality == "critical"
    assert policy.domain("module_registry_state").criticality == "critical"
    assert "tenant module states" in policy.domain("module_registry_state").state_artifacts
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


def test_backup_failover_runbook_names_restore_culture_and_commands() -> None:
    runbook = RUNBOOK_PATH.read_text(encoding="utf-8")

    assert "a backup does not count until it has a checksum" in runbook
    assert "every new durable component must update this continuity model" in runbook
    assert "docker compose run --rm backup" in runbook
    assert "docker compose run --rm backup-verify" in runbook
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
    assert "source-object write receipt hashes" in runbook
    assert "time entries" in runbook


def test_compose_exposes_backup_and_verification_commands() -> None:
    compose = COMPOSE_PATH.read_text(encoding="utf-8")

    assert "\n  backup:\n" in compose
    assert "\n  backup-verify:\n" in compose
    assert "pg_dump" in compose
    assert "sha256sum" in compose
    assert "pg_restore --list" in compose
    assert "./backups:/backups" in compose
