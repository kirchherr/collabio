-- 0069_productivity_pilot_real_user_closure_report.sql
-- Append-only, hash-only closure evidence for an independently admitted real-user pilot.

CREATE TABLE IF NOT EXISTS collabio.productivity_pilot_real_user_closure_reports (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    closure_id text NOT NULL CHECK (closure_id ~ '^[a-z0-9][a-z0-9_.-]{0,127}$'),
    window_id text NOT NULL CHECK (window_id ~ '^[a-z0-9][a-z0-9_.-]{0,127}$'),
    admission_id text NOT NULL CHECK (admission_id ~ '^[a-z0-9][a-z0-9_.-]{0,127}$'),
    nomination_id text NOT NULL CHECK (nomination_id ~ '^[a-z0-9][a-z0-9_.-]{0,127}$'),
    authorization_id text NOT NULL CHECK (authorization_id ~ '^[a-z0-9][a-z0-9_.-]{0,127}$'),
    runtime_window_evidence_hash text NOT NULL CHECK (
        runtime_window_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    real_user_admission_evidence_hash text NOT NULL CHECK (
        real_user_admission_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    observation_manifest_hash text NOT NULL CHECK (
        observation_manifest_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    observation_count integer NOT NULL CHECK (observation_count >= 0),
    domain_receipt_manifest_hash text NOT NULL CHECK (
        domain_receipt_manifest_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    domain_receipt_count integer NOT NULL CHECK (domain_receipt_count >= 0),
    command_hash text NOT NULL CHECK (command_hash ~ '^sha256:[a-f0-9]{64}$'),
    idempotency_key_hash text NOT NULL CHECK (idempotency_key_hash ~ '^sha256:[a-f0-9]{64}$'),
    closed_by_principal_hash text NOT NULL CHECK (
        closed_by_principal_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    closed_at_utc timestamptz NOT NULL,
    recovery_observed_at_utc timestamptz NOT NULL,
    closure_record jsonb NOT NULL CHECK (
        jsonb_typeof(closure_record) = 'object'
        AND closure_record ->> 'schema_version' = 'productivity_pilot_real_user_closure_report.v1'
        AND closure_record ->> 'tenant_id' = tenant_id
        AND closure_record ->> 'closure_id' = closure_id
        AND closure_record ->> 'window_id' = window_id
        AND closure_record ->> 'admission_id' = admission_id
        AND closure_record ->> 'nomination_id' = nomination_id
        AND closure_record ->> 'authorization_id' = authorization_id
        AND closure_record ->> 'runtime_window_evidence_hash' = runtime_window_evidence_hash
        AND closure_record ->> 'real_user_admission_evidence_hash' = real_user_admission_evidence_hash
        AND closure_record ->> 'observation_manifest_hash' = observation_manifest_hash
        AND (closure_record ->> 'observation_count')::integer = observation_count
        AND jsonb_array_length(closure_record -> 'domain_receipts') = domain_receipt_count
        AND closure_record ->> 'domain_receipt_manifest_hash' = domain_receipt_manifest_hash
        AND closure_record ->> 'command_hash' = command_hash
        AND closure_record ->> 'idempotency_key_hash' = idempotency_key_hash
        AND closure_record ->> 'closed_by_principal_hash' = closed_by_principal_hash
        AND (closure_record ->> 'runtime_switch_closed')::boolean = true
        AND (closure_record ->> 'window_evidence_verified')::boolean = true
        AND (closure_record ->> 'admission_chain_verified')::boolean = true
        AND (closure_record ->> 'complete_observation_manifest_verified')::boolean = true
        AND (closure_record ->> 'designated_principals_verified')::boolean = true
        AND (closure_record ->> 'domain_receipts_verified')::boolean = true
        AND (closure_record ->> 'recovery_evidence_verified')::boolean = true
        AND (closure_record ->> 'records_preserved')::boolean = true
        AND (closure_record ->> 'pilot_activity_observed')::boolean = (observation_count > 0)
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
    schema_version text NOT NULL DEFAULT 'productivity_pilot_real_user_closure_report.v1' CHECK (
        schema_version = 'productivity_pilot_real_user_closure_report.v1'
    ),
    PRIMARY KEY (tenant_id, closure_id),
    UNIQUE (tenant_id, window_id),
    UNIQUE (tenant_id, idempotency_key_hash),
    FOREIGN KEY (tenant_id, window_id)
        REFERENCES collabio.productivity_pilot_real_user_runtime_windows(tenant_id, window_id),
    FOREIGN KEY (tenant_id, admission_id)
        REFERENCES collabio.productivity_pilot_real_user_admissions(tenant_id, admission_id),
    FOREIGN KEY (tenant_id, nomination_id)
        REFERENCES collabio.productivity_pilot_real_user_nominations(tenant_id, nomination_id),
    FOREIGN KEY (tenant_id, authorization_id)
        REFERENCES collabio.productivity_pilot_start_authorizations(tenant_id, authorization_id),
    CHECK (recovery_observed_at_utc >= closed_at_utc),
    CHECK (closure_record ->> 'evidence_hash' = evidence_hash),
    CHECK (position('"human_confirmation_statement"' in lower(closure_record::text)) = 0),
    CHECK (position('"designated_principal_ids"' in lower(closure_record::text)) = 0),
    CHECK (position('"principal_id"' in lower(closure_record::text)) = 0),
    CHECK (position('"closed_by"' in lower(closure_record::text)) = 0),
    CHECK (position('"created_by"' in lower(closure_record::text)) = 0),
    CHECK (position('"password"' in lower(closure_record::text)) = 0),
    CHECK (position('"raw_payload"' in lower(closure_record::text)) = 0),
    CHECK (position('"request_body"' in lower(closure_record::text)) = 0),
    CHECK (position('"response_body"' in lower(closure_record::text)) = 0)
);

COMMENT ON TABLE collabio.productivity_pilot_real_user_closure_reports IS
    'Append-only hash-only proof that a real-user productivity pilot runtime window was closed.';

ALTER TABLE collabio.productivity_pilot_real_user_closure_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.productivity_pilot_real_user_closure_reports FORCE ROW LEVEL SECURITY;

CREATE POLICY real_user_pilot_closure_tenant_select
    ON collabio.productivity_pilot_real_user_closure_reports
    FOR SELECT USING (tenant_id = collabio.current_tenant_id());

CREATE POLICY real_user_pilot_closure_tenant_insert
    ON collabio.productivity_pilot_real_user_closure_reports
    FOR INSERT WITH CHECK (tenant_id = collabio.current_tenant_id());

CREATE POLICY real_user_pilot_closure_no_update
    ON collabio.productivity_pilot_real_user_closure_reports
    FOR UPDATE USING (false);

CREATE POLICY real_user_pilot_closure_no_hard_delete
    ON collabio.productivity_pilot_real_user_closure_reports
    FOR DELETE USING (false);

CREATE TRIGGER real_user_pilot_closure_append_only
BEFORE UPDATE OR DELETE ON collabio.productivity_pilot_real_user_closure_reports
FOR EACH ROW EXECUTE FUNCTION collabio.reject_productivity_pilot_evidence_mutation();

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_authz_admin') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.productivity_pilot_real_user_closure_reports TO collabio_authz_admin';
    END IF;
END
$$;
