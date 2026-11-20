-- 0054_tickets_incidents_controlled_pilot.sql
-- Append-only pilot evidence plus one tightly scoped, approval-bound catalog transition.

CREATE TABLE IF NOT EXISTS tickets.controlled_pilot_receipts (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    module_id text NOT NULL DEFAULT 'tickets_incidents' CHECK (module_id = 'tickets_incidents'),
    receipt_type text NOT NULL CHECK (
        receipt_type IN ('admission', 'enablement_authorization', 'enablement_completed')
    ),
    approval_boundary_evidence_hash text NOT NULL CHECK (
        approval_boundary_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    approval_record_evidence_hash text NOT NULL CHECK (
        approval_record_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    tickets_restore_drill_evidence_hash text NOT NULL CHECK (
        tickets_restore_drill_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    command_hash text NOT NULL CHECK (command_hash ~ '^sha256:[a-f0-9]{64}$'),
    idempotency_key_hash text NOT NULL CHECK (idempotency_key_hash ~ '^sha256:[a-f0-9]{64}$'),
    policy_snapshot_hash text NOT NULL CHECK (policy_snapshot_hash ~ '^sha256:[a-f0-9]{64}$'),
    feature_manifest_hash text NOT NULL CHECK (feature_manifest_hash ~ '^sha256:[a-f0-9]{64}$'),
    module_status text NOT NULL CHECK (module_status IN ('disabled', 'enabled')),
    enabled_features jsonb NOT NULL CHECK (jsonb_typeof(enabled_features) = 'object'),
    changed_by text NOT NULL CHECK (changed_by <> ''),
    changed_at_utc timestamptz NOT NULL,
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    receipt jsonb NOT NULL CHECK (
        jsonb_typeof(receipt) = 'object'
        AND receipt ->> 'schema_version' = 'tickets_incidents_controlled_pilot_receipt.v1'
        AND NOT (receipt ? 'human_confirmation_statement')
        AND NOT (receipt ? 'ticket_content')
        AND NOT (receipt ? 'raw_payload')
    ),
    evidence_hash text NOT NULL CHECK (evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    schema_version text NOT NULL DEFAULT 'tickets_incidents_controlled_pilot_receipt.v1' CHECK (
        schema_version = 'tickets_incidents_controlled_pilot_receipt.v1'
    ),
    PRIMARY KEY (tenant_id, evidence_hash),
    UNIQUE (tenant_id, receipt_type, idempotency_key_hash),
    CHECK ((receipt ->> 'tenant_id') = tenant_id),
    CHECK ((receipt ->> 'module_id') = module_id),
    CHECK ((receipt ->> 'receipt_type') = receipt_type),
    CHECK ((receipt ->> 'evidence_hash') = evidence_hash),
    CHECK (position('"human_confirmation_statement"' in lower(receipt::text)) = 0),
    CHECK (position('"ticket_content"' in lower(receipt::text)) = 0),
    CHECK (position('"password"' in lower(receipt::text)) = 0)
);

COMMENT ON TABLE tickets.controlled_pilot_receipts IS
    'Append-only admission and enablement evidence for the controlled Tickets pilot. Metadata only.';

ALTER TABLE tickets.controlled_pilot_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE tickets.controlled_pilot_receipts FORCE ROW LEVEL SECURITY;

CREATE POLICY tickets_controlled_pilot_receipts_tenant_select
    ON tickets.controlled_pilot_receipts
    FOR SELECT USING (tenant_id = collabio.current_tenant_id());

CREATE POLICY tickets_controlled_pilot_receipts_tenant_insert
    ON tickets.controlled_pilot_receipts
    FOR INSERT WITH CHECK (tenant_id = collabio.current_tenant_id());

CREATE POLICY tickets_controlled_pilot_receipts_no_update
    ON tickets.controlled_pilot_receipts
    FOR UPDATE USING (false);

CREATE POLICY tickets_controlled_pilot_receipts_no_hard_delete
    ON tickets.controlled_pilot_receipts
    FOR DELETE USING (false);

CREATE OR REPLACE FUNCTION collabio.install_tickets_incidents_catalog_for_pilot(
    p_tenant_id text,
    p_approval_record_hash text,
    p_expected_manifest_hash text,
    p_installed_at_utc timestamptz
) RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, collabio, tickets
AS $$
DECLARE
    v_status text;
    v_manifest_hash text;
BEGIN
    IF p_tenant_id IS NULL OR p_tenant_id = '' OR p_tenant_id <> current_setting('app.tenant_id', true) THEN
        RAISE EXCEPTION 'tenant context does not match controlled pilot request';
    END IF;
    IF p_approval_record_hash !~ '^sha256:[a-f0-9]{64}$' THEN
        RAISE EXCEPTION 'valid approval record hash required';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM tickets.activation_dry_run_execution_approval_records
        WHERE tenant_id = p_tenant_id
          AND evidence_hash = p_approval_record_hash
          AND (approval_record ->> 'explicit_human_execution_approval_present')::boolean = true
    ) THEN
        RAISE EXCEPTION 'persisted explicit Tickets pilot approval not found';
    END IF;

    SELECT status, manifest_hash
    INTO v_status, v_manifest_hash
    FROM collabio.module_catalog
    WHERE module_id = 'tickets_incidents'
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Tickets module catalog entry not found';
    END IF;
    IF v_manifest_hash <> p_expected_manifest_hash THEN
        RAISE EXCEPTION 'Tickets module manifest hash mismatch';
    END IF;
    IF v_status NOT IN ('not_installed', 'installed') THEN
        RAISE EXCEPTION 'Tickets module catalog transition is not allowed from %', v_status;
    END IF;

    IF v_status = 'not_installed' THEN
        UPDATE collabio.module_catalog
        SET status = 'installed', installed_at_utc = p_installed_at_utc
        WHERE module_id = 'tickets_incidents';
        v_status := 'installed';
    END IF;
    RETURN v_status;
END;
$$;

REVOKE ALL ON FUNCTION collabio.install_tickets_incidents_catalog_for_pilot(text, text, text, timestamptz)
    FROM PUBLIC;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE tickets.controlled_pilot_receipts TO collabio_app';
        EXECUTE 'GRANT EXECUTE ON FUNCTION collabio.install_tickets_incidents_catalog_for_pilot(text, text, text, timestamptz) TO collabio_app';
    END IF;
END
$$;

UPDATE collabio.module_catalog
SET required_migration_versions = '["0051", "0052", "0053", "0054"]'::jsonb
WHERE module_id = 'tickets_incidents';
