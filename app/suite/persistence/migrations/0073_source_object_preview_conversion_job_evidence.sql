-- 0073_source_object_preview_conversion_job_evidence.sql
-- Recoverable metadata-only evidence for each derived preview conversion. No document or PDF bytes.

CREATE TABLE IF NOT EXISTS collabio.source_object_preview_conversion_job_evidence (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    job_evidence_hash text NOT NULL CHECK (job_evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    derived_preview_receipt_hash text NOT NULL CHECK (
        derived_preview_receipt_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    source_object_write_receipt_hash text NOT NULL CHECK (
        source_object_write_receipt_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    source_object_id text NOT NULL CHECK (source_object_id <> ''),
    source_version_id text NOT NULL CHECK (source_version_id <> ''),
    derived_object_id text NOT NULL CHECK (derived_object_id <> ''),
    derived_version_id text NOT NULL CHECK (derived_version_id <> ''),
    command_hash text NOT NULL CHECK (command_hash ~ '^sha256:[a-f0-9]{64}$'),
    source_preflight_evidence_hash text NOT NULL CHECK (
        source_preflight_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    result_hash text NOT NULL CHECK (result_hash ~ '^sha256:[a-f0-9]{64}$'),
    execution_gate_evidence_hash text NOT NULL CHECK (
        execution_gate_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    completed_at_utc timestamptz NOT NULL,
    evidence jsonb NOT NULL CHECK (
        jsonb_typeof(evidence) = 'object'
        AND evidence ->> 'schema_version' = 'source_object_preview_conversion_job_evidence.v1'
        AND evidence ->> 'tenant_id' = tenant_id
        AND evidence ->> 'job_evidence_hash' = job_evidence_hash
        AND evidence ->> 'derived_preview_receipt_hash' = derived_preview_receipt_hash
        AND evidence ->> 'source_object_write_receipt_hash' = source_object_write_receipt_hash
        AND evidence ->> 'source_object_id' = source_object_id
        AND evidence ->> 'source_version_id' = source_version_id
        AND evidence ->> 'derived_object_id' = derived_object_id
        AND evidence ->> 'derived_version_id' = derived_version_id
        AND evidence ->> 'command_hash' = command_hash
        AND evidence ->> 'source_preflight_evidence_hash' = source_preflight_evidence_hash
        AND evidence ->> 'result_hash' = result_hash
        AND evidence ->> 'execution_gate_evidence_hash' = execution_gate_evidence_hash
        AND jsonb_typeof(evidence -> 'command') = 'object'
        AND jsonb_typeof(evidence -> 'source_preflight') = 'object'
        AND jsonb_typeof(evidence -> 'result') = 'object'
        AND evidence -> 'command' ->> 'command_hash' = command_hash
        AND evidence -> 'command' ->> 'source_preflight_evidence_hash' = source_preflight_evidence_hash
        AND evidence -> 'command' ->> 'execution_gate_evidence_hash' = execution_gate_evidence_hash
        AND evidence -> 'source_preflight' ->> 'evidence_hash' = source_preflight_evidence_hash
        AND evidence -> 'result' ->> 'result_hash' = result_hash
        AND evidence -> 'result' ->> 'command_hash' = command_hash
        AND evidence -> 'result' ->> 'source_preflight_evidence_hash' = source_preflight_evidence_hash
        AND evidence -> 'result' ->> 'execution_gate_evidence_hash' = execution_gate_evidence_hash
        AND evidence -> 'result' ->> 'worker_image_ref' = evidence ->> 'worker_image_ref'
        AND (evidence ->> 'source_content_in_evidence')::boolean = false
        AND (evidence ->> 'output_content_in_evidence')::boolean = false
        AND NOT (evidence ? 'content')
        AND NOT (evidence ? 'source_bytes')
        AND NOT (evidence ? 'output_bytes')
        AND NOT (evidence ? 'reason')
        AND NOT (evidence ? 'stdout')
        AND NOT (evidence ? 'stderr')
        AND NOT (evidence ? 'credentials')
        AND NOT (evidence ? 'secret')
        AND NOT (evidence -> 'command' ? 'content')
        AND NOT (evidence -> 'command' ? 'source_bytes')
        AND NOT (evidence -> 'command' ? 'output_bytes')
        AND NOT (evidence -> 'command' ? 'reason')
        AND NOT (evidence -> 'command' ? 'credentials')
        AND NOT (evidence -> 'command' ? 'secret')
        AND NOT (evidence -> 'source_preflight' ? 'content')
        AND NOT (evidence -> 'source_preflight' ? 'source_bytes')
        AND NOT (evidence -> 'source_preflight' ? 'credentials')
        AND NOT (evidence -> 'source_preflight' ? 'secret')
        AND NOT (evidence -> 'result' ? 'content')
        AND NOT (evidence -> 'result' ? 'output_bytes')
        AND NOT (evidence -> 'result' ? 'stdout')
        AND NOT (evidence -> 'result' ? 'stderr')
        AND NOT (evidence -> 'result' ? 'credentials')
        AND NOT (evidence -> 'result' ? 'secret')
    ),
    captured_at_utc timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, job_evidence_hash),
    UNIQUE (tenant_id, derived_preview_receipt_hash),
    UNIQUE (tenant_id, source_object_write_receipt_hash),
    UNIQUE (tenant_id, command_hash),
    UNIQUE (tenant_id, result_hash),
    FOREIGN KEY (tenant_id, source_object_id, source_version_id)
        REFERENCES collabio.source_object_metadata (tenant_id, object_id, version_id),
    FOREIGN KEY (tenant_id, derived_object_id, derived_version_id)
        REFERENCES collabio.source_object_metadata (tenant_id, object_id, version_id),
    FOREIGN KEY (tenant_id, derived_preview_receipt_hash)
        REFERENCES collabio.source_object_derived_preview_receipts (tenant_id, receipt_hash),
    FOREIGN KEY (tenant_id, source_object_write_receipt_hash)
        REFERENCES collabio.source_object_write_receipts (tenant_id, receipt_hash),
    FOREIGN KEY (tenant_id, execution_gate_evidence_hash)
        REFERENCES collabio.source_object_preview_conversion_execution_gates (tenant_id, evidence_hash)
);

COMMENT ON TABLE collabio.source_object_preview_conversion_job_evidence IS
    'Append-only metadata-only command, preflight, and worker-result evidence for derived preview recovery.';

CREATE INDEX IF NOT EXISTS source_object_preview_conversion_job_source_idx
    ON collabio.source_object_preview_conversion_job_evidence (
        tenant_id, source_object_id, source_version_id, completed_at_utc
    );

ALTER TABLE collabio.source_object_preview_conversion_job_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.source_object_preview_conversion_job_evidence FORCE ROW LEVEL SECURITY;

CREATE POLICY source_object_preview_conversion_job_tenant_select
    ON collabio.source_object_preview_conversion_job_evidence
    FOR SELECT USING (tenant_id = collabio.current_tenant_id());

CREATE POLICY source_object_preview_conversion_job_tenant_insert
    ON collabio.source_object_preview_conversion_job_evidence
    FOR INSERT WITH CHECK (tenant_id = collabio.current_tenant_id());

CREATE POLICY source_object_preview_conversion_job_no_update
    ON collabio.source_object_preview_conversion_job_evidence
    FOR UPDATE USING (false);

CREATE POLICY source_object_preview_conversion_job_no_hard_delete
    ON collabio.source_object_preview_conversion_job_evidence
    FOR DELETE USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.source_object_preview_conversion_job_evidence TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT SELECT ON TABLE collabio.source_object_preview_conversion_job_evidence TO collabio_worker';
    END IF;
END
$$;
