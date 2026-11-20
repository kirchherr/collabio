-- 0049_lms_dry_run_execution_job_outbox.sql
-- Tenant-scoped LMS dry-run execution job outbox state machine.
-- This migration persists queue, lease and retry metadata only; worker execution and dry-run result persistence remain forbidden.

CREATE TABLE IF NOT EXISTS lms.dry_run_execution_job_outbox (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    module_id text NOT NULL DEFAULT 'lms' CHECK (module_id = 'lms'),
    continuity_domain text NOT NULL DEFAULT 'background_jobs_queues' CHECK (
        continuity_domain = 'background_jobs_queues'
    ),
    lms_continuity_domain text NOT NULL DEFAULT 'lms_training_records' CHECK (
        lms_continuity_domain = 'lms_training_records'
    ),
    dry_run_execution_admission_gate_evidence_hash text NOT NULL CHECK (
        dry_run_execution_admission_gate_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    dry_run_execution_approval_boundary_evidence_hash text NOT NULL CHECK (
        dry_run_execution_approval_boundary_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    dry_run_execution_approval_record_hash text NOT NULL CHECK (
        dry_run_execution_approval_record_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    dry_run_execution_scheduler_boundary_evidence_hash text NOT NULL CHECK (
        dry_run_execution_scheduler_boundary_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    dry_run_execution_worker_image_boundary_evidence_hash text NOT NULL CHECK (
        dry_run_execution_worker_image_boundary_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    dry_run_execution_final_readiness_gate_evidence_hash text NOT NULL CHECK (
        dry_run_execution_final_readiness_gate_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    worker_queue_ref text NOT NULL CHECK (worker_queue_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    worker_job_ref text NOT NULL CHECK (worker_job_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    worker_idempotency_key_hash text NOT NULL CHECK (worker_idempotency_key_hash ~ '^sha256:[a-f0-9]{64}$'),
    restore_evidence_hash text NOT NULL CHECK (restore_evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    queue_status text NOT NULL CHECK (queue_status IN ('queued', 'leased', 'retry_scheduled', 'blocked')),
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts > 0 AND max_attempts <= 20),
    lease_id text CHECK (lease_id IS NULL OR lease_id ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    lease_owner text CHECK (lease_owner IS NULL OR lease_owner <> ''),
    leased_until_utc timestamptz,
    next_attempt_after_utc timestamptz NOT NULL,
    last_error_type text CHECK (last_error_type IS NULL OR last_error_type <> ''),
    scheduler_activation_allowed boolean NOT NULL DEFAULT false CHECK (scheduler_activation_allowed = false),
    scheduler_job_created boolean NOT NULL DEFAULT false CHECK (scheduler_job_created = false),
    worker_image_resolution_allowed boolean NOT NULL DEFAULT false CHECK (worker_image_resolution_allowed = false),
    worker_image_resolved boolean NOT NULL DEFAULT false CHECK (worker_image_resolved = false),
    worker_image_pull_allowed boolean NOT NULL DEFAULT false CHECK (worker_image_pull_allowed = false),
    worker_image_pulled boolean NOT NULL DEFAULT false CHECK (worker_image_pulled = false),
    worker_dispatch_allowed boolean NOT NULL DEFAULT false CHECK (worker_dispatch_allowed = false),
    worker_queue_enqueued boolean NOT NULL DEFAULT false CHECK (worker_queue_enqueued = false),
    worker_execution_allowed boolean NOT NULL DEFAULT false CHECK (worker_execution_allowed = false),
    worker_executed boolean NOT NULL DEFAULT false CHECK (worker_executed = false),
    package_installation_dry_run_execution_allowed boolean NOT NULL DEFAULT false CHECK (
        package_installation_dry_run_execution_allowed = false
    ),
    package_installation_dry_run_executed boolean NOT NULL DEFAULT false CHECK (
        package_installation_dry_run_executed = false
    ),
    dry_run_result_persistence_allowed boolean NOT NULL DEFAULT false CHECK (
        dry_run_result_persistence_allowed = false
    ),
    dry_run_result_persisted boolean NOT NULL DEFAULT false CHECK (dry_run_result_persisted = false),
    package_installation_execution_allowed boolean NOT NULL DEFAULT false CHECK (
        package_installation_execution_allowed = false
    ),
    tenant_module_state_created boolean NOT NULL DEFAULT false CHECK (tenant_module_state_created = false),
    destructive_actions_allowed boolean NOT NULL DEFAULT false CHECK (destructive_actions_allowed = false),
    external_side_effect_allowed boolean NOT NULL DEFAULT false CHECK (external_side_effect_allowed = false),
    job_evidence jsonb NOT NULL CHECK (
        jsonb_typeof(job_evidence) = 'object'
        AND job_evidence ->> 'schema_version' = 'lms_package_installation_dry_run_execution_job_outbox.v1'
        AND NOT (job_evidence ? 'human_confirmation_statement')
        AND NOT (job_evidence ? 'course_content')
        AND NOT (job_evidence ? 'training_content')
        AND NOT (job_evidence ? 'dry_run_result_payload')
        AND NOT (job_evidence ? 'worker_execution_payload')
        AND (job_evidence ->> 'scheduler_activation_allowed')::boolean = false
        AND (job_evidence ->> 'scheduler_job_created')::boolean = false
        AND (job_evidence ->> 'worker_image_resolution_allowed')::boolean = false
        AND (job_evidence ->> 'worker_image_resolved')::boolean = false
        AND (job_evidence ->> 'worker_image_pull_allowed')::boolean = false
        AND (job_evidence ->> 'worker_image_pulled')::boolean = false
        AND (job_evidence ->> 'worker_dispatch_allowed')::boolean = false
        AND (job_evidence ->> 'worker_queue_enqueued')::boolean = false
        AND (job_evidence ->> 'worker_execution_allowed')::boolean = false
        AND (job_evidence ->> 'worker_executed')::boolean = false
        AND (job_evidence ->> 'package_installation_dry_run_execution_allowed')::boolean = false
        AND (job_evidence ->> 'package_installation_dry_run_executed')::boolean = false
        AND (job_evidence ->> 'dry_run_result_persistence_allowed')::boolean = false
        AND (job_evidence ->> 'dry_run_result_persisted')::boolean = false
        AND (job_evidence ->> 'package_installation_execution_allowed')::boolean = false
        AND (job_evidence ->> 'tenant_module_state_created')::boolean = false
        AND (job_evidence ->> 'destructive_actions_allowed')::boolean = false
        AND (job_evidence ->> 'external_side_effect_allowed')::boolean = false
    ),
    enqueued_at_utc timestamptz NOT NULL,
    updated_at_utc timestamptz NOT NULL,
    evidence_hash text NOT NULL CHECK (evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    captured_at_utc timestamptz NOT NULL DEFAULT now(),
    schema_version text NOT NULL DEFAULT 'lms_package_installation_dry_run_execution_job_outbox.v1' CHECK (
        schema_version = 'lms_package_installation_dry_run_execution_job_outbox.v1'
    ),
    PRIMARY KEY (tenant_id, worker_idempotency_key_hash),
    UNIQUE (tenant_id, worker_job_ref),
    CHECK ((job_evidence ->> 'tenant_id') = tenant_id),
    CHECK ((job_evidence ->> 'module_id') = module_id),
    CHECK ((job_evidence ->> 'continuity_domain') = continuity_domain),
    CHECK ((job_evidence ->> 'lms_continuity_domain') = lms_continuity_domain),
    CHECK ((job_evidence ->> 'dry_run_execution_admission_gate_evidence_hash') = dry_run_execution_admission_gate_evidence_hash),
    CHECK ((job_evidence ->> 'dry_run_execution_approval_boundary_evidence_hash') = dry_run_execution_approval_boundary_evidence_hash),
    CHECK ((job_evidence ->> 'dry_run_execution_approval_record_hash') = dry_run_execution_approval_record_hash),
    CHECK ((job_evidence ->> 'dry_run_execution_scheduler_boundary_evidence_hash') = dry_run_execution_scheduler_boundary_evidence_hash),
    CHECK ((job_evidence ->> 'dry_run_execution_worker_image_boundary_evidence_hash') = dry_run_execution_worker_image_boundary_evidence_hash),
    CHECK ((job_evidence ->> 'dry_run_execution_final_readiness_gate_evidence_hash') = dry_run_execution_final_readiness_gate_evidence_hash),
    CHECK ((job_evidence ->> 'worker_queue_ref') = worker_queue_ref),
    CHECK ((job_evidence ->> 'worker_job_ref') = worker_job_ref),
    CHECK ((job_evidence ->> 'worker_idempotency_key_hash') = worker_idempotency_key_hash),
    CHECK ((job_evidence ->> 'restore_evidence_hash') = restore_evidence_hash),
    CHECK ((job_evidence ->> 'queue_status') = queue_status),
    CHECK ((job_evidence ->> 'evidence_hash') = evidence_hash),
    CHECK (
        (
            queue_status = 'queued'
            AND attempt_count = 0
            AND lease_id IS NULL
            AND lease_owner IS NULL
            AND leased_until_utc IS NULL
            AND last_error_type IS NULL
        )
        OR (
            queue_status = 'leased'
            AND attempt_count > 0
            AND lease_id IS NOT NULL
            AND lease_owner IS NOT NULL
            AND leased_until_utc IS NOT NULL
            AND last_error_type IS NULL
        )
        OR (
            queue_status IN ('retry_scheduled', 'blocked')
            AND attempt_count > 0
            AND lease_id IS NULL
            AND lease_owner IS NULL
            AND leased_until_utc IS NULL
            AND last_error_type IS NOT NULL
        )
    )
);

COMMENT ON TABLE lms.dry_run_execution_job_outbox IS
    'Tenant-scoped LMS dry-run execution job outbox with idempotency, lease, retry, block state, restore evidence and hash-bound approval/admission/scheduler/worker-image evidence. Worker execution, result persistence and LMS state mutation remain forbidden.';

COMMENT ON COLUMN lms.dry_run_execution_job_outbox.job_evidence IS
    'lms_package_installation_dry_run_execution_job_outbox.v1 JSON. Contains queue state, idempotency hashes, lease/retry metadata and restore evidence only; no content, confirmation statement, worker execution payload or dry-run result payload.';

CREATE INDEX IF NOT EXISTS lms_dry_run_execution_job_outbox_ready_idx
    ON lms.dry_run_execution_job_outbox (
        tenant_id,
        queue_status,
        next_attempt_after_utc,
        enqueued_at_utc
    );

CREATE INDEX IF NOT EXISTS lms_dry_run_execution_job_outbox_chain_idx
    ON lms.dry_run_execution_job_outbox (
        tenant_id,
        dry_run_execution_admission_gate_evidence_hash,
        dry_run_execution_worker_image_boundary_evidence_hash,
        dry_run_execution_final_readiness_gate_evidence_hash,
        restore_evidence_hash
    );

ALTER TABLE lms.dry_run_execution_job_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE lms.dry_run_execution_job_outbox FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS lms_dry_run_execution_job_outbox_tenant_select
    ON lms.dry_run_execution_job_outbox;
CREATE POLICY lms_dry_run_execution_job_outbox_tenant_select
    ON lms.dry_run_execution_job_outbox
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS lms_dry_run_execution_job_outbox_tenant_insert
    ON lms.dry_run_execution_job_outbox;
CREATE POLICY lms_dry_run_execution_job_outbox_tenant_insert
    ON lms.dry_run_execution_job_outbox
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS lms_dry_run_execution_job_outbox_tenant_lease_retry_update
    ON lms.dry_run_execution_job_outbox;
CREATE POLICY lms_dry_run_execution_job_outbox_tenant_lease_retry_update
    ON lms.dry_run_execution_job_outbox
    FOR UPDATE
    USING (tenant_id = collabio.current_tenant_id())
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS lms_dry_run_execution_job_outbox_no_hard_delete
    ON lms.dry_run_execution_job_outbox;
CREATE POLICY lms_dry_run_execution_job_outbox_no_hard_delete
    ON lms.dry_run_execution_job_outbox
    FOR DELETE
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE lms.dry_run_execution_job_outbox TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE lms.dry_run_execution_job_outbox TO collabio_worker';
        EXECUTE 'GRANT UPDATE (
            queue_status,
            attempt_count,
            lease_id,
            lease_owner,
            leased_until_utc,
            next_attempt_after_utc,
            last_error_type,
            job_evidence,
            updated_at_utc,
            evidence_hash
        ) ON TABLE lms.dry_run_execution_job_outbox TO collabio_worker';
    END IF;
END
$$;
UPDATE collabio.module_catalog
SET required_migration_versions = '["0045", "0046", "0047", "0048", "0049"]'::jsonb
WHERE module_id = 'lms';