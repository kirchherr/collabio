-- 0067_productivity_pilot_real_user_runtime_window.sql
-- Append-only, hash-only runtime and access evidence for independently admitted real users.

CREATE TABLE IF NOT EXISTS collabio.productivity_pilot_real_user_runtime_windows (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    window_id text NOT NULL CHECK (window_id ~ '^[a-z0-9][a-z0-9_.-]{0,127}$'),
    admission_id text NOT NULL CHECK (admission_id ~ '^[a-z0-9][a-z0-9_.-]{0,127}$'),
    real_user_admission_evidence_hash text NOT NULL CHECK (
        real_user_admission_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    nomination_id text NOT NULL CHECK (nomination_id ~ '^[a-z0-9][a-z0-9_.-]{0,127}$'),
    nomination_evidence_hash text NOT NULL CHECK (nomination_evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    authorization_id text NOT NULL CHECK (authorization_id ~ '^[a-z0-9][a-z0-9_.-]{0,127}$'),
    start_authorization_evidence_hash text NOT NULL CHECK (
        start_authorization_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    designated_principal_hashes jsonb NOT NULL CHECK (
        jsonb_typeof(designated_principal_hashes) = 'array'
        AND jsonb_array_length(designated_principal_hashes) BETWEEN 1 AND 25
    ),
    designated_principal_manifest_hash text NOT NULL CHECK (
        designated_principal_manifest_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    participant_role_snapshot_hash text NOT NULL CHECK (
        participant_role_snapshot_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    allowed_api_operations jsonb NOT NULL CHECK (
        jsonb_typeof(allowed_api_operations) = 'array'
        AND jsonb_array_length(allowed_api_operations) > 0
    ),
    route_scope_hash text NOT NULL CHECK (route_scope_hash ~ '^sha256:[a-f0-9]{64}$'),
    command_hash text NOT NULL CHECK (command_hash ~ '^sha256:[a-f0-9]{64}$'),
    idempotency_key_hash text NOT NULL CHECK (idempotency_key_hash ~ '^sha256:[a-f0-9]{64}$'),
    human_confirmation_statement_hash text NOT NULL CHECK (
        human_confirmation_statement_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    activated_by_principal_hash text NOT NULL CHECK (
        activated_by_principal_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    activated_at_utc timestamptz NOT NULL,
    effective_at_utc timestamptz NOT NULL,
    expires_at_utc timestamptz NOT NULL,
    window_record jsonb NOT NULL CHECK (
        jsonb_typeof(window_record) = 'object'
        AND window_record ->> 'schema_version' = 'productivity_pilot_real_user_runtime_window.v1'
        AND window_record ->> 'tenant_id' = tenant_id
        AND window_record ->> 'window_id' = window_id
        AND window_record ->> 'admission_id' = admission_id
        AND window_record ->> 'real_user_admission_evidence_hash' = real_user_admission_evidence_hash
        AND window_record ->> 'nomination_id' = nomination_id
        AND window_record ->> 'nomination_evidence_hash' = nomination_evidence_hash
        AND window_record ->> 'authorization_id' = authorization_id
        AND window_record ->> 'start_authorization_evidence_hash' = start_authorization_evidence_hash
        AND window_record ->> 'designated_principal_manifest_hash' = designated_principal_manifest_hash
        AND window_record ->> 'participant_role_snapshot_hash' = participant_role_snapshot_hash
        AND window_record ->> 'route_scope_hash' = route_scope_hash
        AND window_record ->> 'activated_by_principal_hash' = activated_by_principal_hash
        AND window_record -> 'designated_principal_hashes' = designated_principal_hashes
        AND window_record -> 'allowed_api_operations' = allowed_api_operations
        AND (window_record ->> 'authoritative_principals_verified')::boolean = true
        AND (window_record ->> 'current_roles_verified')::boolean = true
        AND (window_record ->> 'real_user_admission_verified')::boolean = true
        AND (window_record ->> 'fresh_start_chain_verified')::boolean = true
        AND (window_record ->> 'designated_principals_enforced')::boolean = true
        AND (window_record ->> 'route_scope_enforced')::boolean = true
        AND (window_record ->> 'observation_ledger_enabled')::boolean = true
        AND (window_record ->> 'runtime_window_active')::boolean = true
        AND (window_record ->> 'business_write_executed')::boolean = false
        AND (window_record ->> 'module_activation_executed')::boolean = false
        AND (window_record ->> 'feature_state_changed')::boolean = false
        AND (window_record ->> 'destructive_action_executed')::boolean = false
        AND (window_record ->> 'external_side_effect_executed')::boolean = false
        AND (window_record ->> 'content_included')::boolean = false
        AND NOT (window_record ? 'human_confirmation_statement')
    ),
    evidence_hash text NOT NULL CHECK (evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    schema_version text NOT NULL DEFAULT 'productivity_pilot_real_user_runtime_window.v1' CHECK (
        schema_version = 'productivity_pilot_real_user_runtime_window.v1'
    ),
    PRIMARY KEY (tenant_id, window_id),
    UNIQUE (tenant_id, idempotency_key_hash),
    FOREIGN KEY (tenant_id, admission_id)
        REFERENCES collabio.productivity_pilot_real_user_admissions(tenant_id, admission_id),
    FOREIGN KEY (tenant_id, nomination_id)
        REFERENCES collabio.productivity_pilot_real_user_nominations(tenant_id, nomination_id),
    FOREIGN KEY (tenant_id, authorization_id)
        REFERENCES collabio.productivity_pilot_start_authorizations(tenant_id, authorization_id),
    CHECK (effective_at_utc >= activated_at_utc),
    CHECK (expires_at_utc > effective_at_utc),
    CHECK (window_record ->> 'evidence_hash' = evidence_hash),
    CHECK (position('"human_confirmation_statement"' in lower(window_record::text)) = 0),
    CHECK (position('"designated_principal_ids"' in lower(window_record::text)) = 0),
    CHECK (position('"activated_by"' in lower(window_record::text)) = 0),
    CHECK (position('"password"' in lower(window_record::text)) = 0),
    CHECK (position('"raw_payload"' in lower(window_record::text)) = 0),
    CHECK (position('"request_body"' in lower(window_record::text)) = 0),
    CHECK (position('"response_body"' in lower(window_record::text)) = 0)
);

COMMENT ON TABLE collabio.productivity_pilot_real_user_runtime_windows IS
    'Append-only real-user runtime authorization evidence containing only principal hashes.';

ALTER TABLE collabio.productivity_pilot_real_user_runtime_windows ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.productivity_pilot_real_user_runtime_windows FORCE ROW LEVEL SECURITY;

CREATE POLICY productivity_pilot_real_user_runtime_windows_tenant_select
    ON collabio.productivity_pilot_real_user_runtime_windows
    FOR SELECT USING (tenant_id = collabio.current_tenant_id());

CREATE POLICY productivity_pilot_real_user_runtime_windows_tenant_insert
    ON collabio.productivity_pilot_real_user_runtime_windows
    FOR INSERT WITH CHECK (tenant_id = collabio.current_tenant_id());

CREATE POLICY productivity_pilot_real_user_runtime_windows_no_update
    ON collabio.productivity_pilot_real_user_runtime_windows
    FOR UPDATE USING (false);

CREATE POLICY productivity_pilot_real_user_runtime_windows_no_hard_delete
    ON collabio.productivity_pilot_real_user_runtime_windows
    FOR DELETE USING (false);

CREATE TRIGGER productivity_pilot_real_user_runtime_windows_append_only
BEFORE UPDATE OR DELETE ON collabio.productivity_pilot_real_user_runtime_windows
FOR EACH ROW EXECUTE FUNCTION collabio.reject_productivity_pilot_evidence_mutation();

CREATE TABLE IF NOT EXISTS collabio.productivity_pilot_real_user_runtime_observations (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    observation_id text NOT NULL CHECK (observation_id ~ '^[a-z0-9][a-z0-9_.-]{0,127}$'),
    window_id text NOT NULL CHECK (window_id ~ '^[a-z0-9][a-z0-9_.-]{0,127}$'),
    admission_id text NOT NULL CHECK (admission_id ~ '^[a-z0-9][a-z0-9_.-]{0,127}$'),
    real_user_admission_evidence_hash text NOT NULL CHECK (
        real_user_admission_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    authorization_id text NOT NULL CHECK (authorization_id ~ '^[a-z0-9][a-z0-9_.-]{0,127}$'),
    start_authorization_evidence_hash text NOT NULL CHECK (
        start_authorization_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    window_evidence_hash text NOT NULL CHECK (window_evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    principal_id_hash text NOT NULL CHECK (principal_id_hash ~ '^sha256:[a-f0-9]{64}$'),
    operation text NOT NULL CHECK (
        operation ~ '^(GET|POST|PUT|PATCH|DELETE) /v1/[a-z0-9_./{}-]+$'
    ),
    observed_at_utc timestamptz NOT NULL,
    observation_record jsonb NOT NULL CHECK (
        jsonb_typeof(observation_record) = 'object'
        AND observation_record ->> 'schema_version' = 'productivity_pilot_real_user_runtime_observation.v1'
        AND observation_record ->> 'tenant_id' = tenant_id
        AND observation_record ->> 'observation_id' = observation_id
        AND observation_record ->> 'window_id' = window_id
        AND observation_record ->> 'admission_id' = admission_id
        AND observation_record ->> 'real_user_admission_evidence_hash' = real_user_admission_evidence_hash
        AND observation_record ->> 'authorization_id' = authorization_id
        AND observation_record ->> 'start_authorization_evidence_hash' = start_authorization_evidence_hash
        AND observation_record ->> 'window_evidence_hash' = window_evidence_hash
        AND observation_record ->> 'principal_id_hash' = principal_id_hash
        AND observation_record ->> 'operation' = operation
        AND (observation_record ->> 'authorization_allowed')::boolean = true
        AND (observation_record ->> 'active_principal_verified')::boolean = true
        AND (observation_record ->> 'current_roles_verified')::boolean = true
        AND (observation_record ->> 'designated_principal_verified')::boolean = true
        AND (observation_record ->> 'route_scope_verified')::boolean = true
        AND (observation_record ->> 'response_payload_observed')::boolean = false
        AND (observation_record ->> 'business_payload_persisted')::boolean = false
        AND (observation_record ->> 'content_included')::boolean = false
    ),
    evidence_hash text NOT NULL CHECK (evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    schema_version text NOT NULL DEFAULT 'productivity_pilot_real_user_runtime_observation.v1' CHECK (
        schema_version = 'productivity_pilot_real_user_runtime_observation.v1'
    ),
    PRIMARY KEY (tenant_id, observation_id),
    FOREIGN KEY (tenant_id, window_id)
        REFERENCES collabio.productivity_pilot_real_user_runtime_windows(tenant_id, window_id),
    FOREIGN KEY (tenant_id, admission_id)
        REFERENCES collabio.productivity_pilot_real_user_admissions(tenant_id, admission_id),
    FOREIGN KEY (tenant_id, authorization_id)
        REFERENCES collabio.productivity_pilot_start_authorizations(tenant_id, authorization_id),
    CHECK (observation_record ->> 'evidence_hash' = evidence_hash),
    CHECK (position('"principal_id"' in lower(observation_record::text)) = 0),
    CHECK (position('"password"' in lower(observation_record::text)) = 0),
    CHECK (position('"raw_payload"' in lower(observation_record::text)) = 0),
    CHECK (position('"request_body"' in lower(observation_record::text)) = 0),
    CHECK (position('"response_body"' in lower(observation_record::text)) = 0)
);

COMMENT ON TABLE collabio.productivity_pilot_real_user_runtime_observations IS
    'Append-only metadata-only access observations using tenant-bound principal hashes.';

ALTER TABLE collabio.productivity_pilot_real_user_runtime_observations ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.productivity_pilot_real_user_runtime_observations FORCE ROW LEVEL SECURITY;

CREATE POLICY productivity_pilot_real_user_runtime_observations_tenant_select
    ON collabio.productivity_pilot_real_user_runtime_observations
    FOR SELECT USING (tenant_id = collabio.current_tenant_id());

CREATE POLICY productivity_pilot_real_user_runtime_observations_tenant_insert
    ON collabio.productivity_pilot_real_user_runtime_observations
    FOR INSERT WITH CHECK (tenant_id = collabio.current_tenant_id());

CREATE POLICY productivity_pilot_real_user_runtime_observations_no_update
    ON collabio.productivity_pilot_real_user_runtime_observations
    FOR UPDATE USING (false);

CREATE POLICY productivity_pilot_real_user_runtime_observations_no_hard_delete
    ON collabio.productivity_pilot_real_user_runtime_observations
    FOR DELETE USING (false);

CREATE TRIGGER productivity_pilot_real_user_runtime_observations_append_only
BEFORE UPDATE OR DELETE ON collabio.productivity_pilot_real_user_runtime_observations
FOR EACH ROW EXECUTE FUNCTION collabio.reject_productivity_pilot_evidence_mutation();

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_authz_admin') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.productivity_pilot_real_user_runtime_windows TO collabio_authz_admin';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.productivity_pilot_real_user_runtime_observations TO collabio_authz_admin';
    END IF;
END
$$;
