-- Short-lived tenant-scoped advisory edit leases for native Office documents.
-- They coordinate editors but never replace ACL checks or optimistic version CAS.
UPDATE collabio.module_catalog
SET module_version = '0.8.0',
    required_migration_versions = '["0083", "0084", "0085", "0086", "0087", "0088", "0089", "0090"]'::jsonb
WHERE module_id = 'office_documents';

CREATE TABLE office.document_edit_leases (
    tenant_id text NOT NULL,
    object_id text NOT NULL,
    lease_revision integer NOT NULL CHECK (lease_revision >= 1),
    holder_principal_id text NOT NULL CHECK (holder_principal_id <> ''),
    holder_session_hash text NOT NULL CHECK (holder_session_hash ~ '^sha256:[a-f0-9]{64}$'),
    base_version_id text NOT NULL,
    acquired_at_utc timestamptz NOT NULL,
    renewed_at_utc timestamptz NOT NULL,
    expires_at_utc timestamptz NOT NULL,
    released_at_utc timestamptz,
    takeover_count integer NOT NULL DEFAULT 0 CHECK (takeover_count >= 0),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref LIKE 'audit:%'),
    PRIMARY KEY (tenant_id, object_id),
    FOREIGN KEY (tenant_id, object_id) REFERENCES office.documents (tenant_id, object_id),
    FOREIGN KEY (tenant_id, object_id, base_version_id)
        REFERENCES office.document_versions (tenant_id, object_id, version_id),
    CHECK (renewed_at_utc >= acquired_at_utc),
    CHECK (expires_at_utc > renewed_at_utc),
    CHECK (released_at_utc IS NULL OR released_at_utc >= renewed_at_utc)
);

ALTER TABLE office.document_edit_leases ENABLE ROW LEVEL SECURITY;
ALTER TABLE office.document_edit_leases FORCE ROW LEVEL SECURITY;

CREATE POLICY office_document_edit_leases_tenant_select ON office.document_edit_leases FOR SELECT
USING (tenant_id = collabio.current_tenant_id());
CREATE POLICY office_document_edit_leases_tenant_insert ON office.document_edit_leases FOR INSERT
WITH CHECK (tenant_id = collabio.current_tenant_id());
CREATE POLICY office_document_edit_leases_tenant_update ON office.document_edit_leases FOR UPDATE
USING (tenant_id = collabio.current_tenant_id()) WITH CHECK (tenant_id = collabio.current_tenant_id());
CREATE POLICY office_document_edit_leases_no_delete ON office.document_edit_leases FOR DELETE USING (false);

CREATE INDEX office_document_edit_leases_expiry_idx
ON office.document_edit_leases (tenant_id, expires_at_utc);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        GRANT SELECT, INSERT ON office.document_edit_leases TO collabio_app;
        GRANT UPDATE (
            lease_revision, holder_principal_id, holder_session_hash, base_version_id,
            acquired_at_utc, renewed_at_utc, expires_at_utc, released_at_utc,
            takeover_count, audit_chain_ref
        ) ON office.document_edit_leases TO collabio_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        GRANT SELECT ON office.document_edit_leases TO collabio_worker;
    END IF;
END
$$;
