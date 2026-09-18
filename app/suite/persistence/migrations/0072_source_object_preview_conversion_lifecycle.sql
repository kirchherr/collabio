-- 0072_source_object_preview_conversion_lifecycle.sql
-- Fail-closed execution-gate evidence and derived PDF preview lineage. No document bytes.

CREATE TABLE IF NOT EXISTS collabio.source_object_preview_conversion_execution_gates (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    evidence_hash text NOT NULL CHECK (evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    gate_status text NOT NULL CHECK (gate_status IN ('ready', 'blocked')),
    worker_image_ref text NOT NULL CHECK (
        worker_image_ref ~ '^[a-z0-9][a-z0-9._/:+-]*@sha256:[a-f0-9]{64}$'
    ),
    sandbox_runtime_class text NOT NULL CHECK (
        sandbox_runtime_class IN ('runsc', 'kata-clh', 'kata-qemu', 'firecracker')
    ),
    evaluated_at_utc timestamptz NOT NULL,
    expires_at_utc timestamptz NOT NULL CHECK (expires_at_utc > evaluated_at_utc),
    evidence jsonb NOT NULL CHECK (
        jsonb_typeof(evidence) = 'object'
        AND evidence ->> 'schema_version' = 'source_object_preview_conversion_execution_gate.v1'
        AND evidence ->> 'tenant_id' = tenant_id
        AND evidence ->> 'evidence_hash' = evidence_hash
        AND evidence ->> 'gate_status' = gate_status
        AND evidence ->> 'worker_image_ref' = worker_image_ref
        AND evidence ->> 'sandbox_runtime_class' = sandbox_runtime_class
        AND jsonb_typeof(evidence -> 'blocking_reasons') = 'array'
        AND (
            (
                gate_status = 'ready'
                AND jsonb_array_length(evidence -> 'blocking_reasons') = 0
                AND (evidence ->> 'image_digest_pinned')::boolean = true
                AND (evidence ->> 'stronger_sandbox_attested')::boolean = true
                AND (evidence ->> 'network_egress_denied')::boolean = true
                AND (evidence ->> 'read_only_root_filesystem')::boolean = true
                AND (evidence ->> 'non_root_user')::boolean = true
                AND (evidence ->> 'all_capabilities_dropped')::boolean = true
                AND (evidence ->> 'no_new_privileges')::boolean = true
                AND (evidence ->> 'ephemeral_workspace')::boolean = true
                AND (evidence ->> 'malware_cdr_ready')::boolean = true
                AND (evidence ->> 'pdf_revalidation_ready')::boolean = true
                AND (evidence ->> 'font_baseline_ready')::boolean = true
                AND (evidence ->> 'restore_ready')::boolean = true
                AND (evidence ->> 'separate_viewer_origin_ready')::boolean = true
                AND (evidence ->> 'strict_viewer_csp_ready')::boolean = true
            )
            OR (
                gate_status = 'blocked'
                AND jsonb_array_length(evidence -> 'blocking_reasons') > 0
            )
        )
        AND NOT (evidence ? 'content')
        AND NOT (evidence ? 'source_bytes')
        AND NOT (evidence ? 'output_bytes')
        AND NOT (evidence ? 'credentials')
        AND NOT (evidence ? 'secret')
    ),
    captured_at_utc timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, evidence_hash)
);

CREATE TABLE IF NOT EXISTS collabio.source_object_derived_preview_receipts (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    source_object_id text NOT NULL CHECK (source_object_id <> ''),
    source_version_id text NOT NULL CHECK (source_version_id <> ''),
    derived_object_id text NOT NULL CHECK (derived_object_id <> ''),
    derived_version_id text NOT NULL CHECK (derived_version_id <> ''),
    command_hash text NOT NULL CHECK (command_hash ~ '^sha256:[a-f0-9]{64}$'),
    result_hash text NOT NULL CHECK (result_hash ~ '^sha256:[a-f0-9]{64}$'),
    execution_gate_evidence_hash text NOT NULL CHECK (
        execution_gate_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    source_preflight_evidence_hash text NOT NULL CHECK (
        source_preflight_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    worker_image_ref text NOT NULL CHECK (
        worker_image_ref ~ '^[a-z0-9][a-z0-9._/:+-]*@sha256:[a-f0-9]{64}$'
    ),
    created_at_utc timestamptz NOT NULL,
    receipt_hash text NOT NULL CHECK (receipt_hash ~ '^sha256:[a-f0-9]{64}$'),
    receipt jsonb NOT NULL CHECK (
        jsonb_typeof(receipt) = 'object'
        AND receipt ->> 'schema_version' = 'source_object_derived_preview_receipt.v1'
        AND receipt ->> 'tenant_id' = tenant_id
        AND receipt ->> 'source_object_id' = source_object_id
        AND receipt ->> 'source_version_id' = source_version_id
        AND receipt ->> 'derived_object_id' = derived_object_id
        AND receipt ->> 'derived_version_id' = derived_version_id
        AND receipt ->> 'command_hash' = command_hash
        AND receipt ->> 'result_hash' = result_hash
        AND receipt ->> 'execution_gate_evidence_hash' = execution_gate_evidence_hash
        AND receipt ->> 'source_preflight_evidence_hash' = source_preflight_evidence_hash
        AND receipt ->> 'worker_image_ref' = worker_image_ref
        AND receipt ->> 'receipt_hash' = receipt_hash
        AND (receipt ->> 'source_classification_inherited')::boolean = true
        AND (receipt ->> 'source_acl_inherited')::boolean = true
        AND (receipt ->> 'source_retention_inherited')::boolean = true
        AND (receipt ->> 'source_legal_hold_inherited')::boolean = true
        AND (receipt ->> 'source_lifecycle_inherited')::boolean = true
        AND (receipt ->> 'source_version_lineage_bound')::boolean = true
        AND (receipt ->> 'output_revalidated')::boolean = true
        AND (receipt ->> 'source_content_in_receipt')::boolean = false
        AND (receipt ->> 'output_content_in_receipt')::boolean = false
        AND NOT (receipt ? 'content')
        AND NOT (receipt ? 'source_bytes')
        AND NOT (receipt ? 'output_bytes')
        AND NOT (receipt ? 'reason')
        AND NOT (receipt ? 'stdout')
        AND NOT (receipt ? 'stderr')
    ),
    captured_at_utc timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, receipt_hash),
    UNIQUE (tenant_id, command_hash),
    UNIQUE (tenant_id, derived_object_id, derived_version_id),
    FOREIGN KEY (tenant_id, source_object_id, source_version_id)
        REFERENCES collabio.source_object_metadata (tenant_id, object_id, version_id),
    FOREIGN KEY (tenant_id, derived_object_id, derived_version_id)
        REFERENCES collabio.source_object_metadata (tenant_id, object_id, version_id),
    FOREIGN KEY (tenant_id, execution_gate_evidence_hash)
        REFERENCES collabio.source_object_preview_conversion_execution_gates (tenant_id, evidence_hash)
);

COMMENT ON TABLE collabio.source_object_preview_conversion_execution_gates IS
    'Append-only tenant-scoped admission evidence for credential-less, strongly isolated preview conversion jobs.';

COMMENT ON TABLE collabio.source_object_derived_preview_receipts IS
    'Append-only source-version lineage between authoritative objects and validated PDF preview SourceObjects. No content.';

CREATE INDEX IF NOT EXISTS source_object_preview_conversion_gate_expiry_idx
    ON collabio.source_object_preview_conversion_execution_gates (
        tenant_id, gate_status, expires_at_utc
    );

CREATE INDEX IF NOT EXISTS source_object_derived_preview_source_idx
    ON collabio.source_object_derived_preview_receipts (
        tenant_id, source_object_id, source_version_id, created_at_utc
    );

ALTER TABLE collabio.source_object_preview_conversion_execution_gates ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.source_object_preview_conversion_execution_gates FORCE ROW LEVEL SECURITY;
ALTER TABLE collabio.source_object_derived_preview_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.source_object_derived_preview_receipts FORCE ROW LEVEL SECURITY;

CREATE POLICY source_object_preview_conversion_gate_tenant_select
    ON collabio.source_object_preview_conversion_execution_gates
    FOR SELECT USING (tenant_id = collabio.current_tenant_id());

CREATE POLICY source_object_preview_conversion_gate_tenant_insert
    ON collabio.source_object_preview_conversion_execution_gates
    FOR INSERT WITH CHECK (tenant_id = collabio.current_tenant_id());

CREATE POLICY source_object_preview_conversion_gate_no_update
    ON collabio.source_object_preview_conversion_execution_gates
    FOR UPDATE USING (false);

CREATE POLICY source_object_preview_conversion_gate_no_hard_delete
    ON collabio.source_object_preview_conversion_execution_gates
    FOR DELETE USING (false);

CREATE POLICY source_object_derived_preview_tenant_select
    ON collabio.source_object_derived_preview_receipts
    FOR SELECT USING (tenant_id = collabio.current_tenant_id());

CREATE POLICY source_object_derived_preview_tenant_insert
    ON collabio.source_object_derived_preview_receipts
    FOR INSERT WITH CHECK (tenant_id = collabio.current_tenant_id());

CREATE POLICY source_object_derived_preview_no_update
    ON collabio.source_object_derived_preview_receipts
    FOR UPDATE USING (false);

CREATE POLICY source_object_derived_preview_no_hard_delete
    ON collabio.source_object_derived_preview_receipts
    FOR DELETE USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.source_object_preview_conversion_execution_gates TO collabio_app';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.source_object_derived_preview_receipts TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT SELECT ON TABLE collabio.source_object_preview_conversion_execution_gates TO collabio_worker';
        EXECUTE 'GRANT SELECT ON TABLE collabio.source_object_derived_preview_receipts TO collabio_worker';
    END IF;
END
$$;
