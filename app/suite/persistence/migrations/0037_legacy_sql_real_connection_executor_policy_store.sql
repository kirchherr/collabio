-- 0037_legacy_sql_real_connection_executor_policy_store.sql
-- Tenant-scoped non-executing policy bundle store for Legacy SQL real-connection executor contracts.

CREATE TABLE IF NOT EXISTS collabio.legacy_sql_real_connection_executor_policy_store (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    module_id text NOT NULL DEFAULT 'crm_erp' CHECK (module_id ~ '^[a-z][a-z0-9_]*$'),
    source_system_ref text NOT NULL CHECK (source_system_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    connector_kind text NOT NULL CHECK (
        connector_kind IN ('sqlserver', 'postgres', 'mysql', 'oracle', 'sqlite', 'unknown')
    ),
    policy_bundle_ref text NOT NULL CHECK (policy_bundle_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    sandbox_profile_ref text NOT NULL CHECK (sandbox_profile_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    sandbox_profile_evidence_hash text NOT NULL CHECK (sandbox_profile_evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    preflight_evidence_hash text NOT NULL CHECK (preflight_evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    timeout_retry_policy_hash text NOT NULL CHECK (timeout_retry_policy_hash ~ '^sha256:[a-f0-9]{64}$'),
    audit_plan_hash text NOT NULL CHECK (audit_plan_hash ~ '^sha256:[a-f0-9]{64}$'),
    kill_switch_policy_hash text NOT NULL CHECK (kill_switch_policy_hash ~ '^sha256:[a-f0-9]{64}$'),
    executor_contract_evidence_hash text NOT NULL CHECK (
        executor_contract_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    executor_restore_evidence_hash text NOT NULL CHECK (executor_restore_evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    timeout_retry_policy jsonb NOT NULL CHECK (
        jsonb_typeof(timeout_retry_policy) = 'object'
        AND timeout_retry_policy ->> 'schema_version' = 'legacy_sql_connector_real_connection_timeout_retry_policy.v1'
        AND timeout_retry_policy ->> 'tenant_id' = tenant_id
        AND timeout_retry_policy ->> 'module_id' = module_id
        AND timeout_retry_policy ->> 'source_system_ref' = source_system_ref
        AND timeout_retry_policy ->> 'connector_kind' = connector_kind
        AND timeout_retry_policy ->> 'sandbox_profile_ref' = sandbox_profile_ref
        AND timeout_retry_policy ->> 'sandbox_profile_evidence_hash' = sandbox_profile_evidence_hash
        AND timeout_retry_policy ->> 'preflight_evidence_hash' = preflight_evidence_hash
        AND timeout_retry_policy ->> 'evidence_hash' = timeout_retry_policy_hash
    ),
    audit_plan jsonb NOT NULL CHECK (
        jsonb_typeof(audit_plan) = 'object'
        AND audit_plan ->> 'schema_version' = 'legacy_sql_connector_real_connection_audit_plan.v1'
        AND audit_plan ->> 'tenant_id' = tenant_id
        AND audit_plan ->> 'module_id' = module_id
        AND audit_plan ->> 'source_system_ref' = source_system_ref
        AND audit_plan ->> 'connector_kind' = connector_kind
        AND audit_plan ->> 'sandbox_profile_ref' = sandbox_profile_ref
        AND audit_plan ->> 'sandbox_profile_evidence_hash' = sandbox_profile_evidence_hash
        AND audit_plan ->> 'preflight_evidence_hash' = preflight_evidence_hash
        AND audit_plan ->> 'evidence_hash' = audit_plan_hash
        AND (audit_plan ->> 'metadata_only_events')::boolean = true
        AND (audit_plan ->> 'prompt_or_output_body_logging_allowed')::boolean = false
        AND (audit_plan ->> 'raw_payload_logging_allowed')::boolean = false
        AND (audit_plan ->> 'secret_material_logging_allowed')::boolean = false
    ),
    kill_switch_policy jsonb NOT NULL CHECK (
        jsonb_typeof(kill_switch_policy) = 'object'
        AND kill_switch_policy ->> 'schema_version' = 'legacy_sql_connector_real_connection_kill_switch_policy.v1'
        AND kill_switch_policy ->> 'tenant_id' = tenant_id
        AND kill_switch_policy ->> 'module_id' = module_id
        AND kill_switch_policy ->> 'source_system_ref' = source_system_ref
        AND kill_switch_policy ->> 'connector_kind' = connector_kind
        AND kill_switch_policy ->> 'sandbox_profile_ref' = sandbox_profile_ref
        AND kill_switch_policy ->> 'sandbox_profile_evidence_hash' = sandbox_profile_evidence_hash
        AND kill_switch_policy ->> 'preflight_evidence_hash' = preflight_evidence_hash
        AND kill_switch_policy ->> 'evidence_hash' = kill_switch_policy_hash
        AND (kill_switch_policy ->> 'kill_switch_armed')::boolean = true
        AND (kill_switch_policy ->> 'tenant_connection_disabled')::boolean = false
        AND (kill_switch_policy ->> 'global_connection_disabled')::boolean = false
        AND (kill_switch_policy ->> 'manual_abort_requested')::boolean = false
        AND (kill_switch_policy ->> 'break_glass_allowed')::boolean = false
    ),
    executor_contract jsonb NOT NULL CHECK (
        jsonb_typeof(executor_contract) = 'object'
        AND executor_contract ->> 'schema_version' = 'legacy_sql_connector_real_connection_executor_contract.v1'
        AND executor_contract ->> 'tenant_id' = tenant_id
        AND executor_contract ->> 'module_id' = module_id
        AND executor_contract ->> 'source_system_ref' = source_system_ref
        AND executor_contract ->> 'connector_kind' = connector_kind
        AND executor_contract ->> 'sandbox_profile_ref' = sandbox_profile_ref
        AND executor_contract ->> 'sandbox_profile_evidence_hash' = sandbox_profile_evidence_hash
        AND executor_contract ->> 'preflight_evidence_hash' = preflight_evidence_hash
        AND executor_contract ->> 'timeout_retry_policy_hash' = timeout_retry_policy_hash
        AND executor_contract ->> 'audit_plan_hash' = audit_plan_hash
        AND executor_contract ->> 'kill_switch_policy_hash' = kill_switch_policy_hash
        AND executor_contract ->> 'executor_restore_evidence_hash' = executor_restore_evidence_hash
        AND executor_contract ->> 'evidence_hash' = executor_contract_evidence_hash
        AND (executor_contract ->> 'executor_contract_ready')::boolean = true
        AND (executor_contract ->> 'socket_materialization_allowed')::boolean = false
        AND (executor_contract ->> 'network_socket_opened')::boolean = false
        AND (executor_contract ->> 'network_connection_opened')::boolean = false
        AND (executor_contract ->> 'real_connection_opened')::boolean = false
        AND (executor_contract ->> 'secret_material_resolved')::boolean = false
        AND (executor_contract ->> 'raw_data_access_allowed')::boolean = false
        AND (executor_contract ->> 'import_dry_run_allowed')::boolean = false
        AND (executor_contract ->> 'import_write_allowed')::boolean = false
        AND (executor_contract ->> 'destructive_actions_allowed')::boolean = false
    ),
    policy_bundle jsonb NOT NULL CHECK (
        jsonb_typeof(policy_bundle) = 'object'
        AND policy_bundle ->> 'schema_version' = 'legacy_sql_connector_real_connection_executor_policy_bundle.v1'
        AND policy_bundle ->> 'tenant_id' = tenant_id
        AND policy_bundle ->> 'module_id' = module_id
        AND policy_bundle ->> 'source_system_ref' = source_system_ref
        AND policy_bundle ->> 'connector_kind' = connector_kind
        AND policy_bundle ->> 'policy_bundle_ref' = policy_bundle_ref
        AND policy_bundle ->> 'sandbox_profile_ref' = sandbox_profile_ref
        AND policy_bundle ->> 'sandbox_profile_evidence_hash' = sandbox_profile_evidence_hash
        AND policy_bundle ->> 'preflight_evidence_hash' = preflight_evidence_hash
        AND policy_bundle ->> 'timeout_retry_policy_hash' = timeout_retry_policy_hash
        AND policy_bundle ->> 'audit_plan_hash' = audit_plan_hash
        AND policy_bundle ->> 'kill_switch_policy_hash' = kill_switch_policy_hash
        AND policy_bundle ->> 'executor_contract_evidence_hash' = executor_contract_evidence_hash
        AND policy_bundle ->> 'executor_restore_evidence_hash' = executor_restore_evidence_hash
        AND (policy_bundle ->> 'store_persistence_allowed')::boolean = true
        AND (policy_bundle ->> 'socket_materialization_allowed')::boolean = false
        AND (policy_bundle ->> 'network_socket_opened')::boolean = false
        AND (policy_bundle ->> 'network_connection_opened')::boolean = false
        AND (policy_bundle ->> 'real_connection_opened')::boolean = false
        AND (policy_bundle ->> 'secret_material_resolved')::boolean = false
        AND (policy_bundle ->> 'raw_data_access_allowed')::boolean = false
        AND (policy_bundle ->> 'import_dry_run_allowed')::boolean = false
        AND (policy_bundle ->> 'import_write_allowed')::boolean = false
        AND (policy_bundle ->> 'destructive_actions_allowed')::boolean = false
    ),
    store_persistence_allowed boolean NOT NULL DEFAULT true CHECK (store_persistence_allowed = true),
    socket_materialization_allowed boolean NOT NULL DEFAULT false CHECK (socket_materialization_allowed = false),
    network_socket_opened boolean NOT NULL DEFAULT false CHECK (network_socket_opened = false),
    network_connection_opened boolean NOT NULL DEFAULT false CHECK (network_connection_opened = false),
    real_connection_opened boolean NOT NULL DEFAULT false CHECK (real_connection_opened = false),
    secret_material_resolved boolean NOT NULL DEFAULT false CHECK (secret_material_resolved = false),
    raw_data_access_allowed boolean NOT NULL DEFAULT false CHECK (raw_data_access_allowed = false),
    import_dry_run_allowed boolean NOT NULL DEFAULT false CHECK (import_dry_run_allowed = false),
    import_write_allowed boolean NOT NULL DEFAULT false CHECK (import_write_allowed = false),
    destructive_actions_allowed boolean NOT NULL DEFAULT false CHECK (destructive_actions_allowed = false),
    checked_by text NOT NULL CHECK (checked_by <> ''),
    checked_at_utc timestamptz NOT NULL,
    evidence_hash text NOT NULL CHECK (evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    captured_at_utc timestamptz NOT NULL DEFAULT now(),
    schema_version text NOT NULL DEFAULT 'legacy_sql_connector_real_connection_executor_policy_bundle.v1' CHECK (
        schema_version = 'legacy_sql_connector_real_connection_executor_policy_bundle.v1'
    ),
    PRIMARY KEY (tenant_id, executor_contract_evidence_hash),
    UNIQUE (tenant_id, policy_bundle_ref),
    UNIQUE (tenant_id, evidence_hash),
    CHECK ((policy_bundle ->> 'evidence_hash') = evidence_hash),
    CHECK (position('connection_secret_ref' in policy_bundle::text) = 0),
    CHECK (position('sqlserver://' in lower(policy_bundle::text)) = 0),
    CHECK (position('"password"' in lower(policy_bundle::text)) = 0),
    CHECK (position('"raw_payload"' in lower(policy_bundle::text)) = 0),
    CHECK (position('"sample_values"' in lower(policy_bundle::text)) = 0),
    CHECK (position('"import_write_payload"' in lower(policy_bundle::text)) = 0)
);

COMMENT ON TABLE collabio.legacy_sql_real_connection_executor_policy_store IS
    'Tenant-scoped non-executing policy bundle store for Legacy SQL real-connection executor contracts.';

COMMENT ON COLUMN collabio.legacy_sql_real_connection_executor_policy_store.policy_bundle IS
    'legacy_sql_connector_real_connection_executor_policy_bundle.v1 JSON. Stores timeout/retry, audit, kill-switch, restore, and executor-contract evidence only; socket and Secret materialization remain forbidden.';

CREATE INDEX IF NOT EXISTS legacy_sql_real_connection_executor_policy_store_preflight_idx
    ON collabio.legacy_sql_real_connection_executor_policy_store (
        tenant_id,
        preflight_evidence_hash,
        checked_at_utc
    );

CREATE INDEX IF NOT EXISTS legacy_sql_real_connection_executor_policy_store_source_idx
    ON collabio.legacy_sql_real_connection_executor_policy_store (
        tenant_id,
        source_system_ref,
        checked_at_utc
    );

ALTER TABLE collabio.legacy_sql_real_connection_executor_policy_store ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.legacy_sql_real_connection_executor_policy_store FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS legacy_sql_real_connection_executor_policy_store_tenant_select
    ON collabio.legacy_sql_real_connection_executor_policy_store;
CREATE POLICY legacy_sql_real_connection_executor_policy_store_tenant_select
    ON collabio.legacy_sql_real_connection_executor_policy_store
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS legacy_sql_real_connection_executor_policy_store_tenant_insert
    ON collabio.legacy_sql_real_connection_executor_policy_store;
CREATE POLICY legacy_sql_real_connection_executor_policy_store_tenant_insert
    ON collabio.legacy_sql_real_connection_executor_policy_store
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS legacy_sql_real_connection_executor_policy_store_no_update
    ON collabio.legacy_sql_real_connection_executor_policy_store;
CREATE POLICY legacy_sql_real_connection_executor_policy_store_no_update
    ON collabio.legacy_sql_real_connection_executor_policy_store
    FOR UPDATE
    USING (false);

DROP POLICY IF EXISTS legacy_sql_real_connection_executor_policy_store_no_delete
    ON collabio.legacy_sql_real_connection_executor_policy_store;
CREATE POLICY legacy_sql_real_connection_executor_policy_store_no_delete
    ON collabio.legacy_sql_real_connection_executor_policy_store
    FOR DELETE
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.legacy_sql_real_connection_executor_policy_store TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.legacy_sql_real_connection_executor_policy_store TO collabio_worker';
    END IF;
END
$$;
