-- 0076_mvp_pilot_decision_records.sql
-- Tenant-scoped append-only human MVP pilot decisions. This table never starts a pilot.

CREATE TABLE IF NOT EXISTS collabio.mvp_pilot_decision_records (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    decision_id text NOT NULL CHECK (decision_id ~ '^[a-z0-9][a-z0-9_.-]{0,127}$'),
    decision_context_hash text NOT NULL CHECK (decision_context_hash ~ '^sha256:[a-f0-9]{64}$'),
    go_no_go_decision text NOT NULL CHECK (go_no_go_decision IN ('go', 'no_go', 'defer')),
    decision_reason_hash text NOT NULL CHECK (decision_reason_hash ~ '^sha256:[a-f0-9]{64}$'),
    command_hash text NOT NULL CHECK (command_hash ~ '^sha256:[a-f0-9]{64}$'),
    idempotency_key_hash text NOT NULL CHECK (idempotency_key_hash ~ '^sha256:[a-f0-9]{64}$'),
    human_confirmation_statement_hash text NOT NULL CHECK (
        human_confirmation_statement_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    human_confirmation_reference text NOT NULL CHECK (
        human_confirmation_reference ~ '^[a-z0-9][a-z0-9_+.-]*:.+'
    ),
    change_request_ref text NOT NULL CHECK (change_request_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    decided_by text NOT NULL CHECK (decided_by <> ''),
    decided_at timestamptz NOT NULL,
    confirmation_role_ids jsonb NOT NULL CHECK (
        jsonb_typeof(confirmation_role_ids) = 'array'
        AND jsonb_array_length(confirmation_role_ids) > 0
    ),
    audit_event_id text NOT NULL CHECK (audit_event_id <> ''),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^audit:.+'),
    decision_record jsonb NOT NULL CHECK (
        jsonb_typeof(decision_record) = 'object'
        AND decision_record ->> 'schema_version' = 'mvp_pilot_decision_record.v1'
        AND decision_record ->> 'tenant_id' = tenant_id
        AND decision_record ->> 'decision_id' = decision_id
        AND decision_record ->> 'decision_context_hash' = decision_context_hash
        AND decision_record ->> 'go_no_go_decision' = go_no_go_decision
        AND (decision_record ->> 'decision_record_created')::boolean = true
        AND (decision_record ->> 'human_confirmation_captured')::boolean = true
        AND (decision_record ->> 'pilot_admission_allowed')::boolean = false
        AND (decision_record ->> 'pilot_start_allowed')::boolean = false
        AND (decision_record ->> 'module_activation_executed')::boolean = false
        AND (decision_record ->> 'traffic_authorized')::boolean = false
        AND (decision_record ->> 'business_write_executed')::boolean = false
        AND (decision_record ->> 'destructive_action_executed')::boolean = false
        AND (decision_record ->> 'external_side_effect_executed')::boolean = false
        AND (decision_record ->> 'content_included')::boolean = false
        AND NOT (decision_record ? 'decision_reason')
        AND NOT (decision_record ? 'human_confirmation_statement')
        AND NOT (decision_record ? 'idempotency_key')
    ),
    evidence_hash text NOT NULL CHECK (evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    schema_version text NOT NULL DEFAULT 'mvp_pilot_decision_record.v1' CHECK (
        schema_version = 'mvp_pilot_decision_record.v1'
    ),
    PRIMARY KEY (tenant_id, decision_id),
    UNIQUE (tenant_id, idempotency_key_hash),
    CHECK (decision_record ->> 'evidence_hash' = evidence_hash),
    CHECK (decision_record ->> 'decision_reason_hash' = decision_reason_hash),
    CHECK (decision_record ->> 'human_confirmation_statement_hash' = human_confirmation_statement_hash),
    CHECK (position('"decision_reason"' in lower(decision_record::text)) = 0),
    CHECK (position('"human_confirmation_statement"' in lower(decision_record::text)) = 0),
    CHECK (position('"password"' in lower(decision_record::text)) = 0),
    CHECK (position('"raw_payload"' in lower(decision_record::text)) = 0)
);

COMMENT ON TABLE collabio.mvp_pilot_decision_records IS
    'Append-only tenant-scoped human MVP pilot decision metadata. No admission, activation, traffic authorization, pilot start, content, destructive action or external side effect.';

ALTER TABLE collabio.mvp_pilot_decision_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.mvp_pilot_decision_records FORCE ROW LEVEL SECURITY;

CREATE POLICY mvp_pilot_decision_records_tenant_select
    ON collabio.mvp_pilot_decision_records
    FOR SELECT USING (tenant_id = collabio.current_tenant_id());

CREATE POLICY mvp_pilot_decision_records_tenant_insert
    ON collabio.mvp_pilot_decision_records
    FOR INSERT WITH CHECK (tenant_id = collabio.current_tenant_id());

CREATE POLICY mvp_pilot_decision_records_no_update
    ON collabio.mvp_pilot_decision_records
    FOR UPDATE USING (false);

CREATE POLICY mvp_pilot_decision_records_no_hard_delete
    ON collabio.mvp_pilot_decision_records
    FOR DELETE USING (false);

CREATE OR REPLACE FUNCTION collabio.reject_mvp_pilot_decision_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'MVP pilot decision records are append-only';
END;
$$;

CREATE TRIGGER mvp_pilot_decision_records_append_only
BEFORE UPDATE OR DELETE ON collabio.mvp_pilot_decision_records
FOR EACH ROW EXECUTE FUNCTION collabio.reject_mvp_pilot_decision_mutation();

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_authz_admin') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.mvp_pilot_decision_records TO collabio_authz_admin';
    END IF;
END
$$;
