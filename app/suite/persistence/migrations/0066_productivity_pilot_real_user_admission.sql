-- 0066_productivity_pilot_real_user_admission.sql
-- Append-only, pseudonymized nomination and independent admission evidence for real-user pilots.

CREATE TABLE IF NOT EXISTS collabio.productivity_pilot_real_user_nominations (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    nomination_id text NOT NULL CHECK (nomination_id ~ '^[a-z0-9][a-z0-9_.-]{0,127}$'),
    baseline_closure_id text NOT NULL CHECK (baseline_closure_id ~ '^[a-z0-9][a-z0-9_.-]{0,127}$'),
    baseline_closure_evidence_hash text NOT NULL CHECK (
        baseline_closure_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    participant_manifest_hash text NOT NULL CHECK (participant_manifest_hash ~ '^sha256:[a-f0-9]{64}$'),
    participant_count integer NOT NULL CHECK (participant_count BETWEEN 1 AND 25),
    scheduled_start_at_utc timestamptz NOT NULL,
    scheduled_end_at_utc timestamptz NOT NULL,
    command_hash text NOT NULL CHECK (command_hash ~ '^sha256:[a-f0-9]{64}$'),
    idempotency_key_hash text NOT NULL CHECK (idempotency_key_hash ~ '^sha256:[a-f0-9]{64}$'),
    human_confirmation_statement_hash text NOT NULL CHECK (
        human_confirmation_statement_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    nominated_by_principal_hash text NOT NULL CHECK (
        nominated_by_principal_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    nominated_at_utc timestamptz NOT NULL,
    nomination_record jsonb NOT NULL CHECK (
        jsonb_typeof(nomination_record) = 'object'
        AND nomination_record ->> 'schema_version' = 'productivity_pilot_real_user_nomination.v1'
        AND nomination_record ->> 'tenant_id' = tenant_id
        AND nomination_record ->> 'nomination_id' = nomination_id
        AND nomination_record ->> 'baseline_closure_evidence_hash' = baseline_closure_evidence_hash
        AND nomination_record ->> 'participant_manifest_hash' = participant_manifest_hash
        AND (nomination_record ->> 'participant_count')::integer = participant_count
        AND jsonb_array_length(nomination_record -> 'participants') = participant_count
        AND (nomination_record ->> 'authoritative_principals_verified')::boolean = true
        AND (nomination_record ->> 'authoritative_roles_verified')::boolean = true
        AND (nomination_record ->> 'purpose_limitation_recorded')::boolean = true
        AND (nomination_record ->> 'privacy_review_recorded')::boolean = true
        AND (nomination_record ->> 'nomination_recorded')::boolean = true
        AND (nomination_record ->> 'security_approval_recorded')::boolean = false
        AND (nomination_record ->> 'runtime_activation_allowed')::boolean = false
        AND (nomination_record ->> 'traffic_authorization_allowed')::boolean = false
        AND (nomination_record ->> 'business_write_executed')::boolean = false
        AND (nomination_record ->> 'destructive_action_executed')::boolean = false
        AND (nomination_record ->> 'external_side_effect_executed')::boolean = false
        AND (nomination_record ->> 'content_included')::boolean = false
        AND NOT (nomination_record ? 'human_confirmation_statement')
    ),
    evidence_hash text NOT NULL CHECK (evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    schema_version text NOT NULL DEFAULT 'productivity_pilot_real_user_nomination.v1' CHECK (
        schema_version = 'productivity_pilot_real_user_nomination.v1'
    ),
    PRIMARY KEY (tenant_id, nomination_id),
    UNIQUE (tenant_id, idempotency_key_hash),
    FOREIGN KEY (tenant_id, baseline_closure_id)
        REFERENCES collabio.productivity_pilot_closure_reports(tenant_id, closure_id),
    CHECK (scheduled_start_at_utc >= nominated_at_utc),
    CHECK (scheduled_end_at_utc > scheduled_start_at_utc),
    CHECK (scheduled_end_at_utc - scheduled_start_at_utc <= interval '30 days'),
    CHECK (nomination_record ->> 'evidence_hash' = evidence_hash),
    CHECK (position('"human_confirmation_statement"' in lower(nomination_record::text)) = 0),
    CHECK (position('"principal_id"' in lower(nomination_record::text)) = 0),
    CHECK (position('"password"' in lower(nomination_record::text)) = 0),
    CHECK (position('"raw_payload"' in lower(nomination_record::text)) = 0),
    CHECK (position('"request_body"' in lower(nomination_record::text)) = 0),
    CHECK (position('"response_body"' in lower(nomination_record::text)) = 0)
);

COMMENT ON TABLE collabio.productivity_pilot_real_user_nominations IS
    'Append-only pseudonymized participant nomination evidence; no module, traffic, or runtime activation.';

ALTER TABLE collabio.productivity_pilot_real_user_nominations ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.productivity_pilot_real_user_nominations FORCE ROW LEVEL SECURITY;

CREATE POLICY productivity_pilot_real_user_nominations_tenant_select
    ON collabio.productivity_pilot_real_user_nominations
    FOR SELECT USING (tenant_id = collabio.current_tenant_id());

CREATE POLICY productivity_pilot_real_user_nominations_tenant_insert
    ON collabio.productivity_pilot_real_user_nominations
    FOR INSERT WITH CHECK (tenant_id = collabio.current_tenant_id());

CREATE POLICY productivity_pilot_real_user_nominations_no_update
    ON collabio.productivity_pilot_real_user_nominations
    FOR UPDATE USING (false);

CREATE POLICY productivity_pilot_real_user_nominations_no_hard_delete
    ON collabio.productivity_pilot_real_user_nominations
    FOR DELETE USING (false);

CREATE TRIGGER productivity_pilot_real_user_nominations_append_only
BEFORE UPDATE OR DELETE ON collabio.productivity_pilot_real_user_nominations
FOR EACH ROW EXECUTE FUNCTION collabio.reject_productivity_pilot_evidence_mutation();

CREATE TABLE IF NOT EXISTS collabio.productivity_pilot_real_user_admissions (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    admission_id text NOT NULL CHECK (admission_id ~ '^[a-z0-9][a-z0-9_.-]{0,127}$'),
    nomination_id text NOT NULL CHECK (nomination_id ~ '^[a-z0-9][a-z0-9_.-]{0,127}$'),
    nomination_evidence_hash text NOT NULL CHECK (nomination_evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    participant_manifest_hash text NOT NULL CHECK (participant_manifest_hash ~ '^sha256:[a-f0-9]{64}$'),
    participant_count integer NOT NULL CHECK (participant_count BETWEEN 1 AND 25),
    preflight_gate_hash text NOT NULL REFERENCES collabio.productivity_pilot_preflight_reports(gate_hash),
    backup_sha256 text NOT NULL CHECK (backup_sha256 ~ '^sha256:[a-f0-9]{64}$'),
    postgres_restore_drill_report_hash text NOT NULL CHECK (
        postgres_restore_drill_report_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    backend_foundation_gate_hash text NOT NULL CHECK (backend_foundation_gate_hash ~ '^sha256:[a-f0-9]{64}$'),
    control_evidence_observed_at_utc timestamptz NOT NULL,
    scheduled_start_at_utc timestamptz NOT NULL,
    scheduled_end_at_utc timestamptz NOT NULL,
    command_hash text NOT NULL CHECK (command_hash ~ '^sha256:[a-f0-9]{64}$'),
    idempotency_key_hash text NOT NULL CHECK (idempotency_key_hash ~ '^sha256:[a-f0-9]{64}$'),
    human_confirmation_statement_hash text NOT NULL CHECK (
        human_confirmation_statement_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    approved_by_principal_hash text NOT NULL CHECK (
        approved_by_principal_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    approved_at_utc timestamptz NOT NULL,
    admission_record jsonb NOT NULL CHECK (
        jsonb_typeof(admission_record) = 'object'
        AND admission_record ->> 'schema_version' = 'productivity_pilot_real_user_admission.v1'
        AND admission_record ->> 'tenant_id' = tenant_id
        AND admission_record ->> 'admission_id' = admission_id
        AND admission_record ->> 'nomination_id' = nomination_id
        AND admission_record ->> 'nomination_evidence_hash' = nomination_evidence_hash
        AND admission_record ->> 'participant_manifest_hash' = participant_manifest_hash
        AND (admission_record ->> 'participant_count')::integer = participant_count
        AND jsonb_array_length(admission_record -> 'approved_principal_hashes') = participant_count
        AND (admission_record ->> 'current_principals_verified')::boolean = true
        AND (admission_record ->> 'current_roles_verified')::boolean = true
        AND (admission_record ->> 'purpose_and_privacy_binding_verified')::boolean = true
        AND (admission_record ->> 'fresh_control_evidence_verified')::boolean = true
        AND (admission_record ->> 'four_eyes_verified')::boolean = true
        AND (admission_record ->> 'security_admission_recorded')::boolean = true
        AND (admission_record ->> 'runtime_activation_allowed')::boolean = false
        AND (admission_record ->> 'traffic_authorization_allowed')::boolean = false
        AND (admission_record ->> 'business_write_executed')::boolean = false
        AND (admission_record ->> 'destructive_action_executed')::boolean = false
        AND (admission_record ->> 'external_side_effect_executed')::boolean = false
        AND (admission_record ->> 'content_included')::boolean = false
        AND NOT (admission_record ? 'human_confirmation_statement')
    ),
    evidence_hash text NOT NULL CHECK (evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    schema_version text NOT NULL DEFAULT 'productivity_pilot_real_user_admission.v1' CHECK (
        schema_version = 'productivity_pilot_real_user_admission.v1'
    ),
    PRIMARY KEY (tenant_id, admission_id),
    UNIQUE (tenant_id, nomination_id),
    UNIQUE (tenant_id, idempotency_key_hash),
    FOREIGN KEY (tenant_id, nomination_id)
        REFERENCES collabio.productivity_pilot_real_user_nominations(tenant_id, nomination_id),
    CHECK (control_evidence_observed_at_utc >= scheduled_start_at_utc - interval '30 days'),
    CHECK (scheduled_end_at_utc > scheduled_start_at_utc),
    CHECK (approved_at_utc < scheduled_end_at_utc),
    CHECK (admission_record ->> 'evidence_hash' = evidence_hash),
    CHECK (position('"human_confirmation_statement"' in lower(admission_record::text)) = 0),
    CHECK (position('"principal_id"' in lower(admission_record::text)) = 0),
    CHECK (position('"password"' in lower(admission_record::text)) = 0),
    CHECK (position('"raw_payload"' in lower(admission_record::text)) = 0),
    CHECK (position('"request_body"' in lower(admission_record::text)) = 0),
    CHECK (position('"response_body"' in lower(admission_record::text)) = 0)
);

COMMENT ON TABLE collabio.productivity_pilot_real_user_admissions IS
    'Append-only independent real-user pilot admission evidence; runtime and traffic remain disabled.';

ALTER TABLE collabio.productivity_pilot_real_user_admissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.productivity_pilot_real_user_admissions FORCE ROW LEVEL SECURITY;

CREATE POLICY productivity_pilot_real_user_admissions_tenant_select
    ON collabio.productivity_pilot_real_user_admissions
    FOR SELECT USING (tenant_id = collabio.current_tenant_id());

CREATE POLICY productivity_pilot_real_user_admissions_tenant_insert
    ON collabio.productivity_pilot_real_user_admissions
    FOR INSERT WITH CHECK (tenant_id = collabio.current_tenant_id());

CREATE POLICY productivity_pilot_real_user_admissions_no_update
    ON collabio.productivity_pilot_real_user_admissions
    FOR UPDATE USING (false);

CREATE POLICY productivity_pilot_real_user_admissions_no_hard_delete
    ON collabio.productivity_pilot_real_user_admissions
    FOR DELETE USING (false);

CREATE TRIGGER productivity_pilot_real_user_admissions_append_only
BEFORE UPDATE OR DELETE ON collabio.productivity_pilot_real_user_admissions
FOR EACH ROW EXECUTE FUNCTION collabio.reject_productivity_pilot_evidence_mutation();

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_authz_admin') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.productivity_pilot_real_user_nominations TO collabio_authz_admin';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.productivity_pilot_real_user_admissions TO collabio_authz_admin';
    END IF;
END
$$;
