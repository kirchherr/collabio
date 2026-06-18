-- 0035_legacy_sql_host_profile_release_gate_evidence.sql
-- Append-only metadata-only release gate evidence for Legacy SQL host profile activation.

CREATE TABLE IF NOT EXISTS collabio.legacy_sql_host_profile_release_gate_evidence (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    module_id text NOT NULL DEFAULT 'crm_erp' CHECK (module_id ~ '^[a-z][a-z0-9_]*$'),
    source_system_ref text NOT NULL CHECK (source_system_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    host_profile_ref text NOT NULL CHECK (host_profile_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    connector_kind text NOT NULL CHECK (connector_kind = 'sqlserver'),
    connector_policy_ref text NOT NULL CHECK (connector_policy_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    policy_snapshot_hash text NOT NULL CHECK (policy_snapshot_hash ~ '^sha256:[a-f0-9]{64}$'),
    approved_egress_ref text NOT NULL CHECK (approved_egress_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    connection_secret_ref_hash text NOT NULL CHECK (connection_secret_ref_hash ~ '^sha256:[a-f0-9]{64}$'),
    connection_fingerprint_hash text NOT NULL CHECK (connection_fingerprint_hash ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    ledger_operations_report_hash text NOT NULL CHECK (ledger_operations_report_hash ~ '^sha256:[a-f0-9]{64}$'),
    ledger_operations_checked_at_utc timestamptz NOT NULL,
    evaluated_at_utc timestamptz NOT NULL,
    freshness_window_hours integer NOT NULL CHECK (freshness_window_hours > 0 AND freshness_window_hours <= 720),
    requested_by text NOT NULL CHECK (requested_by <> ''),
    human_confirmation_reference text NOT NULL CHECK (human_confirmation_reference ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    ledger_operations_report_hash_valid boolean NOT NULL,
    ledger_operations_report_fresh boolean NOT NULL,
    ledger_operations_gate_passed boolean NOT NULL,
    postgres_ledger_backend_ready boolean NOT NULL,
    connector_policy_hash_valid boolean NOT NULL,
    host_profile_policy_bound boolean NOT NULL,
    host_profile_egress_bound boolean NOT NULL,
    host_profile_secret_bound boolean NOT NULL,
    host_profile_fingerprint_bound boolean NOT NULL,
    host_profile_metadata_only boolean NOT NULL,
    human_confirmation_verified boolean NOT NULL,
    metadata_only_boundary_verified boolean NOT NULL,
    host_profile_activation_allowed boolean NOT NULL,
    metadata_worker_scheduling_allowed boolean NOT NULL,
    real_connection_used boolean NOT NULL DEFAULT false CHECK (real_connection_used = false),
    raw_data_access_allowed boolean NOT NULL DEFAULT false CHECK (raw_data_access_allowed = false),
    import_dry_run_allowed boolean NOT NULL DEFAULT false CHECK (import_dry_run_allowed = false),
    import_write_allowed boolean NOT NULL DEFAULT false CHECK (import_write_allowed = false),
    destructive_actions_allowed boolean NOT NULL DEFAULT false CHECK (destructive_actions_allowed = false),
    blocking_reasons jsonb NOT NULL CHECK (jsonb_typeof(blocking_reasons) = 'array'),
    gate_status text NOT NULL CHECK (gate_status IN ('ready', 'blocked')),
    gate_evidence jsonb NOT NULL CHECK (
        jsonb_typeof(gate_evidence) = 'object'
        AND gate_evidence ->> 'schema_version' = 'legacy_sql_host_profile_release_gate.v1'
        AND gate_evidence -> 'required_evidence_inputs' ? 'legacy_sql_evidence_ledger_operations_report_hash'
        AND gate_evidence -> 'required_evidence_inputs' ? 'legacy_sql_connector_policy_hash'
        AND gate_evidence -> 'required_evidence_inputs' ? 'legacy_sql_host_profile_ref'
        AND gate_evidence -> 'required_evidence_inputs' ? 'approved_egress_ref'
        AND gate_evidence -> 'required_evidence_inputs' ? 'connection_secret_ref_hash'
        AND gate_evidence -> 'required_evidence_inputs' ? 'explicit_human_confirmation_reference'
    ),
    evidence_hash text NOT NULL CHECK (evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    captured_at_utc timestamptz NOT NULL DEFAULT now(),
    schema_version text NOT NULL DEFAULT 'legacy_sql_host_profile_release_gate.v1' CHECK (
        schema_version = 'legacy_sql_host_profile_release_gate.v1'
    ),
    PRIMARY KEY (tenant_id, evidence_hash),
    CHECK ((gate_evidence ->> 'tenant_id') = tenant_id),
    CHECK ((gate_evidence ->> 'module_id') = module_id),
    CHECK ((gate_evidence ->> 'source_system_ref') = source_system_ref),
    CHECK ((gate_evidence ->> 'host_profile_ref') = host_profile_ref),
    CHECK ((gate_evidence ->> 'connector_kind') = connector_kind),
    CHECK ((gate_evidence ->> 'connector_policy_ref') = connector_policy_ref),
    CHECK ((gate_evidence ->> 'policy_snapshot_hash') = policy_snapshot_hash),
    CHECK ((gate_evidence ->> 'approved_egress_ref') = approved_egress_ref),
    CHECK ((gate_evidence ->> 'connection_secret_ref_hash') = connection_secret_ref_hash),
    CHECK ((gate_evidence ->> 'connection_fingerprint_hash') = connection_fingerprint_hash),
    CHECK ((gate_evidence ->> 'ledger_operations_report_hash') = ledger_operations_report_hash),
    CHECK ((gate_evidence ->> 'evidence_hash') = evidence_hash),
    CHECK ((gate_evidence ->> 'gate_status') = gate_status),
    CHECK ((gate_evidence ->> 'host_profile_activation_allowed')::boolean = host_profile_activation_allowed),
    CHECK ((gate_evidence ->> 'metadata_worker_scheduling_allowed')::boolean = metadata_worker_scheduling_allowed),
    CHECK ((gate_evidence ->> 'real_connection_used')::boolean = false),
    CHECK ((gate_evidence ->> 'raw_data_access_allowed')::boolean = false),
    CHECK ((gate_evidence ->> 'import_dry_run_allowed')::boolean = false),
    CHECK ((gate_evidence ->> 'import_write_allowed')::boolean = false),
    CHECK ((gate_evidence ->> 'destructive_actions_allowed')::boolean = false),
    CHECK (
        (
            gate_status = 'ready'
            AND host_profile_activation_allowed = true
            AND metadata_worker_scheduling_allowed = true
            AND ledger_operations_report_hash_valid = true
            AND ledger_operations_report_fresh = true
            AND ledger_operations_gate_passed = true
            AND postgres_ledger_backend_ready = true
            AND connector_policy_hash_valid = true
            AND host_profile_policy_bound = true
            AND host_profile_egress_bound = true
            AND host_profile_secret_bound = true
            AND host_profile_fingerprint_bound = true
            AND host_profile_metadata_only = true
            AND human_confirmation_verified = true
            AND metadata_only_boundary_verified = true
            AND jsonb_array_length(blocking_reasons) = 0
        )
        OR (
            gate_status = 'blocked'
            AND (
                host_profile_activation_allowed = false
                OR metadata_worker_scheduling_allowed = false
            )
        )
    )
);

COMMENT ON TABLE collabio.legacy_sql_host_profile_release_gate_evidence IS
    'Tenant-scoped append-only metadata-only release gate evidence for Legacy SQL host profile activation.';

COMMENT ON COLUMN collabio.legacy_sql_host_profile_release_gate_evidence.gate_evidence IS
    'legacy_sql_host_profile_release_gate.v1 JSON. DSNs, raw SQL rows, sample values, table data, Secret references, import payloads, prompts, outputs, embeddings, transcripts, and destructive action payloads are excluded.';

CREATE INDEX IF NOT EXISTS legacy_sql_host_profile_release_gate_status_idx
    ON collabio.legacy_sql_host_profile_release_gate_evidence (tenant_id, gate_status, evaluated_at_utc);

CREATE INDEX IF NOT EXISTS legacy_sql_host_profile_release_gate_profile_idx
    ON collabio.legacy_sql_host_profile_release_gate_evidence (
        tenant_id,
        host_profile_ref,
        ledger_operations_report_hash,
        evaluated_at_utc
    );

ALTER TABLE collabio.legacy_sql_host_profile_release_gate_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.legacy_sql_host_profile_release_gate_evidence FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS legacy_sql_host_profile_release_gate_tenant_select
    ON collabio.legacy_sql_host_profile_release_gate_evidence;
CREATE POLICY legacy_sql_host_profile_release_gate_tenant_select
    ON collabio.legacy_sql_host_profile_release_gate_evidence
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS legacy_sql_host_profile_release_gate_tenant_insert
    ON collabio.legacy_sql_host_profile_release_gate_evidence;
CREATE POLICY legacy_sql_host_profile_release_gate_tenant_insert
    ON collabio.legacy_sql_host_profile_release_gate_evidence
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS legacy_sql_host_profile_release_gate_no_update
    ON collabio.legacy_sql_host_profile_release_gate_evidence;
CREATE POLICY legacy_sql_host_profile_release_gate_no_update
    ON collabio.legacy_sql_host_profile_release_gate_evidence
    FOR UPDATE
    USING (false);

DROP POLICY IF EXISTS legacy_sql_host_profile_release_gate_no_hard_delete
    ON collabio.legacy_sql_host_profile_release_gate_evidence;
CREATE POLICY legacy_sql_host_profile_release_gate_no_hard_delete
    ON collabio.legacy_sql_host_profile_release_gate_evidence
    FOR DELETE
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.legacy_sql_host_profile_release_gate_evidence TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.legacy_sql_host_profile_release_gate_evidence TO collabio_worker';
    END IF;
END
$$;
