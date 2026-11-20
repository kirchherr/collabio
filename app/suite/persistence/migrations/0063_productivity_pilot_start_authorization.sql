-- 0063_productivity_pilot_start_authorization.sql
-- Append-only, time-bounded, four-eyes start authorization for controlled pilot traffic.

CREATE TABLE IF NOT EXISTS collabio.productivity_pilot_start_authorizations (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    authorization_id text NOT NULL CHECK (authorization_id ~ '^[a-z0-9][a-z0-9_.-]{0,127}$'),
    enforcement_id text NOT NULL CHECK (enforcement_id ~ '^[a-z0-9][a-z0-9_.-]{0,127}$'),
    traffic_scope_evidence_hash text NOT NULL CHECK (traffic_scope_evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    route_scope_hash text NOT NULL CHECK (route_scope_hash ~ '^sha256:[a-f0-9]{64}$'),
    admission_evidence_hash text NOT NULL CHECK (admission_evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    preflight_gate_hash text NOT NULL REFERENCES collabio.productivity_pilot_preflight_reports(gate_hash),
    policy_hash text NOT NULL CHECK (policy_hash ~ '^sha256:[a-f0-9]{64}$'),
    allowed_api_operations jsonb NOT NULL CHECK (
        jsonb_typeof(allowed_api_operations) = 'array'
        AND jsonb_array_length(allowed_api_operations) > 0
    ),
    monitoring_evidence_manifest_hash text NOT NULL CHECK (
        monitoring_evidence_manifest_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    rollback_evidence_manifest_hash text NOT NULL CHECK (
        rollback_evidence_manifest_hash ~ '^sha256:[a-f0-9]{64}$'
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
    security_approval_ref text NOT NULL CHECK (security_approval_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    authorized_by text NOT NULL CHECK (authorized_by <> ''),
    authorized_at_utc timestamptz NOT NULL,
    effective_at_utc timestamptz NOT NULL,
    expires_at_utc timestamptz NOT NULL,
    authorization_record jsonb NOT NULL CHECK (
        jsonb_typeof(authorization_record) = 'object'
        AND authorization_record ->> 'schema_version' = 'productivity_pilot_start_authorization.v1'
        AND authorization_record ->> 'tenant_id' = tenant_id
        AND authorization_record ->> 'authorization_id' = authorization_id
        AND authorization_record ->> 'enforcement_id' = enforcement_id
        AND authorization_record ->> 'traffic_scope_evidence_hash' = traffic_scope_evidence_hash
        AND authorization_record ->> 'route_scope_hash' = route_scope_hash
        AND authorization_record ->> 'admission_evidence_hash' = admission_evidence_hash
        AND authorization_record ->> 'preflight_gate_hash' = preflight_gate_hash
        AND authorization_record ->> 'policy_hash' = policy_hash
        AND authorization_record -> 'allowed_api_operations' = allowed_api_operations
        AND (authorization_record ->> 'four_eyes_verified')::boolean = true
        AND (authorization_record ->> 'monitoring_controls_verified')::boolean = true
        AND (authorization_record ->> 'rollback_controls_verified')::boolean = true
        AND (authorization_record ->> 'runtime_enablement_verified')::boolean = true
        AND (authorization_record ->> 'pilot_start_authorized')::boolean = true
        AND (authorization_record ->> 'pilot_business_traffic_allowed')::boolean = true
        AND (authorization_record ->> 'tenant_state_changed')::boolean = false
        AND (authorization_record ->> 'module_activation_executed')::boolean = false
        AND (authorization_record ->> 'business_write_executed')::boolean = false
        AND (authorization_record ->> 'destructive_action_executed')::boolean = false
        AND (authorization_record ->> 'external_side_effect_executed')::boolean = false
        AND (authorization_record ->> 'content_included')::boolean = false
        AND NOT (authorization_record ? 'human_confirmation_statement')
    ),
    evidence_hash text NOT NULL CHECK (evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    schema_version text NOT NULL DEFAULT 'productivity_pilot_start_authorization.v1' CHECK (
        schema_version = 'productivity_pilot_start_authorization.v1'
    ),
    PRIMARY KEY (tenant_id, authorization_id),
    UNIQUE (tenant_id, idempotency_key_hash),
    FOREIGN KEY (tenant_id, enforcement_id)
        REFERENCES collabio.productivity_pilot_traffic_scope_enforcements(tenant_id, enforcement_id),
    CHECK (effective_at_utc >= authorized_at_utc),
    CHECK (expires_at_utc > effective_at_utc),
    CHECK (expires_at_utc <= effective_at_utc + interval '8 hours'),
    CHECK (authorization_record ->> 'evidence_hash' = evidence_hash),
    CHECK (position('"human_confirmation_statement"' in lower(authorization_record::text)) = 0),
    CHECK (position('"password"' in lower(authorization_record::text)) = 0),
    CHECK (position('"raw_payload"' in lower(authorization_record::text)) = 0)
);

COMMENT ON TABLE collabio.productivity_pilot_start_authorizations IS
    'Append-only, time-bounded, four-eyes authorization for exact controlled pilot traffic; no business write is executed by this record.';

ALTER TABLE collabio.productivity_pilot_start_authorizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.productivity_pilot_start_authorizations FORCE ROW LEVEL SECURITY;

CREATE POLICY productivity_pilot_start_authorizations_tenant_select
    ON collabio.productivity_pilot_start_authorizations
    FOR SELECT USING (tenant_id = collabio.current_tenant_id());

CREATE POLICY productivity_pilot_start_authorizations_tenant_insert
    ON collabio.productivity_pilot_start_authorizations
    FOR INSERT WITH CHECK (tenant_id = collabio.current_tenant_id());

CREATE POLICY productivity_pilot_start_authorizations_no_update
    ON collabio.productivity_pilot_start_authorizations
    FOR UPDATE USING (false);

CREATE POLICY productivity_pilot_start_authorizations_no_hard_delete
    ON collabio.productivity_pilot_start_authorizations
    FOR DELETE USING (false);

CREATE TRIGGER productivity_pilot_start_authorizations_append_only
BEFORE UPDATE OR DELETE ON collabio.productivity_pilot_start_authorizations
FOR EACH ROW EXECUTE FUNCTION collabio.reject_productivity_pilot_evidence_mutation();

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_authz_admin') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.productivity_pilot_start_authorizations TO collabio_authz_admin';
    END IF;
END
$$;
