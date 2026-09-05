-- 0033_source_object_preview_renderer_release_gate_evidence.sql
-- Append-only metadata-only release gate evidence for preview renderer wiring.

CREATE TABLE IF NOT EXISTS collabio.source_object_preview_renderer_release_gate_evidence (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    api_smoke_report_hash text NOT NULL CHECK (api_smoke_report_hash ~ '^sha256:[a-f0-9]{64}$'),
    recovery_drill_report_hash text NOT NULL CHECK (recovery_drill_report_hash ~ '^sha256:[a-f0-9]{64}$'),
    api_smoke_checked_at_utc timestamptz NOT NULL,
    recovery_drill_checked_at_utc timestamptz NOT NULL,
    evaluated_at_utc timestamptz NOT NULL,
    freshness_window_hours integer NOT NULL CHECK (freshness_window_hours > 0 AND freshness_window_hours <= 720),
    api_smoke_fresh boolean NOT NULL,
    recovery_drill_fresh boolean NOT NULL,
    api_smoke_passed boolean NOT NULL,
    recovery_drill_ready boolean NOT NULL,
    recovery_drill_bound boolean NOT NULL,
    tenant_ready boolean NOT NULL,
    metadata_only_boundary_verified boolean NOT NULL,
    renderer_connection_allowed boolean NOT NULL,
    viewer_connection_allowed boolean NOT NULL,
    content_release_workflow_allowed boolean NOT NULL,
    blocking_reasons jsonb NOT NULL CHECK (jsonb_typeof(blocking_reasons) = 'array'),
    gate_status text NOT NULL CHECK (gate_status IN ('ready', 'blocked')),
    gate_evidence jsonb NOT NULL CHECK (
        jsonb_typeof(gate_evidence) = 'object'
        AND gate_evidence ->> 'schema_version' = 'source_object_preview_renderer_release_gate.v1'
        AND gate_evidence -> 'required_evidence_inputs' ? 'source_object_preview_renderer_api_smoke_report_hash'
        AND gate_evidence -> 'required_evidence_inputs' ? 'source_object_preview_renderer_recovery_drill_report_hash'
    ),
    evidence_hash text NOT NULL CHECK (evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    captured_at_utc timestamptz NOT NULL DEFAULT now(),
    schema_version text NOT NULL DEFAULT 'source_object_preview_renderer_release_gate.v1' CHECK (
        schema_version = 'source_object_preview_renderer_release_gate.v1'
    ),
    PRIMARY KEY (tenant_id, evidence_hash),
    CHECK ((gate_evidence ->> 'tenant_id') = tenant_id),
    CHECK ((gate_evidence ->> 'api_smoke_report_hash') = api_smoke_report_hash),
    CHECK ((gate_evidence ->> 'recovery_drill_report_hash') = recovery_drill_report_hash),
    CHECK ((gate_evidence ->> 'evidence_hash') = evidence_hash),
    CHECK ((gate_evidence ->> 'gate_status') = gate_status),
    CHECK ((gate_evidence ->> 'renderer_connection_allowed')::boolean = renderer_connection_allowed),
    CHECK ((gate_evidence ->> 'viewer_connection_allowed')::boolean = viewer_connection_allowed),
    CHECK ((gate_evidence ->> 'content_release_workflow_allowed')::boolean = content_release_workflow_allowed),
    CHECK (
        (
            gate_status = 'ready'
            AND renderer_connection_allowed = true
            AND viewer_connection_allowed = true
            AND content_release_workflow_allowed = true
            AND jsonb_array_length(blocking_reasons) = 0
        )
        OR (
            gate_status = 'blocked'
            AND (
                renderer_connection_allowed = false
                OR viewer_connection_allowed = false
                OR content_release_workflow_allowed = false
            )
        )
    )
);

COMMENT ON TABLE collabio.source_object_preview_renderer_release_gate_evidence IS
    'Tenant-scoped append-only metadata-only release gate evidence for preview renderer, viewer, and content release wiring.';

COMMENT ON COLUMN collabio.source_object_preview_renderer_release_gate_evidence.gate_evidence IS
    'source_object_preview_renderer_release_gate.v1 JSON. Source text, rendered HTML, mail bodies, attachment bytes, prompts, outputs, embeddings, transcripts, and raw payloads are excluded.';

CREATE INDEX IF NOT EXISTS source_object_preview_renderer_release_gate_smoke_idx
    ON collabio.source_object_preview_renderer_release_gate_evidence (
        tenant_id,
        api_smoke_report_hash,
        recovery_drill_report_hash,
        evaluated_at_utc
    );

CREATE INDEX IF NOT EXISTS source_object_preview_renderer_release_gate_status_idx
    ON collabio.source_object_preview_renderer_release_gate_evidence (tenant_id, gate_status, evaluated_at_utc);

ALTER TABLE collabio.source_object_preview_renderer_release_gate_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.source_object_preview_renderer_release_gate_evidence FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS source_object_preview_renderer_release_gate_tenant_select
    ON collabio.source_object_preview_renderer_release_gate_evidence;
CREATE POLICY source_object_preview_renderer_release_gate_tenant_select
    ON collabio.source_object_preview_renderer_release_gate_evidence
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS source_object_preview_renderer_release_gate_tenant_insert
    ON collabio.source_object_preview_renderer_release_gate_evidence;
CREATE POLICY source_object_preview_renderer_release_gate_tenant_insert
    ON collabio.source_object_preview_renderer_release_gate_evidence
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS source_object_preview_renderer_release_gate_no_update
    ON collabio.source_object_preview_renderer_release_gate_evidence;
CREATE POLICY source_object_preview_renderer_release_gate_no_update
    ON collabio.source_object_preview_renderer_release_gate_evidence
    FOR UPDATE
    USING (false);

DROP POLICY IF EXISTS source_object_preview_renderer_release_gate_no_hard_delete
    ON collabio.source_object_preview_renderer_release_gate_evidence;
CREATE POLICY source_object_preview_renderer_release_gate_no_hard_delete
    ON collabio.source_object_preview_renderer_release_gate_evidence
    FOR DELETE
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.source_object_preview_renderer_release_gate_evidence TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.source_object_preview_renderer_release_gate_evidence TO collabio_worker';
    END IF;
END
$$;
