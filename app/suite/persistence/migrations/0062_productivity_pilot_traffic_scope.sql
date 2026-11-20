-- 0062_productivity_pilot_traffic_scope.sql
-- Append-only tenant and route scope enforcement. Pilot start remains unauthorized.

CREATE TABLE IF NOT EXISTS collabio.productivity_pilot_traffic_scope_enforcements (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    enforcement_id text NOT NULL CHECK (enforcement_id ~ '^[a-z0-9][a-z0-9_.-]{0,127}$'),
    admission_id text NOT NULL CHECK (admission_id ~ '^[a-z0-9][a-z0-9_.-]{0,127}$'),
    admission_evidence_hash text NOT NULL CHECK (admission_evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    preflight_gate_hash text NOT NULL REFERENCES collabio.productivity_pilot_preflight_reports(gate_hash),
    policy_hash text NOT NULL CHECK (policy_hash ~ '^sha256:[a-f0-9]{64}$'),
    route_scope_hash text NOT NULL CHECK (route_scope_hash ~ '^sha256:[a-f0-9]{64}$'),
    allowed_api_operations jsonb NOT NULL CHECK (
        jsonb_typeof(allowed_api_operations) = 'array'
        AND jsonb_array_length(allowed_api_operations) > 0
    ),
    command_hash text NOT NULL CHECK (command_hash ~ '^sha256:[a-f0-9]{64}$'),
    idempotency_key_hash text NOT NULL CHECK (idempotency_key_hash ~ '^sha256:[a-f0-9]{64}$'),
    human_confirmation_statement_hash text NOT NULL CHECK (
        human_confirmation_statement_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    change_request_ref text NOT NULL CHECK (change_request_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    ingress_policy_ref text NOT NULL CHECK (ingress_policy_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    human_confirmation_reference text NOT NULL CHECK (
        human_confirmation_reference ~ '^[a-z0-9][a-z0-9_+.-]*:.+'
    ),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    enforced_by text NOT NULL CHECK (enforced_by <> ''),
    enforced_at_utc timestamptz NOT NULL,
    enforcement_record jsonb NOT NULL CHECK (
        jsonb_typeof(enforcement_record) = 'object'
        AND enforcement_record ->> 'schema_version' = 'productivity_pilot_traffic_scope_enforcement.v1'
        AND enforcement_record ->> 'tenant_id' = tenant_id
        AND enforcement_record ->> 'enforcement_id' = enforcement_id
        AND enforcement_record ->> 'admission_id' = admission_id
        AND enforcement_record ->> 'preflight_gate_hash' = preflight_gate_hash
        AND (enforcement_record ->> 'tenant_scope_enforced')::boolean = true
        AND (enforcement_record ->> 'route_scope_enforced')::boolean = true
        AND (enforcement_record ->> 'default_deny_enabled')::boolean = true
        AND (enforcement_record ->> 'pilot_start_authorized')::boolean = false
        AND (enforcement_record ->> 'pilot_business_traffic_allowed')::boolean = false
        AND (enforcement_record ->> 'tenant_state_changed')::boolean = false
        AND (enforcement_record ->> 'business_write_executed')::boolean = false
        AND (enforcement_record ->> 'content_included')::boolean = false
        AND NOT (enforcement_record ? 'human_confirmation_statement')
    ),
    evidence_hash text NOT NULL CHECK (evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    schema_version text NOT NULL DEFAULT 'productivity_pilot_traffic_scope_enforcement.v1' CHECK (
        schema_version = 'productivity_pilot_traffic_scope_enforcement.v1'
    ),
    PRIMARY KEY (tenant_id, enforcement_id),
    UNIQUE (tenant_id, idempotency_key_hash),
    UNIQUE (tenant_id, admission_id),
    UNIQUE (tenant_id, preflight_gate_hash),
    FOREIGN KEY (tenant_id, admission_id)
        REFERENCES collabio.productivity_pilot_admission_records(tenant_id, admission_id),
    CHECK (enforcement_record ->> 'evidence_hash' = evidence_hash),
    CHECK (position('"human_confirmation_statement"' in lower(enforcement_record::text)) = 0),
    CHECK (position('"password"' in lower(enforcement_record::text)) = 0),
    CHECK (position('"raw_payload"' in lower(enforcement_record::text)) = 0)
);

COMMENT ON TABLE collabio.productivity_pilot_traffic_scope_enforcements IS
    'Append-only tenant and route scope enforcement. Default deny remains in force until separate pilot start authorization.';

ALTER TABLE collabio.productivity_pilot_traffic_scope_enforcements ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.productivity_pilot_traffic_scope_enforcements FORCE ROW LEVEL SECURITY;

CREATE POLICY productivity_pilot_traffic_scope_tenant_select
    ON collabio.productivity_pilot_traffic_scope_enforcements
    FOR SELECT USING (tenant_id = collabio.current_tenant_id());

CREATE POLICY productivity_pilot_traffic_scope_tenant_insert
    ON collabio.productivity_pilot_traffic_scope_enforcements
    FOR INSERT WITH CHECK (tenant_id = collabio.current_tenant_id());

CREATE POLICY productivity_pilot_traffic_scope_no_update
    ON collabio.productivity_pilot_traffic_scope_enforcements
    FOR UPDATE USING (false);

CREATE POLICY productivity_pilot_traffic_scope_no_hard_delete
    ON collabio.productivity_pilot_traffic_scope_enforcements
    FOR DELETE USING (false);

CREATE TRIGGER productivity_pilot_traffic_scope_append_only
BEFORE UPDATE OR DELETE ON collabio.productivity_pilot_traffic_scope_enforcements
FOR EACH ROW EXECUTE FUNCTION collabio.reject_productivity_pilot_evidence_mutation();

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_authz_admin') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.productivity_pilot_traffic_scope_enforcements TO collabio_authz_admin';
    END IF;
END
$$;
