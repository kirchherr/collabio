-- 0029_knowledge_base_runtime_reconciliation.sql
-- Append-only Knowledge Base runtime reconciliation evidence and drift blocking.

ALTER TABLE collabio.knowledge_base_runtime_activations
    ADD COLUMN IF NOT EXISTS deactivated_at_utc timestamptz,
    ADD COLUMN IF NOT EXISTS deactivated_by text,
    ADD COLUMN IF NOT EXISTS deactivation_reason text,
    ADD COLUMN IF NOT EXISTS deactivation_reconciliation_evidence_hash text CHECK (
        deactivation_reconciliation_evidence_hash IS NULL
        OR deactivation_reconciliation_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    );

CREATE TABLE IF NOT EXISTS collabio.knowledge_base_runtime_reconciliation_evidence (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    activation_id text NOT NULL CHECK (activation_id <> ''),
    reconciliation_id text NOT NULL CHECK (reconciliation_id <> ''),
    checked_at_utc timestamptz NOT NULL,
    checked_by text NOT NULL CHECK (checked_by <> ''),
    activation_evidence_hash text NOT NULL CHECK (activation_evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    previous_source_content_recovery_evidence_hash text NOT NULL CHECK (
        previous_source_content_recovery_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    observed_source_content_recovery_evidence_hash text NOT NULL CHECK (
        observed_source_content_recovery_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    previous_provider_profile_evidence_hash text NOT NULL CHECK (
        previous_provider_profile_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    observed_provider_profile_evidence_hash text NOT NULL CHECK (
        observed_provider_profile_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    previous_production_write_deployment_gate_evidence_hash text NOT NULL CHECK (
        previous_production_write_deployment_gate_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    observed_production_write_deployment_gate_evidence_hash text NOT NULL CHECK (
        observed_production_write_deployment_gate_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    observed_source_content_recovery_evidence jsonb NOT NULL CHECK (
        jsonb_typeof(observed_source_content_recovery_evidence) = 'object'
    ),
    observed_provider_profile_evidence jsonb NOT NULL CHECK (
        jsonb_typeof(observed_provider_profile_evidence) = 'object'
    ),
    observed_production_write_deployment_gate_evidence jsonb NOT NULL CHECK (
        jsonb_typeof(observed_production_write_deployment_gate_evidence) = 'object'
    ),
    restore_drill_report_hash text NOT NULL CHECK (restore_drill_report_hash ~ '^sha256:[a-f0-9]{64}$'),
    blocking_reasons jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(blocking_reasons) = 'array'),
    reconciliation_status text NOT NULL CHECK (reconciliation_status IN ('ready', 'drift_blocked')),
    recommended_action text NOT NULL CHECK (recommended_action IN ('keep_active', 'deactivate_runtime')),
    runtime_deactivated boolean NOT NULL,
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z][a-z0-9_+.-]*:.+'),
    evidence_hash text NOT NULL CHECK (evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    schema_version text NOT NULL DEFAULT 'knowledge_base_runtime_reconciliation_evidence.v1' CHECK (
        schema_version = 'knowledge_base_runtime_reconciliation_evidence.v1'
    ),
    PRIMARY KEY (tenant_id, reconciliation_id),
    UNIQUE (tenant_id, evidence_hash),
    FOREIGN KEY (tenant_id, activation_id)
        REFERENCES collabio.knowledge_base_runtime_activations (tenant_id, activation_id),
    CHECK ((observed_source_content_recovery_evidence ->> 'tenant_id') = tenant_id),
    CHECK ((observed_production_write_deployment_gate_evidence ->> 'tenant_id') = tenant_id),
    CHECK (
        (observed_source_content_recovery_evidence ->> 'evidence_hash')
        = observed_source_content_recovery_evidence_hash
    ),
    CHECK ((observed_provider_profile_evidence ->> 'evidence_hash') = observed_provider_profile_evidence_hash),
    CHECK (
        (observed_production_write_deployment_gate_evidence ->> 'evidence_hash')
        = observed_production_write_deployment_gate_evidence_hash
    ),
    CHECK ((reconciliation_status = 'ready') = (jsonb_array_length(blocking_reasons) = 0)),
    CHECK ((recommended_action = 'deactivate_runtime') = runtime_deactivated)
);

CREATE INDEX IF NOT EXISTS knowledge_base_runtime_reconciliation_activation_idx
    ON collabio.knowledge_base_runtime_reconciliation_evidence (tenant_id, activation_id, checked_at_utc DESC);

CREATE INDEX IF NOT EXISTS knowledge_base_runtime_reconciliation_status_idx
    ON collabio.knowledge_base_runtime_reconciliation_evidence (tenant_id, reconciliation_status);

COMMENT ON TABLE collabio.knowledge_base_runtime_reconciliation_evidence IS
    'Append-only metadata-only evidence from periodic Knowledge Base runtime drift checks.';

COMMENT ON COLUMN collabio.knowledge_base_runtime_reconciliation_evidence.blocking_reasons IS
    'Machine-readable drift blockers. Source text, article bodies, prompts, outputs, and raw payloads are excluded.';

ALTER TABLE collabio.knowledge_base_runtime_reconciliation_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.knowledge_base_runtime_reconciliation_evidence FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS knowledge_base_runtime_reconciliation_tenant_select
    ON collabio.knowledge_base_runtime_reconciliation_evidence;
CREATE POLICY knowledge_base_runtime_reconciliation_tenant_select
    ON collabio.knowledge_base_runtime_reconciliation_evidence
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS knowledge_base_runtime_reconciliation_tenant_insert
    ON collabio.knowledge_base_runtime_reconciliation_evidence;
CREATE POLICY knowledge_base_runtime_reconciliation_tenant_insert
    ON collabio.knowledge_base_runtime_reconciliation_evidence
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS knowledge_base_runtime_reconciliation_no_update
    ON collabio.knowledge_base_runtime_reconciliation_evidence;
CREATE POLICY knowledge_base_runtime_reconciliation_no_update
    ON collabio.knowledge_base_runtime_reconciliation_evidence
    FOR UPDATE
    USING (false);

DROP POLICY IF EXISTS knowledge_base_runtime_reconciliation_no_hard_delete
    ON collabio.knowledge_base_runtime_reconciliation_evidence;
CREATE POLICY knowledge_base_runtime_reconciliation_no_hard_delete
    ON collabio.knowledge_base_runtime_reconciliation_evidence
    FOR DELETE
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.knowledge_base_runtime_reconciliation_evidence TO collabio_app';
        EXECUTE 'GRANT UPDATE (active, deactivated_at_utc, deactivated_by, deactivation_reason, deactivation_reconciliation_evidence_hash) ON TABLE collabio.knowledge_base_runtime_activations TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.knowledge_base_runtime_reconciliation_evidence TO collabio_worker';
        EXECUTE 'GRANT UPDATE (active, deactivated_at_utc, deactivated_by, deactivation_reason, deactivation_reconciliation_evidence_hash) ON TABLE collabio.knowledge_base_runtime_activations TO collabio_worker';
    END IF;
END
$$;
