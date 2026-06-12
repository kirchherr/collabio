-- 0016_crm_erp_schema_scaffold.sql
-- Persistent CRM/ERP schema scaffolding and tenant-scoped object-rule manifest tables.

CREATE SCHEMA IF NOT EXISTS crm_erp;
CREATE SCHEMA IF NOT EXISTS crm;
CREATE SCHEMA IF NOT EXISTS erp;
CREATE SCHEMA IF NOT EXISTS crm_erp_legacy;

CREATE TABLE IF NOT EXISTS crm_erp.schema_plans (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    module_id text NOT NULL DEFAULT 'crm_erp' CHECK (module_id = 'crm_erp'),
    schema_name text NOT NULL CHECK (schema_name IN ('crm_erp', 'crm', 'erp', 'crm_erp_legacy')),
    purpose text NOT NULL CHECK (
        purpose IN ('module_control', 'crm_domain', 'erp_domain', 'legacy_staging')
    ),
    manifest_hash text NOT NULL CHECK (manifest_hash ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    backup_domain_id text NOT NULL DEFAULT 'crm_erp_business_records'
        CHECK (backup_domain_id = 'crm_erp_business_records'),
    rls_required boolean NOT NULL DEFAULT true CHECK (rls_required),
    audit_required boolean NOT NULL DEFAULT true CHECK (audit_required),
    raw_legacy_payload_allowed boolean NOT NULL DEFAULT false CHECK (NOT raw_legacy_payload_allowed),
    captured_by text NOT NULL CHECK (captured_by <> ''),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    schema_version text NOT NULL DEFAULT 'crm_erp_schema_plan.v1',
    PRIMARY KEY (tenant_id, module_id, schema_name, manifest_hash),
    CHECK (
        (schema_name = 'crm_erp' AND purpose = 'module_control')
        OR (schema_name = 'crm' AND purpose = 'crm_domain')
        OR (schema_name = 'erp' AND purpose = 'erp_domain')
        OR (schema_name = 'crm_erp_legacy' AND purpose = 'legacy_staging')
    )
);

CREATE TABLE IF NOT EXISTS crm_erp.object_type_rules (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    module_id text NOT NULL DEFAULT 'crm_erp' CHECK (module_id = 'crm_erp'),
    object_type text NOT NULL CHECK (
        object_type IN (
            'crm.account',
            'crm.contact',
            'crm.activity',
            'crm.note',
            'erp.product',
            'erp.supplier',
            'erp.order',
            'erp.order_item',
            'erp.invoice',
            'erp.invoice_item',
            'erp.delivery_note',
            'erp.contract',
            'legacy.row'
        )
    ),
    schema_name text NOT NULL CHECK (schema_name IN ('crm', 'erp', 'crm_erp_legacy')),
    table_name text NOT NULL CHECK (table_name ~ '^[a-z][a-z0-9_]*$'),
    feature_id text NOT NULL CHECK (feature_id ~ '^crm_erp\.[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$'),
    classification text NOT NULL CHECK (
        classification IN ('internal', 'personal', 'confidential', 'gobd')
    ),
    retention_policy_id text NOT NULL CHECK (retention_policy_id ~ '^rp-[a-z0-9][a-z0-9_-]*$'),
    lifecycle_states text[] NOT NULL CHECK (array_length(lifecycle_states, 1) > 0),
    legal_hold_supported boolean NOT NULL DEFAULT true CHECK (legal_hold_supported),
    kms_key_ref_required boolean NOT NULL DEFAULT true CHECK (kms_key_ref_required),
    audit_required boolean NOT NULL DEFAULT true CHECK (audit_required),
    rls_required boolean NOT NULL DEFAULT true CHECK (rls_required),
    source_system_required boolean NOT NULL DEFAULT true CHECK (source_system_required),
    search_candidate_only boolean NOT NULL DEFAULT true CHECK (search_candidate_only),
    rag_indexing_default_enabled boolean NOT NULL DEFAULT false CHECK (NOT rag_indexing_default_enabled),
    source_resolver_required boolean NOT NULL DEFAULT true CHECK (source_resolver_required),
    raw_import_payload_allowed boolean NOT NULL DEFAULT false CHECK (NOT raw_import_payload_allowed),
    destructive_actions_require_approval boolean NOT NULL DEFAULT true CHECK (destructive_actions_require_approval),
    backup_domain_id text NOT NULL DEFAULT 'crm_erp_business_records'
        CHECK (backup_domain_id = 'crm_erp_business_records'),
    gobd_relevant boolean NOT NULL DEFAULT false,
    worm_candidate boolean NOT NULL DEFAULT false,
    required_metadata_fields text[] NOT NULL CHECK (
        required_metadata_fields @> ARRAY[
            'tenant_id',
            'object_id',
            'object_type',
            'owner_principal_id',
            'created_by',
            'created_at_utc',
            'updated_at_utc',
            'data_classification',
            'retention_policy_id',
            'legal_hold_state',
            'lifecycle_state',
            'kms_key_ref',
            'audit_chain_ref',
            'source_system',
            'schema_version'
        ]::text[]
    ),
    manifest_hash text NOT NULL CHECK (manifest_hash ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    captured_by text NOT NULL CHECK (captured_by <> ''),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    schema_version text NOT NULL DEFAULT 'crm_erp_object_type_rule.v1',
    PRIMARY KEY (tenant_id, object_type, manifest_hash),
    CHECK (
        (object_type LIKE 'crm.%' AND schema_name = 'crm')
        OR (object_type LIKE 'erp.%' AND schema_name = 'erp')
        OR (object_type = 'legacy.row' AND schema_name = 'crm_erp_legacy')
    ),
    CHECK (
        classification <> 'gobd'
        OR (
            retention_policy_id = 'rp-gobd-10y'
            AND gobd_relevant
            AND worm_candidate
            AND lifecycle_states @> ARRAY['record']::text[]
        )
    ),
    CHECK (
        object_type <> 'legacy.row'
        OR (
            classification = 'confidential'
            AND retention_policy_id = 'rp-restricted'
            AND lifecycle_states @> ARRAY['quarantined']::text[]
        )
    )
);

COMMENT ON SCHEMA crm_erp IS
    'CRM/ERP module control schema for manifests, mapping evidence, validation reports, and migration state.';
COMMENT ON SCHEMA crm IS
    'CRM domain schema. Business tables must follow crm_erp.object_type_rules before creation.';
COMMENT ON SCHEMA erp IS
    'ERP domain schema. Business tables must follow crm_erp.object_type_rules before creation.';
COMMENT ON SCHEMA crm_erp_legacy IS
    'CRM/ERP legacy staging schema. Raw legacy payload storage is not allowed by the initial scaffold.';
COMMENT ON TABLE crm_erp.schema_plans IS
    'Tenant-scoped CRM/ERP schema-plan snapshots captured from the object-rule manifest.';
COMMENT ON TABLE crm_erp.object_type_rules IS
    'Tenant-scoped CRM/ERP object-rule snapshots. Candidate-only search, RLS, KMS, audit, retention, and Legal Hold are mandatory.';

CREATE INDEX IF NOT EXISTS crm_erp_schema_plans_tenant_manifest_idx
    ON crm_erp.schema_plans (tenant_id, manifest_hash);

CREATE INDEX IF NOT EXISTS crm_erp_object_type_rules_tenant_schema_idx
    ON crm_erp.object_type_rules (tenant_id, schema_name, object_type);

CREATE INDEX IF NOT EXISTS crm_erp_object_type_rules_retention_idx
    ON crm_erp.object_type_rules (
        tenant_id,
        classification,
        retention_policy_id,
        legal_hold_supported,
        gobd_relevant
    );

ALTER TABLE crm_erp.schema_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE crm_erp.schema_plans FORCE ROW LEVEL SECURITY;
ALTER TABLE crm_erp.object_type_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE crm_erp.object_type_rules FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS crm_erp_schema_plans_tenant_select ON crm_erp.schema_plans;
CREATE POLICY crm_erp_schema_plans_tenant_select
    ON crm_erp.schema_plans
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS crm_erp_schema_plans_tenant_insert ON crm_erp.schema_plans;
CREATE POLICY crm_erp_schema_plans_tenant_insert
    ON crm_erp.schema_plans
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS crm_erp_schema_plans_no_update ON crm_erp.schema_plans;
CREATE POLICY crm_erp_schema_plans_no_update
    ON crm_erp.schema_plans
    FOR UPDATE
    USING (false);

DROP POLICY IF EXISTS crm_erp_schema_plans_no_hard_delete ON crm_erp.schema_plans;
CREATE POLICY crm_erp_schema_plans_no_hard_delete
    ON crm_erp.schema_plans
    FOR DELETE
    USING (false);

DROP POLICY IF EXISTS crm_erp_object_type_rules_tenant_select ON crm_erp.object_type_rules;
CREATE POLICY crm_erp_object_type_rules_tenant_select
    ON crm_erp.object_type_rules
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS crm_erp_object_type_rules_tenant_insert ON crm_erp.object_type_rules;
CREATE POLICY crm_erp_object_type_rules_tenant_insert
    ON crm_erp.object_type_rules
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS crm_erp_object_type_rules_no_update ON crm_erp.object_type_rules;
CREATE POLICY crm_erp_object_type_rules_no_update
    ON crm_erp.object_type_rules
    FOR UPDATE
    USING (false);

DROP POLICY IF EXISTS crm_erp_object_type_rules_no_hard_delete ON crm_erp.object_type_rules;
CREATE POLICY crm_erp_object_type_rules_no_hard_delete
    ON crm_erp.object_type_rules
    FOR DELETE
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA crm_erp, crm, erp, crm_erp_legacy TO collabio_app';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE crm_erp.schema_plans TO collabio_app';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE crm_erp.object_type_rules TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA crm_erp, crm, erp, crm_erp_legacy TO collabio_worker';
        EXECUTE 'GRANT SELECT ON TABLE crm_erp.schema_plans TO collabio_worker';
        EXECUTE 'GRANT SELECT ON TABLE crm_erp.object_type_rules TO collabio_worker';
    END IF;
END
$$;
