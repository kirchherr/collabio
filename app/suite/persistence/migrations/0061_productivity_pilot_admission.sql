-- 0061_productivity_pilot_admission.sql
-- Authoritative preflight evidence and append-only, tenant-scoped human admission.

CREATE TABLE IF NOT EXISTS collabio.productivity_pilot_preflight_reports (
    gate_hash text PRIMARY KEY CHECK (gate_hash ~ '^sha256:[a-f0-9]{64}$'),
    checked_at_utc timestamptz NOT NULL,
    policy_hash text NOT NULL CHECK (policy_hash ~ '^sha256:[a-f0-9]{64}$'),
    business_backend_release_gate_hash text NOT NULL CHECK (
        business_backend_release_gate_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    tenant_module_state_manifest_hash text NOT NULL CHECK (
        tenant_module_state_manifest_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    candidate_tenant_ids jsonb NOT NULL CHECK (
        jsonb_typeof(candidate_tenant_ids) = 'array'
        AND jsonb_array_length(candidate_tenant_ids) > 0
    ),
    report jsonb NOT NULL CHECK (
        jsonb_typeof(report) = 'object'
        AND report ->> 'schema_version' = 'productivity_pilot_preflight_gate.v1'
        AND report ->> 'gate_hash' = gate_hash
        AND (report ->> 'preflight_ready')::boolean = true
        AND (report ->> 'pilot_start_allowed')::boolean = false
        AND (report ->> 'business_write_executed')::boolean = false
        AND (report ->> 'tenant_state_changed')::boolean = false
        AND (report ->> 'content_included')::boolean = false
    ),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    schema_version text NOT NULL DEFAULT 'productivity_pilot_preflight_gate.v1' CHECK (
        schema_version = 'productivity_pilot_preflight_gate.v1'
    ),
    CHECK (position('"password"' in lower(report::text)) = 0),
    CHECK (position('"raw_payload"' in lower(report::text)) = 0)
);

COMMENT ON TABLE collabio.productivity_pilot_preflight_reports IS
    'Authoritative metadata-only productivity pilot preflight evidence. No admission, activation or traffic change.';

ALTER TABLE collabio.productivity_pilot_preflight_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.productivity_pilot_preflight_reports FORCE ROW LEVEL SECURITY;

CREATE POLICY productivity_pilot_preflight_reports_tenant_select
    ON collabio.productivity_pilot_preflight_reports
    FOR SELECT USING (candidate_tenant_ids ? collabio.current_tenant_id());

CREATE POLICY productivity_pilot_preflight_reports_owner_insert
    ON collabio.productivity_pilot_preflight_reports
    FOR INSERT WITH CHECK (current_user = 'collabio_owner');

CREATE POLICY productivity_pilot_preflight_reports_no_update
    ON collabio.productivity_pilot_preflight_reports
    FOR UPDATE USING (false);

CREATE POLICY productivity_pilot_preflight_reports_no_hard_delete
    ON collabio.productivity_pilot_preflight_reports
    FOR DELETE USING (false);

CREATE TABLE IF NOT EXISTS collabio.productivity_pilot_admission_records (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    admission_id text NOT NULL CHECK (admission_id ~ '^[a-z0-9][a-z0-9_.-]{0,127}$'),
    preflight_gate_hash text NOT NULL REFERENCES collabio.productivity_pilot_preflight_reports(gate_hash),
    policy_hash text NOT NULL CHECK (policy_hash ~ '^sha256:[a-f0-9]{64}$'),
    business_backend_release_gate_hash text NOT NULL CHECK (
        business_backend_release_gate_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    tenant_module_state_manifest_hash text NOT NULL CHECK (
        tenant_module_state_manifest_hash ~ '^sha256:[a-f0-9]{64}$'
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
    monitoring_owner_ref text NOT NULL CHECK (monitoring_owner_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    rollback_owner_ref text NOT NULL CHECK (rollback_owner_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    admitted_by text NOT NULL CHECK (admitted_by <> ''),
    admitted_at_utc timestamptz NOT NULL,
    admission_record jsonb NOT NULL CHECK (
        jsonb_typeof(admission_record) = 'object'
        AND admission_record ->> 'schema_version' = 'productivity_pilot_admission_record.v1'
        AND admission_record ->> 'tenant_id' = tenant_id
        AND admission_record ->> 'admission_id' = admission_id
        AND admission_record ->> 'preflight_gate_hash' = preflight_gate_hash
        AND (admission_record ->> 'admission_recorded')::boolean = true
        AND (admission_record ->> 'pilot_start_allowed')::boolean = false
        AND (admission_record ->> 'traffic_scope_enforced')::boolean = false
        AND (admission_record ->> 'tenant_state_changed')::boolean = false
        AND (admission_record ->> 'business_write_executed')::boolean = false
        AND (admission_record ->> 'content_included')::boolean = false
        AND NOT (admission_record ? 'human_confirmation_statement')
    ),
    evidence_hash text NOT NULL CHECK (evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    schema_version text NOT NULL DEFAULT 'productivity_pilot_admission_record.v1' CHECK (
        schema_version = 'productivity_pilot_admission_record.v1'
    ),
    PRIMARY KEY (tenant_id, admission_id),
    UNIQUE (tenant_id, idempotency_key_hash),
    UNIQUE (tenant_id, preflight_gate_hash),
    CHECK (admission_record ->> 'evidence_hash' = evidence_hash),
    CHECK (position('"human_confirmation_statement"' in lower(admission_record::text)) = 0),
    CHECK (position('"password"' in lower(admission_record::text)) = 0),
    CHECK (position('"raw_payload"' in lower(admission_record::text)) = 0)
);

COMMENT ON TABLE collabio.productivity_pilot_admission_records IS
    'Append-only tenant admission metadata. It does not activate modules, enforce traffic or execute business writes.';

ALTER TABLE collabio.productivity_pilot_admission_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.productivity_pilot_admission_records FORCE ROW LEVEL SECURITY;

CREATE POLICY productivity_pilot_admission_records_tenant_select
    ON collabio.productivity_pilot_admission_records
    FOR SELECT USING (tenant_id = collabio.current_tenant_id());

CREATE POLICY productivity_pilot_admission_records_tenant_insert
    ON collabio.productivity_pilot_admission_records
    FOR INSERT WITH CHECK (tenant_id = collabio.current_tenant_id());

CREATE POLICY productivity_pilot_admission_records_no_update
    ON collabio.productivity_pilot_admission_records
    FOR UPDATE USING (false);

CREATE POLICY productivity_pilot_admission_records_no_hard_delete
    ON collabio.productivity_pilot_admission_records
    FOR DELETE USING (false);

CREATE OR REPLACE FUNCTION collabio.reject_productivity_pilot_evidence_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'productivity pilot evidence is append-only';
END;
$$;

CREATE TRIGGER productivity_pilot_preflight_reports_append_only
BEFORE UPDATE OR DELETE ON collabio.productivity_pilot_preflight_reports
FOR EACH ROW EXECUTE FUNCTION collabio.reject_productivity_pilot_evidence_mutation();

CREATE TRIGGER productivity_pilot_admission_records_append_only
BEFORE UPDATE OR DELETE ON collabio.productivity_pilot_admission_records
FOR EACH ROW EXECUTE FUNCTION collabio.reject_productivity_pilot_evidence_mutation();

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_authz_admin') THEN
        EXECUTE 'GRANT SELECT ON TABLE collabio.productivity_pilot_preflight_reports TO collabio_authz_admin';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.productivity_pilot_admission_records TO collabio_authz_admin';
    END IF;
END
$$;
