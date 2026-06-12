-- 0020_erp_products.sql
-- Minimal ERP product catalog table for the gated crm_erp.erp.products architecture proof.

CREATE TABLE IF NOT EXISTS erp.products (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    object_id text NOT NULL CHECK (object_id <> ''),
    object_type text NOT NULL DEFAULT 'erp.product' CHECK (object_type = 'erp.product'),
    owner_principal_id text NOT NULL CHECK (owner_principal_id <> ''),
    created_by text NOT NULL CHECK (created_by <> ''),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    updated_at_utc timestamptz NOT NULL DEFAULT now(),
    data_classification text NOT NULL DEFAULT 'internal' CHECK (data_classification = 'internal'),
    retention_policy_id text NOT NULL DEFAULT 'rp-standard' CHECK (retention_policy_id = 'rp-standard'),
    legal_hold_state text NOT NULL DEFAULT 'none' CHECK (legal_hold_state IN ('none', 'active')),
    lifecycle_state text NOT NULL DEFAULT 'active' CHECK (
        lifecycle_state IN ('working', 'active', 'restricted', 'disposition_pending')
    ),
    kms_key_ref text NOT NULL CHECK (kms_key_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    source_system text NOT NULL CHECK (source_system ~ '^[a-z][a-z0-9_+.-]*$'),
    schema_version text NOT NULL DEFAULT 'erp_product.v1' CHECK (schema_version = 'erp_product.v1'),
    product_number text NOT NULL CHECK (product_number <> ''),
    display_name text NOT NULL CHECK (display_name <> ''),
    product_kind text NOT NULL DEFAULT 'good' CHECK (product_kind IN ('good', 'service', 'bundle')),
    unit_code text NOT NULL DEFAULT 'pcs' CHECK (unit_code <> ''),
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'restricted', 'archived')),
    PRIMARY KEY (tenant_id, object_id),
    CHECK (status <> 'restricted' OR lifecycle_state = 'restricted')
);

COMMENT ON TABLE erp.products IS
    'Tenant-scoped ERP product catalog records for crm_erp.erp.products. This slice proves internal master-data handling.';
COMMENT ON COLUMN erp.products.data_classification IS
    'ERP products start as internal data, unlike the personal CRM slices.';
COMMENT ON COLUMN erp.products.retention_policy_id IS
    'Retention policy reference. Initial ERP product records use rp-standard.';
COMMENT ON COLUMN erp.products.legal_hold_state IS
    'Legal Hold state blocks destructive lifecycle transitions outside approved compliance workflows.';

CREATE UNIQUE INDEX IF NOT EXISTS erp_products_product_number_unique_idx
    ON erp.products (tenant_id, product_number);

CREATE INDEX IF NOT EXISTS erp_products_tenant_status_idx
    ON erp.products (tenant_id, status, lifecycle_state);

CREATE INDEX IF NOT EXISTS erp_products_retention_legal_hold_idx
    ON erp.products (tenant_id, retention_policy_id, legal_hold_state, lifecycle_state);

CREATE OR REPLACE FUNCTION erp.touch_updated_at_utc()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at_utc = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS erp_products_touch_updated_at_utc ON erp.products;
CREATE TRIGGER erp_products_touch_updated_at_utc
    BEFORE UPDATE ON erp.products
    FOR EACH ROW
    EXECUTE FUNCTION erp.touch_updated_at_utc();

ALTER TABLE erp.products ENABLE ROW LEVEL SECURITY;
ALTER TABLE erp.products FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS erp_products_tenant_select ON erp.products;
CREATE POLICY erp_products_tenant_select
    ON erp.products
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS erp_products_tenant_insert ON erp.products;
CREATE POLICY erp_products_tenant_insert
    ON erp.products
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS erp_products_tenant_update ON erp.products;
CREATE POLICY erp_products_tenant_update
    ON erp.products
    FOR UPDATE
    USING (tenant_id = collabio.current_tenant_id())
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS erp_products_no_hard_delete ON erp.products;
CREATE POLICY erp_products_no_hard_delete
    ON erp.products
    FOR DELETE
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA erp TO collabio_app';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE erp.products TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA erp TO collabio_worker';
        EXECUTE 'GRANT SELECT ON TABLE erp.products TO collabio_worker';
    END IF;
END
$$;
