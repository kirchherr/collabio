-- 0075_audit_worm_snapshots_v2.sql
-- Asymmetric KMS-signed audit checkpoints and verified immutable object-version receipts.

CREATE TABLE IF NOT EXISTS collabio.audit_snapshot_checkpoints_v2 (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    checkpoint_id text NOT NULL CHECK (checkpoint_id <> ''),
    through_sequence_number bigint NOT NULL CHECK (through_sequence_number >= 1),
    event_count bigint NOT NULL CHECK (event_count = through_sequence_number),
    first_event_hash text NOT NULL CHECK (first_event_hash ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    last_event_hash text NOT NULL CHECK (last_event_hash ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    events_hash text NOT NULL CHECK (events_hash ~ '^sha256:[a-f0-9]{64}$'),
    manifest_hash text NOT NULL CHECK (manifest_hash ~ '^sha256:[a-f0-9]{64}$'),
    signature_algorithm text NOT NULL CHECK (
        signature_algorithm IN ('ecdsa-sha256', 'rsassa-pss-sha256')
    ),
    signing_message_type text NOT NULL DEFAULT 'DIGEST' CHECK (signing_message_type = 'DIGEST'),
    signature_key_ref text NOT NULL CHECK (signature_key_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    signature_key_version integer NOT NULL CHECK (signature_key_version >= 1),
    provider_profile text NOT NULL CHECK (provider_profile <> ''),
    provider_key_id text NOT NULL CHECK (provider_key_id <> ''),
    public_key_sha256 text NOT NULL CHECK (public_key_sha256 ~ '^sha256:[a-f0-9]{64}$'),
    signature bytea NOT NULL CHECK (octet_length(signature) > 0),
    signature_sha256 text NOT NULL CHECK (signature_sha256 ~ '^sha256:[a-f0-9]{64}$'),
    provider_sign_request_id text NOT NULL CHECK (provider_sign_request_id <> ''),
    provider_verify_request_id text NOT NULL CHECK (provider_verify_request_id <> ''),
    provider_verified boolean NOT NULL CHECK (provider_verified),
    signed_at_utc timestamptz NOT NULL,
    created_by text NOT NULL CHECK (created_by <> ''),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    schema_version text NOT NULL DEFAULT 'audit_snapshot_checkpoint.v2' CHECK (
        schema_version = 'audit_snapshot_checkpoint.v2'
    ),
    PRIMARY KEY (tenant_id, checkpoint_id),
    UNIQUE (tenant_id, through_sequence_number),
    UNIQUE (tenant_id, manifest_hash),
    UNIQUE (tenant_id, signature_sha256)
);

CREATE TABLE IF NOT EXISTS collabio.audit_worm_snapshot_receipts_v2 (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    export_id text NOT NULL CHECK (export_id <> ''),
    checkpoint_id text NOT NULL CHECK (checkpoint_id <> ''),
    bundle_hash text NOT NULL CHECK (bundle_hash ~ '^sha256:[a-f0-9]{64}$'),
    storage_provider text NOT NULL CHECK (storage_provider <> ''),
    bucket_id text NOT NULL CHECK (bucket_id <> ''),
    object_key text NOT NULL CHECK (object_key <> ''),
    object_version_id text NOT NULL CHECK (object_version_id <> ''),
    storage_uri text NOT NULL CHECK (storage_uri <> ''),
    object_lock_mode text NOT NULL CHECK (object_lock_mode = 'compliance'),
    object_lock_retain_until_utc timestamptz NOT NULL,
    legal_hold_enabled boolean NOT NULL DEFAULT false,
    server_side_encryption text NOT NULL CHECK (server_side_encryption = 'aws:kms'),
    storage_kms_key_ref text NOT NULL CHECK (storage_kms_key_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    provider_storage_key_id text NOT NULL CHECK (provider_storage_key_id <> ''),
    put_request_id text NOT NULL CHECK (put_request_id <> ''),
    get_request_id text NOT NULL CHECK (get_request_id <> ''),
    head_request_id text NOT NULL CHECK (head_request_id <> ''),
    readback_verified boolean NOT NULL CHECK (readback_verified),
    object_lock_verified boolean NOT NULL CHECK (object_lock_verified),
    encryption_verified boolean NOT NULL CHECK (encryption_verified),
    created_by text NOT NULL CHECK (created_by <> ''),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    schema_version text NOT NULL DEFAULT 'audit_worm_snapshot_receipt.v2' CHECK (
        schema_version = 'audit_worm_snapshot_receipt.v2'
    ),
    PRIMARY KEY (tenant_id, export_id),
    UNIQUE (tenant_id, checkpoint_id),
    UNIQUE (tenant_id, bucket_id, object_key, object_version_id),
    FOREIGN KEY (tenant_id, checkpoint_id)
        REFERENCES collabio.audit_snapshot_checkpoints_v2 (tenant_id, checkpoint_id)
);

COMMENT ON TABLE collabio.audit_snapshot_checkpoints_v2 IS
    'Append-only asymmetric KMS signature evidence. Private key material and audit event bodies are forbidden.';
COMMENT ON TABLE collabio.audit_worm_snapshot_receipts_v2 IS
    'Append-only exact-version WORM receipts recorded only after readback, Object Lock and KMS encryption checks.';

CREATE INDEX IF NOT EXISTS audit_snapshot_checkpoints_v2_tenant_sequence_idx
    ON collabio.audit_snapshot_checkpoints_v2 (tenant_id, through_sequence_number);
CREATE INDEX IF NOT EXISTS audit_worm_snapshot_receipts_v2_tenant_checkpoint_idx
    ON collabio.audit_worm_snapshot_receipts_v2 (tenant_id, checkpoint_id);

ALTER TABLE collabio.audit_snapshot_checkpoints_v2 ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.audit_snapshot_checkpoints_v2 FORCE ROW LEVEL SECURITY;
ALTER TABLE collabio.audit_worm_snapshot_receipts_v2 ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.audit_worm_snapshot_receipts_v2 FORCE ROW LEVEL SECURITY;

CREATE POLICY audit_snapshot_checkpoints_v2_tenant_select
    ON collabio.audit_snapshot_checkpoints_v2
    FOR SELECT TO collabio_audit_writer
    USING (tenant_id = collabio.current_tenant_id());

CREATE POLICY audit_snapshot_checkpoints_v2_tenant_insert
    ON collabio.audit_snapshot_checkpoints_v2
    FOR INSERT TO collabio_audit_writer
    WITH CHECK (tenant_id = collabio.current_tenant_id());

CREATE POLICY audit_snapshot_checkpoints_v2_no_update
    ON collabio.audit_snapshot_checkpoints_v2
    FOR UPDATE TO collabio_audit_writer
    USING (false) WITH CHECK (false);

CREATE POLICY audit_snapshot_checkpoints_v2_no_hard_delete
    ON collabio.audit_snapshot_checkpoints_v2
    FOR DELETE TO collabio_audit_writer
    USING (false);

CREATE POLICY audit_worm_snapshot_receipts_v2_tenant_select
    ON collabio.audit_worm_snapshot_receipts_v2
    FOR SELECT TO collabio_audit_writer
    USING (tenant_id = collabio.current_tenant_id());

CREATE POLICY audit_worm_snapshot_receipts_v2_tenant_insert
    ON collabio.audit_worm_snapshot_receipts_v2
    FOR INSERT TO collabio_audit_writer
    WITH CHECK (tenant_id = collabio.current_tenant_id());

CREATE POLICY audit_worm_snapshot_receipts_v2_no_update
    ON collabio.audit_worm_snapshot_receipts_v2
    FOR UPDATE TO collabio_audit_writer
    USING (false) WITH CHECK (false);

CREATE POLICY audit_worm_snapshot_receipts_v2_no_hard_delete
    ON collabio.audit_worm_snapshot_receipts_v2
    FOR DELETE TO collabio_audit_writer
    USING (false);

CREATE OR REPLACE FUNCTION collabio.reject_audit_worm_snapshot_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'audit WORM snapshot evidence is append-only';
END;
$$;

CREATE TRIGGER audit_snapshot_checkpoints_v2_append_only
BEFORE UPDATE OR DELETE ON collabio.audit_snapshot_checkpoints_v2
FOR EACH ROW EXECUTE FUNCTION collabio.reject_audit_worm_snapshot_mutation();

CREATE TRIGGER audit_worm_snapshot_receipts_v2_append_only
BEFORE UPDATE OR DELETE ON collabio.audit_worm_snapshot_receipts_v2
FOR EACH ROW EXECUTE FUNCTION collabio.reject_audit_worm_snapshot_mutation();

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_audit_writer') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.audit_snapshot_checkpoints_v2 TO collabio_audit_writer';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.audit_worm_snapshot_receipts_v2 TO collabio_audit_writer';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'REVOKE ALL ON TABLE collabio.audit_snapshot_checkpoints_v2 FROM collabio_app';
        EXECUTE 'REVOKE ALL ON TABLE collabio.audit_worm_snapshot_receipts_v2 FROM collabio_app';
    END IF;
END
$$;
