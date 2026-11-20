-- 0028_knowledge_base_runtime_activation.sql
-- Tenant-scoped Knowledge Base runtime activation evidence.

CREATE TABLE IF NOT EXISTS collabio.knowledge_base_runtime_activations (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    activation_id text NOT NULL CHECK (activation_id <> ''),
    backend text NOT NULL CHECK (backend IN ('postgres_s3')),
    active boolean NOT NULL DEFAULT true,
    activated_at_utc timestamptz NOT NULL,
    activated_by text NOT NULL CHECK (activated_by <> ''),
    provider_profile_id text NOT NULL CHECK (provider_profile_id <> ''),
    restore_drill_report_hash text NOT NULL CHECK (restore_drill_report_hash ~ '^sha256:[a-f0-9]{64}$'),
    source_content_recovery_evidence_hash text NOT NULL CHECK (
        source_content_recovery_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    provider_profile_evidence_hash text NOT NULL CHECK (provider_profile_evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    production_write_deployment_gate_evidence_hash text NOT NULL CHECK (
        production_write_deployment_gate_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    source_content_recovery_evidence jsonb NOT NULL CHECK (
        jsonb_typeof(source_content_recovery_evidence) = 'object'
    ),
    provider_profile_evidence jsonb NOT NULL CHECK (jsonb_typeof(provider_profile_evidence) = 'object'),
    production_write_deployment_gate_evidence jsonb NOT NULL CHECK (
        jsonb_typeof(production_write_deployment_gate_evidence) = 'object'
    ),
    approval_reference text NOT NULL CHECK (approval_reference ~ '^[a-z][a-z0-9_+.-]*:.+'),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z][a-z0-9_+.-]*:.+'),
    activation_evidence_hash text NOT NULL CHECK (activation_evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    schema_version text NOT NULL DEFAULT 'knowledge_base_runtime_activation.v1' CHECK (
        schema_version = 'knowledge_base_runtime_activation.v1'
    ),
    PRIMARY KEY (tenant_id, activation_id),
    UNIQUE (tenant_id, activation_evidence_hash),
    CHECK ((source_content_recovery_evidence ->> 'tenant_id') = tenant_id),
    CHECK ((production_write_deployment_gate_evidence ->> 'tenant_id') = tenant_id),
    CHECK (
        (source_content_recovery_evidence ->> 'evidence_hash') = source_content_recovery_evidence_hash
    ),
    CHECK ((provider_profile_evidence ->> 'evidence_hash') = provider_profile_evidence_hash),
    CHECK (
        (production_write_deployment_gate_evidence ->> 'evidence_hash')
        = production_write_deployment_gate_evidence_hash
    ),
    CHECK ((source_content_recovery_evidence ->> 'api_wiring_allowed')::boolean IS TRUE),
    CHECK ((provider_profile_evidence ->> 'provider_profile_ready')::boolean IS TRUE),
    CHECK ((production_write_deployment_gate_evidence ->> 'api_wiring_allowed')::boolean IS TRUE)
);

CREATE UNIQUE INDEX IF NOT EXISTS knowledge_base_runtime_activations_one_active_idx
    ON collabio.knowledge_base_runtime_activations (tenant_id)
    WHERE active;

CREATE INDEX IF NOT EXISTS knowledge_base_runtime_activations_gate_hash_idx
    ON collabio.knowledge_base_runtime_activations (tenant_id, production_write_deployment_gate_evidence_hash);

COMMENT ON TABLE collabio.knowledge_base_runtime_activations IS
    'Tenant-scoped metadata-only activation evidence for Knowledge Base production runtime wiring.';

COMMENT ON COLUMN collabio.knowledge_base_runtime_activations.source_content_recovery_evidence IS
    'source_object_content_recovery_evidence.v1 JSON. Source text, article bodies, prompts, outputs, and raw payloads are excluded.';

ALTER TABLE collabio.knowledge_base_runtime_activations ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.knowledge_base_runtime_activations FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS knowledge_base_runtime_activations_tenant_select
    ON collabio.knowledge_base_runtime_activations;
CREATE POLICY knowledge_base_runtime_activations_tenant_select
    ON collabio.knowledge_base_runtime_activations
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS knowledge_base_runtime_activations_tenant_insert
    ON collabio.knowledge_base_runtime_activations;
CREATE POLICY knowledge_base_runtime_activations_tenant_insert
    ON collabio.knowledge_base_runtime_activations
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS knowledge_base_runtime_activations_tenant_deactivate
    ON collabio.knowledge_base_runtime_activations;
CREATE POLICY knowledge_base_runtime_activations_tenant_deactivate
    ON collabio.knowledge_base_runtime_activations
    FOR UPDATE
    USING (tenant_id = collabio.current_tenant_id())
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS knowledge_base_runtime_activations_no_hard_delete
    ON collabio.knowledge_base_runtime_activations;
CREATE POLICY knowledge_base_runtime_activations_no_hard_delete
    ON collabio.knowledge_base_runtime_activations
    FOR DELETE
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.knowledge_base_runtime_activations TO collabio_app';
        EXECUTE 'GRANT UPDATE (active) ON TABLE collabio.knowledge_base_runtime_activations TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT SELECT ON TABLE collabio.knowledge_base_runtime_activations TO collabio_worker';
    END IF;
END
$$;
