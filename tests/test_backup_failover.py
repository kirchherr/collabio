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

    assert policy.schema_version == "backup_failover_policy.v4"
    assert policy.owner == "platform-operations"
    assert len(policy.targets) == 7
    assert backup_policy_summary(policy) == {
        "schema_version": "backup_failover_policy.v4",
        "owner": "platform-operations",
        "target_count": 7,
        "continuity_domain_count": len(REQUIRED_CONTINUITY_DOMAINS),
        "strictest_rpo_minutes": 15,
        "strictest_rto_hours": 4,
    }

    deployment_gate = policy.production_deployment_gate
    assert deployment_gate.schema_version == "production_continuity_deployment_policy.v2"
    assert deployment_gate.maximum_evidence_age_hours == 168
    assert deployment_gate.required_target_ids == (
        "postgres_primary",
        "object_storage_records",
        "kms_and_secrets",
    )
    assert deployment_gate.minimum_postgres_instances == 3
    assert deployment_gate.minimum_failure_domains == 3
    assert deployment_gate.maximum_wal_archive_backlog_bytes == 0
    assert deployment_gate.maximum_manual_promotion_minutes == 15
    assert deployment_gate.maximum_cross_site_failover_minutes == 240
    assert deployment_gate.automatic_failover_requires_separate_drill is True
    assert deployment_gate.deployment_execution_allowed is False
    assert deployment_gate.reference_implementation_ids("postgres_pitr") == {
        "postgresql_native",
        "pgbackrest",
        "cloudnativepg_barman_plugin",
    }
    assert deployment_gate.reference_implementation_ids("ha_orchestration") == {
        "patroni",
        "cloudnativepg",
        "managed_postgresql_provider",
    }
    assert {
        "promotion_fencing_and_split_brain_prevention",
        "cross_site_postgres_object_storage_and_kms_recovery",
        "metadata_only_no_deployment_or_failover_execution",
    }.issubset(deployment_gate.required_control_ids)

    postgres = policy.target("postgres_primary")
    assert postgres.rpo_minutes <= 15
    assert postgres.rto_hours <= 4
    assert postgres.restore_drill_frequency_days <= 30
    assert "sha256_manifest" in postgres.integrity_checks
    assert "pg_restore_catalog" in postgres.integrity_checks
    assert "business_backend_release_gate_hash_check" in postgres.integrity_checks
    assert "productivity_pilot_preflight_gate_hash_check" in postgres.integrity_checks
    assert "productivity_pilot_admission_record_hash_check" in postgres.integrity_checks
    assert "productivity_pilot_admission_rls_append_only_check" in postgres.integrity_checks
    assert "productivity_pilot_traffic_scope_hash_check" in postgres.integrity_checks
    assert "productivity_pilot_traffic_scope_rls_append_only_check" in postgres.integrity_checks
    assert "productivity_pilot_start_authorization_hash_check" in postgres.integrity_checks
    assert "productivity_pilot_start_authorization_rls_append_only_check" in postgres.integrity_checks
    assert "productivity_pilot_runtime_window_hash_check" in postgres.integrity_checks
    assert "productivity_pilot_runtime_window_rls_append_only_check" in postgres.integrity_checks
    assert "productivity_pilot_runtime_observation_hash_check" in postgres.integrity_checks
    assert "productivity_pilot_runtime_observation_rls_append_only_check" in postgres.integrity_checks
    assert "productivity_pilot_closure_report_hash_check" in postgres.integrity_checks
    assert "productivity_pilot_closure_report_rls_append_only_check" in postgres.integrity_checks
    assert "productivity_pilot_real_user_closure_report_hash_check" in postgres.integrity_checks
    assert "productivity_pilot_real_user_closure_report_rls_append_only_check" in postgres.integrity_checks
    assert postgres.restore_verification_gates == [
        "postgres_restore_drill_report.v1",
        "isolated_postgres_restore",
        "exact_schema_relation_row_count_match",
        "migration_catalog_match",
        "rls_policy_role_grant_match",
        "backend_foundation_completion_gate.v1",
        "business_backend_release_gate.v1",
        "productivity_pilot_preflight_gate.v1",
        "productivity_pilot_admission_record.v1",
        "productivity_pilot_real_user_nomination.v1",
        "productivity_pilot_real_user_admission.v1",
        "productivity_pilot_traffic_scope_enforcement.v1",
        "productivity_pilot_start_authorization.v1",
        "productivity_pilot_runtime_window.v1",
        "productivity_pilot_runtime_observation.v1",
        "productivity_pilot_real_user_runtime_window.v1",
        "productivity_pilot_real_user_runtime_observation.v1",
        "productivity_pilot_closure_report.v1",
        "preview_conversion_execution_gate_hash_check",
        "preview_conversion_job_evidence_hash_check",
        "preview_cdr_manifest_hash_check",
        "derived_preview_lineage_receipt_hash_check",
        "derived_preview_source_object_recovery_check",
        "derived_preview_recovery_drill_report_hash_check",
        "productivity_pilot_real_user_closure_report.v1",
    ]
    assert "vector_metadata_schema_check" in postgres.integrity_checks
    assert "embedding_model_version_approval_check" in postgres.integrity_checks
    assert "acl_version_checkpoint_check" in postgres.integrity_checks
    assert "source_object_storage_manifest_hash_check" in postgres.integrity_checks
    assert "persistent_source_object_runtime_report_hash_check" in postgres.integrity_checks
    assert "persistent_source_object_restart_read_check" in postgres.integrity_checks
    assert "runtime_test_database_isolation_check" in postgres.integrity_checks
    assert "source_object_write_receipt_hash_check" in postgres.integrity_checks
    assert "source_object_preview_decision_evidence_hash_check" in postgres.integrity_checks
    assert "source_object_preview_renderer_evidence_hash_check" in postgres.integrity_checks
    assert "preview_renderer_api_smoke_report_hash_check" in postgres.integrity_checks
    assert "preview_renderer_recovery_drill_report_hash_check" in postgres.integrity_checks
    assert "preview_renderer_release_gate_evidence_hash_check" in postgres.integrity_checks
    assert "preview_conversion_job_evidence_hash_check" in postgres.integrity_checks
    assert "preview_cdr_manifest_hash_check" in postgres.integrity_checks
    assert "derived_preview_recovery_drill_report_hash_check" in postgres.integrity_checks
    assert "preview_conversion_execution_gate_hash_check" in postgres.restore_verification_gates
    assert "preview_conversion_job_evidence_hash_check" in postgres.restore_verification_gates
    assert "preview_cdr_manifest_hash_check" in postgres.restore_verification_gates
    assert "derived_preview_lineage_receipt_hash_check" in postgres.restore_verification_gates
    assert "derived_preview_source_object_recovery_check" in postgres.restore_verification_gates
    assert "derived_preview_recovery_drill_report_hash_check" in postgres.restore_verification_gates
    postgres_metadata = policy.domain("postgres_metadata")
    assert "source object preview conversion execution gate evidence" in postgres_metadata.state_artifacts
    assert "source object preview conversion job evidence" in postgres_metadata.state_artifacts
    assert "preview CDR profile and manifest hashes" in postgres_metadata.state_artifacts
    assert "source object derived preview lineage receipts" in postgres_metadata.state_artifacts
    assert "source object derived preview recovery drill reports" in postgres_metadata.state_artifacts
    object_storage_domain = policy.domain("object_storage_records")
    assert "derived preview PDF source objects" in object_storage_domain.state_artifacts
    assert "derived preview source-to-output lineage" in object_storage_domain.state_artifacts
    parser_artifacts = policy.domain("parser_worker_artifacts").state_artifacts
    assert "preview malware scan evidence hashes" in parser_artifacts
    assert "preview malware scanner smoke report hashes" in parser_artifacts
    assert "preview CDR profile and manifest hashes" in parser_artifacts
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
    assert (
        "docker compose --profile restore-drill run --rm derived-preview-recovery-drill"
        in postgres.current_dev_commands
    )
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
    assert "persistent_source_object_runtime_report_hash_check" in object_storage.integrity_checks
    assert "source_object_content_recovery_evidence_hash_check" in object_storage.integrity_checks
    assert "source_object_restart_read_check" in object_storage.integrity_checks
    assert "exact_version_restore_drill_report_hash_check" in object_storage.integrity_checks
    assert "backend_storage_foundation_gate_hash_check" in object_storage.integrity_checks
    assert "independent_restore_target_check" in object_storage.integrity_checks
    assert "restore_target_object_lock_control_check" in object_storage.integrity_checks
    assert "restore_target_legal_hold_control_check" in object_storage.integrity_checks
    assert "envelope_encryption_manifest_hash_check" in object_storage.integrity_checks
    assert "restore_drill_report_hash_check" in object_storage.integrity_checks
    assert "knowledge_base_source_version_evidence_hash_check" in object_storage.integrity_checks
    assert "knowledge_base_restore_evidence_hash_check" in object_storage.integrity_checks
    assert "knowledge_base_runtime_reconciliation_restore_drill_binding_check" in object_storage.integrity_checks
    assert "genoffice_internal_oss_signing_request_validity_check" in object_storage.integrity_checks
    assert "genoffice_internal_oss_signing_assignment_check" in object_storage.integrity_checks
    assert "genoffice_internal_oss_external_signature_response_binding_check" in object_storage.integrity_checks
    assert "genoffice_internal_oss_write_once_mode_check" in object_storage.integrity_checks
    assert "genoffice_source_archive_sha256_check" in object_storage.integrity_checks
    assert "genoffice_source_archive_regular_file_check" in object_storage.integrity_checks
    assert "genoffice_solo_founder_detached_signature_check" in object_storage.restore_verification_gates
    assert "genoffice_solo_founder_maximum_30_day_validity_check" in object_storage.restore_verification_gates
    assert "genoffice_solo_founder_two_person_false_check" in object_storage.restore_verification_gates
    assert "genoffice_solo_founder_runtime_boundaries_closed_check" in object_storage.restore_verification_gates
    assert "genoffice_development_authorization_mode_exclusivity_check" in object_storage.restore_verification_gates
    assert "genoffice_worker_dual_build_reproducibility_check" in object_storage.restore_verification_gates
    assert "genoffice_worker_archive_config_binding_check" in object_storage.restore_verification_gates
    assert "genoffice_worker_cyclonedx_schema_and_image_binding_check" in object_storage.restore_verification_gates
    assert "genoffice_worker_trivy_database_freshness_check" in object_storage.restore_verification_gates
    assert "genoffice_worker_detached_signature_check" in object_storage.restore_verification_gates
    assert "genoffice_worker_runtime_boundaries_closed_check" in object_storage.restore_verification_gates
    assert "genoffice_worker_private_signing_key_absence_check" in object_storage.restore_verification_gates
    assert "genoffice_quick_edit_preflight_policy_and_schema_hash_check" in object_storage.restore_verification_gates
    assert (
        "genoffice_quick_edit_19_fixture_byte_manifest_and_expected_decision_check"
        in object_storage.restore_verification_gates
    )
    assert "genoffice_quick_edit_source_blind_candidate_only_revalidation_check" in (
        object_storage.restore_verification_gates
    )
    assert "genoffice_quick_edit_signed_original_retention_and_derived_invalidation_check" in (
        object_storage.restore_verification_gates
    )
    assert "genoffice_quick_edit_harness_hard_closed_check" in object_storage.restore_verification_gates
    assert "genoffice_fidelity_policy_plan_and_baseline_hash_check" in object_storage.integrity_checks
    assert "genoffice_fidelity_result_engine_assignment_and_signer_binding_check" in object_storage.integrity_checks
    assert "genoffice_fidelity_referenced_evidence_hash_check" in object_storage.integrity_checks
    assert "genoffice_fidelity_execution_receipt_artifact_inventory_hash_check" in object_storage.integrity_checks
    assert "genoffice_fidelity_output_preflight_and_structural_recomputation_check" in object_storage.integrity_checks
    assert "genoffice_fidelity_openxml_font_cdr_and_visual_cross_binding_check" in object_storage.integrity_checks
    assert "genoffice_fidelity_evidence_verification_report_hash_check" in object_storage.integrity_checks
    assert "genoffice_libreoffice_runner_request_report_schema_hash_check" in object_storage.integrity_checks
    assert "genoffice_libreoffice_runner_image_digest_and_openxml_lock_check" in object_storage.integrity_checks
    assert "genoffice_libreoffice_execution_receipt_and_result_payload_hash_check" in object_storage.integrity_checks
    assert "genoffice_libreoffice_baseline_metadata_report_hash_check" in object_storage.integrity_checks
    assert "genoffice_word_host_readiness_and_runner_script_hash_check" in object_storage.integrity_checks
    assert "genoffice_word_assignment_handoff_and_interactive_receipt_hash_check" in object_storage.integrity_checks
    assert "genoffice_word_collector_image_execution_receipt_and_result_payload_hash_check" in (
        object_storage.integrity_checks
    )
    assert "genoffice_word_profile_credentials_dpapi_private_key_and_transient_workspace_absence_check" in (
        object_storage.integrity_checks
    )
    assert "genoffice_fidelity_exact_three_engine_by_three_fixture_plan_check" in (
        object_storage.restore_verification_gates
    )
    assert "genoffice_fidelity_structural_baseline_metadata_only_and_no_engine_check" in (
        object_storage.restore_verification_gates
    )
    assert "genoffice_fidelity_distinct_engine_signer_and_detached_signature_check" in (
        object_storage.restore_verification_gates
    )
    assert "genoffice_fidelity_complete_signed_matrix_intake_check" in object_storage.restore_verification_gates
    assert "genoffice_fidelity_referenced_evidence_content_calibration_and_human_review_gate_check" in (
        object_storage.restore_verification_gates
    )
    assert "genoffice_fidelity_private_key_credentials_profiles_scratch_and_transient_rgb_absence_check" in (
        object_storage.restore_verification_gates
    )
    assert "genoffice_fidelity_evidence_exact_tree_regular_file_and_no_symlink_check" in (
        object_storage.restore_verification_gates
    )
    assert "genoffice_fidelity_evidence_duplicate_json_key_and_strict_schema_check" in (
        object_storage.restore_verification_gates
    )
    assert "genoffice_fidelity_evidence_receipt_inventory_rebuild_check" in (object_storage.restore_verification_gates)
    assert "genoffice_fidelity_evidence_docx_preflight_and_structure_reproduction_check" in (
        object_storage.restore_verification_gates
    )
    assert "genoffice_fidelity_evidence_reference_candidate_cdr_page_hash_and_visual_reproduction_check" in (
        object_storage.restore_verification_gates
    )
    assert "genoffice_fidelity_evidence_success_still_blocks_threshold_review_claim_and_spike_check" in (
        object_storage.restore_verification_gates
    )
    assert "genoffice_libreoffice_assignment_exact_tree_digest_expiry_and_synthetic_only_check" in (
        object_storage.restore_verification_gates
    )
    assert "genoffice_libreoffice_runsc_kvm_no_network_read_only_root_and_empty_capability_check" in (
        object_storage.restore_verification_gates
    )
    assert "genoffice_libreoffice_unsigned_result_still_blocks_verification_calibration_review_and_claim_check" in (
        object_storage.restore_verification_gates
    )
    assert "genoffice_libreoffice_profiles_temporary_pdfs_credentials_private_keys_and_transient_rgb_absence_check" in (
        object_storage.restore_verification_gates
    )
    assert "genoffice_word_dedicated_interactive_account_identity_firewall_and_signing_custody_check" in (
        object_storage.restore_verification_gates
    )
    assert "genoffice_word_assignment_request_lifetime_source_script_and_host_binding_check" in (
        object_storage.restore_verification_gates
    )
    assert "genoffice_word_exact_handoff_source_blind_collector_and_runsc_kvm_check" in (
        object_storage.restore_verification_gates
    )
    assert "genoffice_word_unsigned_result_still_blocks_verification_calibration_review_and_claim_check" in (
        object_storage.restore_verification_gates
    )
    assert "ciphertext_hash_check" in object_storage.integrity_checks
    assert "aad_hash_check" in object_storage.integrity_checks
    assert "content_hash_verifier_check" in object_storage.integrity_checks
    assert "bucket_profile_policy_export" in object_storage.backup_methods
    assert "docker compose run --rm kb-runtime-reconciler" in object_storage.current_dev_commands
    assert "docker compose run --rm source-object-runtime-bootstrap" in object_storage.current_dev_commands
    assert "docker compose run --rm backend-storage-foundation-gate" in object_storage.current_dev_commands
    assert (
        "docker compose --profile office-worker-build run --rm genoffice-worker-image-admission-verifier"
        in object_storage.current_dev_commands
    )
    assert (
        "docker compose --profile office-worker-runtime-proof run --rm genoffice-quick-edit-preflight-control"
        in object_storage.current_dev_commands
    )
    assert (
        "docker compose --profile office-worker-runtime-proof run --rm genoffice-docx-fidelity-study-control"
        in object_storage.current_dev_commands
    )
    assert (
        "docker compose --profile office-worker-runtime-proof run --rm genoffice-docx-fidelity-libreoffice-schema"
        in object_storage.current_dev_commands
    )
    assert (
        "docker compose --profile office-worker-runtime-proof run --rm genoffice-docx-fidelity-libreoffice-prepare"
        in object_storage.current_dev_commands
    )
    assert (
        "docker compose --profile office-worker-runtime-proof run --rm --pull never "
        "genoffice-docx-fidelity-libreoffice-runner" in object_storage.current_dev_commands
    )
    assert (
        "docker compose --profile office-worker-runtime-proof run --rm genoffice-docx-fidelity-word-schema"
        in object_storage.current_dev_commands
    )
    assert (
        "docker compose --profile office-worker-runtime-proof run --rm genoffice-docx-fidelity-word-prepare"
        in object_storage.current_dev_commands
    )
    assert (
        "docker compose --profile office-worker-runtime-proof run --rm --pull never "
        "genoffice-docx-fidelity-word-collector" in object_storage.current_dev_commands
    )
    assert (
        "docker compose --profile office-worker-runtime-proof run --rm genoffice-docx-fidelity-evidence-schema"
        in object_storage.current_dev_commands
    )
    assert (
        "docker compose --profile office-worker-runtime-proof run --rm genoffice-docx-fidelity-evidence-verifier"
        in object_storage.current_dev_commands
    )
    for service in ("schema", "policy", "request", "assemble"):
        assert (
            "docker compose --profile office-worker-runtime-proof run --rm "
            f"genoffice-docx-fidelity-ceremony-{service}" in object_storage.current_dev_commands
        )
    assert (
        "DOCX quick-edit preflight policy and schemas, 19-fixture synthetic corpus, metadata-only evaluation reports, "
        "source-blind revalidation evidence, and hard-closed harness admission"
        in policy.domain("office_documents").state_artifacts
    )
    assert (
        "DOCX fidelity execution receipts, output DOCX candidates, Open XML and font reports, reference/candidate CDR "
        "manifests, visual comparison manifests, source-blind evidence verification reports, and retained review "
        "evidence without private keys, credentials, profiles, tokens, scratch, or expired transient RGB"
        in policy.domain("office_documents").state_artifacts
    )
    assert (
        "LibreOffice synthetic runner schemas, digest-bound run requests, exact package and NuGet lock inputs, "
        "unsigned result payloads, canonical signature messages, runner reports, execution receipts, output DOCX "
        "candidates, metadata-only OpenXML findings, CDR manifests and visual measurements without private keys, "
        "tenant content, profiles, temporary PDFs, credentials or transient RGB buffers"
        in policy.domain("office_documents").state_artifacts
    )
    assert any(
        artifact.startswith("Microsoft Word interactive reference-runner schemas")
        for artifact in policy.domain("office_documents").state_artifacts
    )
    assert (
        "DOCX fidelity signing-ceremony schemas, public engine signer policies and keys, bounded signing requests, "
        "canonical result messages, detached public signature responses, signed result envelopes and independent "
        "evidence-verification reports without private keys, DPAPI ciphertext, HSM sessions, KMS credentials or "
        "provider tokens" in policy.domain("office_documents").state_artifacts
    )
    assert (
        "DOCX fidelity study policy and schemas, exact 3x3 plan, metadata-only structural baselines, "
        "readiness reports, "
        "public signer policies, signed result envelopes, referenced evidence hashes, calibrated-threshold records, "
        "and human-review records without private keys or transient RGB"
        in policy.domain("office_documents").state_artifacts
    )

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

    runbook = RUNBOOK_PATH.read_text(encoding="utf-8")
    assert "Derived preview conversion recovery" in runbook
    assert "docker compose run --rm preview-conversion-engine-smoke" in runbook
    assert "docker compose --profile restore-drill run --rm derived-preview-recovery-drill" in runbook
    assert "derived-preview lineage receipt" in runbook
    assert "source_object_derived_preview_recovery_drill_report.v1" in runbook
    assert "Raw RGB CDR pages" in runbook
    assert "preview-conversion-proof-cdr-renderer" in runbook
    assert "Microsoft Word Fidelity Evidence Recovery" in runbook
    assert "GENOFFICE_DOCX_WORD_RUNNER.md" in runbook


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
    assert "workflow transitions" in policy.domain("task_activity_records").state_artifacts
    assert "ticket SLA state" in policy.domain("service_ticket_records").state_artifacts
    assert (
        "Tickets & Incidents storage migration evidence hash" in policy.domain("service_ticket_records").state_artifacts
    )
    assert "Tickets & Incidents restore drill evidence hash" in policy.domain("service_ticket_records").state_artifacts
    assert (
        "Tickets & Incidents tenant-admin activation approval gate hash"
        in policy.domain("service_ticket_records").state_artifacts
    )
    assert (
        "Tickets & Incidents tenant-admin activation approval record hash"
        in policy.domain("service_ticket_records").state_artifacts
    )
    assert "tickets.tenant_admin_activation_approval_records" in policy.domain("service_ticket_records").state_artifacts
    assert (
        "Tickets & Incidents tenant approval record migration 0074"
        in policy.domain("service_ticket_records").state_artifacts
    )
    assert (
        "Tickets & Incidents activation execution boundary hash"
        in policy.domain("service_ticket_records").state_artifacts
    )
    assert (
        "Tickets & Incidents activation dry-run execution skeleton hash"
        in policy.domain("service_ticket_records").state_artifacts
    )
    assert (
        "Tickets & Incidents activation dry-run executor implementation review hash"
        in policy.domain("service_ticket_records").state_artifacts
    )
    assert (
        "Tickets & Incidents activation dry-run result contract hash"
        in policy.domain("service_ticket_records").state_artifacts
    )
    assert (
        "Tickets & Incidents activation dry-run execution gate hash"
        in policy.domain("service_ticket_records").state_artifacts
    )
    assert (
        "Tickets & Incidents activation dry-run execution request boundary hash"
        in policy.domain("service_ticket_records").state_artifacts
    )
    assert (
        "Tickets & Incidents activation dry-run executor runtime boundary hash"
        in policy.domain("service_ticket_records").state_artifacts
    )
    assert (
        "Tickets & Incidents activation dry-run execution preflight hash"
        in policy.domain("service_ticket_records").state_artifacts
    )
    assert (
        "Tickets & Incidents activation dry-run execution receipt boundary hash"
        in policy.domain("service_ticket_records").state_artifacts
    )
    assert (
        "Tickets & Incidents activation dry-run result persistence boundary hash"
        in policy.domain("service_ticket_records").state_artifacts
    )
    assert (
        "Tickets & Incidents activation dry-run execution activation boundary hash"
        in policy.domain("service_ticket_records").state_artifacts
    )
    assert (
        "Tickets & Incidents activation dry-run execution start boundary hash"
        in policy.domain("service_ticket_records").state_artifacts
    )
    assert (
        "Tickets & Incidents activation dry-run execution dispatch boundary hash"
        in policy.domain("service_ticket_records").state_artifacts
    )
    assert (
        "Tickets & Incidents activation dry-run execution worker boundary hash"
        in policy.domain("service_ticket_records").state_artifacts
    )
    assert (
        "Tickets & Incidents activation dry-run execution final readiness gate hash"
        in policy.domain("service_ticket_records").state_artifacts
    )
    assert (
        "Tickets & Incidents activation dry-run execution approval boundary hash"
        in policy.domain("service_ticket_records").state_artifacts
    )
    assert (
        "Tickets & Incidents metadata schema migration 0052" in policy.domain("service_ticket_records").state_artifacts
    )
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
    assert (
        "Persistent SourceObject runtime report hash and restart-read/reconciliation evidence when applicable"
        in policy.restore_drill_evidence
    )
    assert "exact-version restore drill report hash when object storage is covered" in policy.restore_drill_evidence
    assert "backend storage foundation gate hash when object storage is covered" in policy.restore_drill_evidence
    assert "PostgreSQL restore drill report hash when PostgreSQL is covered" in policy.restore_drill_evidence
    assert "backend foundation completion gate hash for release evidence" in policy.restore_drill_evidence
    assert "business backend release gate hash for productive slice release evidence" in policy.restore_drill_evidence
    assert "productivity pilot preflight gate hash and selected tenant module state manifest hash" in (
        policy.restore_drill_evidence
    )
    assert "LMS restore drill evidence hash when applicable" in policy.restore_drill_evidence
    assert "Tickets & Incidents storage migration evidence hash when applicable" in policy.restore_drill_evidence
    assert "Tickets & Incidents restore drill evidence hash when applicable" in policy.restore_drill_evidence
    assert (
        "Tickets & Incidents tenant-admin activation approval gate hash when applicable"
        in policy.restore_drill_evidence
    )
    assert (
        "Tickets & Incidents tenant-admin activation approval record hash when applicable"
        in policy.restore_drill_evidence
    )
    assert "Tickets & Incidents activation execution boundary hash when applicable" in policy.restore_drill_evidence
    assert "Tickets & Incidents activation executor skeleton hash when applicable" in policy.restore_drill_evidence
    assert "Tickets & Incidents activation dry-run plan hash when applicable" in policy.restore_drill_evidence
    assert (
        "Tickets & Incidents activation dry-run execution boundary hash when applicable"
        in policy.restore_drill_evidence
    )
    assert (
        "Tickets & Incidents activation dry-run execution skeleton hash when applicable"
        in policy.restore_drill_evidence
    )
    assert (
        "Tickets & Incidents activation dry-run executor implementation review hash when applicable"
        in policy.restore_drill_evidence
    )
    assert (
        "Tickets & Incidents activation dry-run result contract hash when applicable" in policy.restore_drill_evidence
    )
    assert "Tickets & Incidents activation dry-run execution gate hash when applicable" in policy.restore_drill_evidence
    assert (
        "Tickets & Incidents activation dry-run execution request boundary hash when applicable"
        in policy.restore_drill_evidence
    )
    assert (
        "Tickets & Incidents activation dry-run executor runtime boundary hash when applicable"
        in policy.restore_drill_evidence
    )
    assert (
        "Tickets & Incidents activation dry-run execution preflight hash when applicable"
        in policy.restore_drill_evidence
    )
    assert (
        "Tickets & Incidents activation dry-run execution receipt boundary hash when applicable"
        in policy.restore_drill_evidence
    )
    assert (
        "Tickets & Incidents activation dry-run result persistence boundary hash when applicable"
        in policy.restore_drill_evidence
    )
    assert (
        "Tickets & Incidents activation dry-run execution activation boundary hash when applicable"
        in policy.restore_drill_evidence
    )
    assert (
        "Tickets & Incidents activation dry-run execution start boundary hash when applicable"
        in policy.restore_drill_evidence
    )
    assert (
        "Tickets & Incidents activation dry-run execution dispatch boundary hash when applicable"
        in policy.restore_drill_evidence
    )
    assert (
        "Tickets & Incidents activation dry-run execution worker boundary hash when applicable"
        in policy.restore_drill_evidence
    )
    assert (
        "Tickets & Incidents activation dry-run execution final readiness gate hash when applicable"
        in policy.restore_drill_evidence
    )
    assert (
        "Tickets & Incidents activation dry-run execution approval boundary hash when applicable"
        in policy.restore_drill_evidence
    )
    assert (
        "Tickets & Incidents metadata schema migration 0052 restore checks when applicable"
        in policy.restore_drill_evidence
    )
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
    assert "docker compose run --rm postgres-restore-drill" in runbook
    assert "docker compose run --rm backend-foundation-completion-gate" in runbook
    assert "docker compose --profile restore-drill run --rm business-backend-release-gate" in runbook
    assert "docker compose --profile restore-drill run --rm productivity-pilot-preflight-gate" in runbook
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
    assert "docker compose run --rm backend-storage-foundation-gate" in runbook
    assert "exact_version_restore_drill_report.v1" in runbook
    assert "backend_storage_foundation_gate.v1" in runbook
    assert "postgres_restore_drill_report.v1" in runbook
    assert "backend_foundation_completion_gate.v1" in runbook
    assert "business_backend_release_gate.v1" in runbook
    assert "productivity_pilot_preflight_gate.v1" in runbook
    assert "productivity_pilot_traffic_scope_enforcement.v1" in runbook
    assert "productivity_pilot_start_authorization.v1" in runbook
    assert "productivity_pilot_runtime_window.v1" in runbook
    assert "productivity_pilot_runtime_observation" in runbook
    assert "production_continuity_deployment_gate.v2" in runbook
    assert "PRODUCTION_CONTINUITY_SIGNING_CEREMONY.md" in runbook
    assert "docker compose --profile production-continuity run --rm" in runbook
    assert "runtime switch fails closed" in runbook
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
    assert "Tickets & Incidents activation dry-run execution gate hash" in runbook
    assert "Tickets & Incidents activation dry-run execution request boundary hash" in runbook
    assert "Tickets & Incidents activation dry-run executor runtime boundary hash" in runbook
    assert "Tickets & Incidents activation dry-run execution preflight hash" in runbook
    assert "Tickets & Incidents activation dry-run execution receipt boundary hash" in runbook
    assert "Tickets & Incidents activation dry-run result persistence boundary hash" in runbook
    assert "Tickets & Incidents activation dry-run execution activation boundary hash" in runbook
    assert "Tickets & Incidents activation dry-run execution start boundary hash" in runbook
    assert "Tickets & Incidents activation dry-run execution dispatch boundary hash" in runbook
    assert "Tickets & Incidents activation dry-run execution worker boundary hash" in runbook
    assert "Tickets & Incidents activation dry-run execution final readiness gate hash" in runbook
    assert "Tickets & Incidents activation dry-run execution approval boundary hash" in runbook
    assert "activation-dry-run-execution-gate" in runbook
    assert "activation-dry-run-execution-request-boundary" in runbook
    assert "activation-dry-run-executor-runtime-boundary" in runbook
    assert "activation-dry-run-execution-preflight" in runbook
    assert "activation-dry-run-execution-receipt-boundary" in runbook
    assert "activation-dry-run-result-persistence-boundary" in runbook
    assert "activation-dry-run-execution-activation-boundary" in runbook
    assert "activation-dry-run-execution-start-boundary" in runbook
    assert "activation-dry-run-execution-dispatch-boundary" in runbook
    assert "activation-dry-run-execution-worker-boundary" in runbook
    assert "activation-dry-run-execution-final-readiness-gate" in runbook
    assert "activation-dry-run-execution-approval-boundary" in runbook
    assert "activation dry-run execution preflight" in runbook
    assert "activation dry-run executor runtime boundary" in runbook
    assert "activation dry-run result persistence boundary" in runbook
    assert "activation dry-run execution activation boundary" in runbook
    assert "activation dry-run execution start boundary" in runbook
    assert "activation dry-run execution dispatch boundary" in runbook
    assert "activation dry-run execution worker boundary" in runbook
    assert "activation dry-run execution final readiness gate" in runbook
    assert "activation dry-run execution approval boundary" in runbook
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
    assert "\n  production-continuity-deployment-gate:\n" in compose
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
    assert "python -m suite.operations.production_continuity_deployment_gate" in compose
    ceremony_service = compose.split("\n  production-continuity-attestation-ceremony:\n", 1)[1].split(
        "\n  production-continuity-deployment-gate:\n", 1
    )[0]
    assert "suite.operations.production_continuity_attestation_ceremony" in ceremony_service
    assert 'command: ["--help"]' in ceremony_service
    assert 'network_mode: "none"' in ceremony_service
    assert "read_only: true" in ceremony_service
    assert "cap_drop:\n      - ALL" in ceremony_service
    assert "no-new-privileges:true" in ceremony_service
    assert "./app:/workspace/app:ro" in ceremony_service
    assert "./docs:/workspace/docs:ro" in ceremony_service
    assert "private_key" not in ceremony_service.lower()
    assert "SUITE_PRODUCTION_CONTINUITY_EVIDENCE_PATH: /evidence/production-continuity.json" in compose
    assert "SUITE_PRODUCTION_CONTINUITY_ATTESTATION_PATH: /evidence/production-continuity.dsse.json" in compose
    assert "SUITE_PRODUCTION_CONTINUITY_SIGNER_POLICY_PATH: /trust/production-continuity-signers.json" in compose
    assert (
        "SUITE_PRODUCTION_CONTINUITY_GATE_REPORT_PATH: /backups/production-continuity-deployment-gate.json" in compose
    )
    assert "./backups:/workspace/backups:ro" in compose
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


def test_compose_restarts_only_long_lived_services_after_host_reboot() -> None:
    compose = COMPOSE_PATH.read_text(encoding="utf-8")

    def service_block(service_name: str) -> str:
        lines = compose.splitlines()
        start = lines.index(f"  {service_name}:") + 1
        block: list[str] = []
        for line in lines[start:]:
            if line and not line.startswith("    "):
                break
            block.append(line)
        return "\n".join(block)

    for service_name in ("postgres", "minio", "api"):
        assert "\n    restart: unless-stopped\n" in service_block(service_name)

    assert compose.count("\n    restart: unless-stopped\n") == 3
    for service_name in (
        "migrate",
        "backup",
        "production-continuity-deployment-gate",
    ):
        assert "\n    restart:" not in service_block(service_name)
