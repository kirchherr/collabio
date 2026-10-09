-- 0065_productivity_pilot_closure_report.sql
-- Append-only, metadata-only closure evidence for controlled productivity pilots.

CREATE TABLE IF NOT EXISTS collabio.productivity_pilot_closure_reports (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    closure_id text NOT NULL CHECK (closure_id ~ '^[a-z0-9][a-z0-9_.-]{0,127}$'),
    window_id text NOT NULL CHECK (window_id ~ '^[a-z0-9][a-z0-9_.-]{0,127}$'),
    authorization_id text NOT NULL CHECK (authorization_id ~ '^[a-z0-9][a-z0-9_.-]{0,127}$'),
    runtime_window_evidence_hash text NOT NULL CHECK (runtime_window_evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    start_authorization_evidence_hash text NOT NULL CHECK (
        start_authorization_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    route_scope_hash text NOT NULL CHECK (route_scope_hash ~ '^sha256:[a-f0-9]{64}$'),
    observation_manifest_hash text NOT NULL CHECK (observation_manifest_hash ~ '^sha256:[a-f0-9]{64}$'),
    observation_count integer NOT NULL CHECK (observation_count = 7),
    distinct_principal_hash_count integer NOT NULL CHECK (distinct_principal_hash_count BETWEEN 1 AND 25),
    domain_receipt_manifest_hash text NOT NULL CHECK (
        domain_receipt_manifest_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    domain_receipt_count integer NOT NULL CHECK (domain_receipt_count = 3),
    backup_sha256 text NOT NULL CHECK (backup_sha256 ~ '^sha256:[a-f0-9]{64}$'),
    postgres_restore_drill_report_hash text NOT NULL CHECK (
        postgres_restore_drill_report_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    backend_foundation_gate_hash text NOT NULL CHECK (backend_foundation_gate_hash ~ '^sha256:[a-f0-9]{64}$'),
    business_backend_release_gate_hash text NOT NULL CHECK (
        business_backend_release_gate_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    command_hash text NOT NULL CHECK (command_hash ~ '^sha256:[a-f0-9]{64}$'),
    idempotency_key_hash text NOT NULL CHECK (idempotency_key_hash ~ '^sha256:[a-f0-9]{64}$'),
    human_confirmation_statement_hash text NOT NULL CHECK (
        human_confirmation_statement_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    change_request_ref text NOT NULL CHECK (change_request_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    human_confirmation_reference text NOT NULL CHECK (
        human_confirmation_reference ~ '^[a-z0-9][a-z0-9_+.-]*:.+'
    ),
    operations_owner_ref text NOT NULL CHECK (operations_owner_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    recovery_owner_ref text NOT NULL CHECK (recovery_owner_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    closed_by text NOT NULL CHECK (closed_by <> ''),
    closed_at_utc timestamptz NOT NULL,
    recovery_observed_at_utc timestamptz NOT NULL,
    closure_record jsonb NOT NULL CHECK (
        jsonb_typeof(closure_record) = 'object'
        AND closure_record ->> 'schema_version' = 'productivity_pilot_closure_report.v1'
        AND closure_record ->> 'tenant_id' = tenant_id
        AND closure_record ->> 'closure_id' = closure_id
        AND closure_record ->> 'window_id' = window_id
        AND closure_record ->> 'authorization_id' = authorization_id
        AND closure_record ->> 'runtime_window_evidence_hash' = runtime_window_evidence_hash
        AND closure_record ->> 'start_authorization_evidence_hash' = start_authorization_evidence_hash
        AND (closure_record ->> 'observation_count')::integer = observation_count
        AND jsonb_array_length(closure_record -> 'operation_summaries') = observation_count
        AND jsonb_array_length(closure_record -> 'domain_receipts') = domain_receipt_count
        AND (closure_record ->> 'runtime_switch_closed')::boolean = true
        AND (closure_record ->> 'exact_route_observations_verified')::boolean = true
        AND (closure_record ->> 'designated_principals_verified')::boolean = true
        AND (closure_record ->> 'domain_receipts_verified')::boolean = true
        AND (closure_record ->> 'recovery_evidence_verified')::boolean = true
        AND (closure_record ->> 'records_preserved')::boolean = true
        AND (closure_record ->> 'business_write_executed')::boolean = false
        AND (closure_record ->> 'destructive_action_executed')::boolean = false
        AND (closure_record ->> 'external_side_effect_executed')::boolean = false
        AND (closure_record ->> 'content_included')::boolean = false
        AND (closure_record -> 'recovery_evidence' ->> 'ready')::boolean = true
        AND (closure_record -> 'recovery_evidence' ->> 'content_included')::boolean = false
        AND NOT (closure_record ? 'human_confirmation_statement')
    ),
    evidence_hash text NOT NULL CHECK (evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    schema_version text NOT NULL DEFAULT 'productivity_pilot_closure_report.v1' CHECK (
        schema_version = 'productivity_pilot_closure_report.v1'
    ),
    PRIMARY KEY (tenant_id, closure_id),
    UNIQUE (tenant_id, window_id),
    UNIQUE (tenant_id, idempotency_key_hash),
    FOREIGN KEY (tenant_id, window_id)
        REFERENCES collabio.productivity_pilot_runtime_windows(tenant_id, window_id),
    FOREIGN KEY (tenant_id, authorization_id)
        REFERENCES collabio.productivity_pilot_start_authorizations(tenant_id, authorization_id),
    CHECK (recovery_observed_at_utc >= closed_at_utc),
    CHECK (closure_record ->> 'evidence_hash' = evidence_hash),
    CHECK (position('"human_confirmation_statement"' in lower(closure_record::text)) = 0),
    CHECK (position('"principal_id"' in lower(closure_record::text)) = 0),
    CHECK (position('"created_by"' in lower(closure_record::text)) = 0),
    CHECK (position('"password"' in lower(closure_record::text)) = 0),
    CHECK (position('"raw_payload"' in lower(closure_record::text)) = 0),
    CHECK (position('"request_body"' in lower(closure_record::text)) = 0),
    CHECK (position('"response_body"' in lower(closure_record::text)) = 0)
);

COMMENT ON TABLE collabio.productivity_pilot_closure_reports IS
    'Append-only metadata-only proof that a controlled productivity pilot was closed and recovery-verified.';

ALTER TABLE collabio.productivity_pilot_closure_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.productivity_pilot_closure_reports FORCE ROW LEVEL SECURITY;

CREATE POLICY productivity_pilot_closure_reports_tenant_select
    ON collabio.productivity_pilot_closure_reports
    FOR SELECT USING (tenant_id = collabio.current_tenant_id());

CREATE POLICY productivity_pilot_closure_reports_tenant_insert
    ON collabio.productivity_pilot_closure_reports
    FOR INSERT WITH CHECK (tenant_id = collabio.current_tenant_id());

CREATE POLICY productivity_pilot_closure_reports_no_update
    ON collabio.productivity_pilot_closure_reports
    FOR UPDATE USING (false);

CREATE POLICY productivity_pilot_closure_reports_no_hard_delete
    ON collabio.productivity_pilot_closure_reports
    FOR DELETE USING (false);

CREATE TRIGGER productivity_pilot_closure_reports_append_only
BEFORE UPDATE OR DELETE ON collabio.productivity_pilot_closure_reports
FOR EACH ROW EXECUTE FUNCTION collabio.reject_productivity_pilot_evidence_mutation();

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_authz_admin') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.productivity_pilot_closure_reports TO collabio_authz_admin';
    END IF;
END
$$;
