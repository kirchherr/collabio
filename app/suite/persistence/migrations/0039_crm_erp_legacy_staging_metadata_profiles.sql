-- 0039_crm_erp_legacy_staging_metadata_profiles.sql
-- Tenant-scoped metadata contract profiles for future CRM/ERP Legacy SQL staging rows.
-- This migration does not allow raw legacy rows, import writes, or destructive actions.

CREATE TABLE IF NOT EXISTS crm_erp_legacy.staging_metadata_profiles (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    module_id text NOT NULL DEFAULT 'crm_erp' CHECK (module_id = 'crm_erp'),
    object_id text NOT NULL CHECK (object_id <> ''),
    object_type text NOT NULL DEFAULT 'legacy.sql_staging_metadata_profile' CHECK (
        object_type = 'legacy.sql_staging_metadata_profile'
    ),
    owner_principal_id text NOT NULL CHECK (owner_principal_id <> ''),
    created_by text NOT NULL CHECK (created_by <> ''),
    created_at_utc timestamptz NOT NULL,
    updated_at_utc timestamptz NOT NULL,
    classification text NOT NULL CHECK (
        classification IN ('internal', 'personal', 'confidential', 'gobd')
    ),
    retention_policy_id text NOT NULL CHECK (retention_policy_id ~ '^rp-[a-z0-9][a-z0-9_-]*$'),
    legal_hold_state text NOT NULL DEFAULT 'none' CHECK (legal_hold_state <> ''),
    lifecycle_state text NOT NULL DEFAULT 'staged' CHECK (
        lifecycle_state IN ('staged', 'quarantined', 'deferred')
    ),
    kms_key_ref text NOT NULL CHECK (kms_key_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    source_system text NOT NULL DEFAULT 'legacy_sql' CHECK (source_system = 'legacy_sql'),
    source_system_ref text NOT NULL CHECK (source_system_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    source_table_ref text NOT NULL CHECK (
        source_table_ref ~ '^[A-Za-z_][A-Za-z0-9_@$#-]*\.[A-Za-z_][A-Za-z0-9_@$#-]*$'
    ),
    target_object_type text NOT NULL CHECK (
        target_object_type ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$'
    ),
    target_schema_version text NOT NULL CHECK (target_schema_version <> ''),
    feature_id text NOT NULL CHECK (feature_id ~ '^crm_erp\.[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$'),
    row_object_id_template text NOT NULL CHECK (
        row_object_id_template LIKE '%{source_row_hash}%'
    ),
    metadata_contract text NOT NULL DEFAULT 'persistent_object_metadata.v1' CHECK (
        metadata_contract = 'persistent_object_metadata.v1'
    ),
    required_metadata_fields text[] NOT NULL CHECK (
        required_metadata_fields @> ARRAY[
            'tenant_id',
            'object_id',
            'object_type',
            'owner_principal_id',
            'created_by',
            'created_at_utc',
            'updated_at_utc',
            'classification',
            'retention_policy_id',
            'legal_hold_state',
            'lifecycle_state',
            'kms_key_ref',
            'audit_chain_ref',
            'source_system',
            'schema_version'
        ]::text[]
    ),
    metadata_field_sources jsonb NOT NULL CHECK (
        jsonb_typeof(metadata_field_sources) = 'object'
        AND metadata_field_sources ?& ARRAY[
            'tenant_id',
            'object_id',
            'object_type',
            'owner_principal_id',
            'created_by',
            'created_at_utc',
            'updated_at_utc',
            'classification',
            'retention_policy_id',
            'legal_hold_state',
            'lifecycle_state',
            'kms_key_ref',
            'audit_chain_ref',
            'source_system',
            'schema_version'
        ]
    ),
    discovery_manifest_hash text NOT NULL CHECK (discovery_manifest_hash ~ '^sha256:[a-f0-9]{64}$'),
    mapping_manifest_hash text NOT NULL CHECK (mapping_manifest_hash ~ '^sha256:[a-f0-9]{64}$'),
    plan_manifest_hash text NOT NULL CHECK (plan_manifest_hash ~ '^sha256:[a-f0-9]{64}$'),
    quarantine_required boolean NOT NULL,
    dry_run_required boolean NOT NULL DEFAULT true CHECK (dry_run_required),
    import_write_allowed boolean NOT NULL DEFAULT false CHECK (import_write_allowed = false),
    raw_data_import_allowed boolean NOT NULL DEFAULT false CHECK (raw_data_import_allowed = false),
    destructive_actions_allowed boolean NOT NULL DEFAULT false CHECK (destructive_actions_allowed = false),
    schema_version text NOT NULL DEFAULT 'crm_erp_legacy_staging_metadata_profile.v1' CHECK (
        schema_version = 'crm_erp_legacy_staging_metadata_profile.v1'
    ),
    PRIMARY KEY (tenant_id, object_id),
    UNIQUE (tenant_id, source_system_ref, source_table_ref, mapping_manifest_hash),
    CHECK (updated_at_utc >= created_at_utc)
);

COMMENT ON TABLE crm_erp_legacy.staging_metadata_profiles IS
    'Tenant-scoped persistent metadata contract profiles for future Legacy SQL staging rows. Raw legacy rows, sample values, cell values, DSNs, Secret references, prompts, outputs, and import payloads are excluded.';

COMMENT ON COLUMN crm_erp_legacy.staging_metadata_profiles.metadata_field_sources IS
    'Maps persistent_object_metadata.v1 required fields to approved metadata-only sources before row materialization.';

CREATE INDEX IF NOT EXISTS crm_erp_legacy_staging_metadata_profiles_source_idx
    ON crm_erp_legacy.staging_metadata_profiles (
        tenant_id,
        source_system_ref,
        source_table_ref
    );

CREATE INDEX IF NOT EXISTS crm_erp_legacy_staging_metadata_profiles_target_idx
    ON crm_erp_legacy.staging_metadata_profiles (
        tenant_id,
        target_object_type,
        classification,
        retention_policy_id
    );

CREATE INDEX IF NOT EXISTS crm_erp_legacy_staging_metadata_profiles_plan_idx
    ON crm_erp_legacy.staging_metadata_profiles (
        tenant_id,
        plan_manifest_hash,
        mapping_manifest_hash
    );

ALTER TABLE crm_erp_legacy.staging_metadata_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE crm_erp_legacy.staging_metadata_profiles FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS crm_erp_legacy_staging_metadata_profiles_tenant_select
    ON crm_erp_legacy.staging_metadata_profiles;
CREATE POLICY crm_erp_legacy_staging_metadata_profiles_tenant_select
    ON crm_erp_legacy.staging_metadata_profiles
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS crm_erp_legacy_staging_metadata_profiles_tenant_insert
    ON crm_erp_legacy.staging_metadata_profiles;
CREATE POLICY crm_erp_legacy_staging_metadata_profiles_tenant_insert
    ON crm_erp_legacy.staging_metadata_profiles
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS crm_erp_legacy_staging_metadata_profiles_no_update
    ON crm_erp_legacy.staging_metadata_profiles;
CREATE POLICY crm_erp_legacy_staging_metadata_profiles_no_update
    ON crm_erp_legacy.staging_metadata_profiles
    FOR UPDATE
    USING (false);

DROP POLICY IF EXISTS crm_erp_legacy_staging_metadata_profiles_no_hard_delete
    ON crm_erp_legacy.staging_metadata_profiles;
CREATE POLICY crm_erp_legacy_staging_metadata_profiles_no_hard_delete
    ON crm_erp_legacy.staging_metadata_profiles
    FOR DELETE
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE crm_erp_legacy.staging_metadata_profiles TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE crm_erp_legacy.staging_metadata_profiles TO collabio_worker';
    END IF;
END
$$;

UPDATE collabio.module_catalog
SET required_migration_versions = '["0007", "0008", "0009", "0010", "0011", "0016", "0017", "0018", "0019", "0020", "0034", "0035", "0036", "0037", "0038", "0039"]'::jsonb
WHERE module_id = 'crm_erp';
