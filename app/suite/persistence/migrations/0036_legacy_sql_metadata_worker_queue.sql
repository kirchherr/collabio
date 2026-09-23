-- 0036_legacy_sql_metadata_worker_queue.sql
-- Tenant-scoped metadata-only scheduling queue for Legacy SQL metadata worker jobs.

CREATE TABLE IF NOT EXISTS collabio.legacy_sql_metadata_worker_queue (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    module_id text NOT NULL DEFAULT 'crm_erp' CHECK (module_id ~ '^[a-z][a-z0-9_]*$'),
    source_system_ref text NOT NULL CHECK (source_system_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    connector_kind text NOT NULL CHECK (connector_kind = 'sqlserver'),
    host_profile_ref text NOT NULL CHECK (host_profile_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    schedule_evidence_hash text NOT NULL CHECK (schedule_evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    schedule_evidence_ref text NOT NULL CHECK (schedule_evidence_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    release_gate_evidence_hash text NOT NULL CHECK (release_gate_evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    metadata_worker_command_hash text NOT NULL CHECK (metadata_worker_command_hash ~ '^sha256:[a-f0-9]{64}$'),
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
    default_compose_legacy_network_enabled boolean NOT NULL DEFAULT false CHECK (
        default_compose_legacy_network_enabled = false
    ),
    network_connection_opened boolean NOT NULL DEFAULT false CHECK (network_connection_opened = false),
    real_connection_opened boolean NOT NULL DEFAULT false CHECK (real_connection_opened = false),
    raw_data_access_allowed boolean NOT NULL DEFAULT false CHECK (raw_data_access_allowed = false),
    import_dry_run_allowed boolean NOT NULL DEFAULT false CHECK (import_dry_run_allowed = false),
    import_write_allowed boolean NOT NULL DEFAULT false CHECK (import_write_allowed = false),
    destructive_actions_allowed boolean NOT NULL DEFAULT false CHECK (destructive_actions_allowed = false),
    schedule_evidence jsonb NOT NULL CHECK (
        jsonb_typeof(schedule_evidence) = 'object'
        AND schedule_evidence ->> 'schema_version' = 'legacy_sql_host_profile_adapter_schedule.v1'
        AND NOT (schedule_evidence ? 'connection_secret_ref')
        AND (schedule_evidence ->> 'default_compose_legacy_network_enabled')::boolean = false
        AND (schedule_evidence ->> 'network_connection_opened')::boolean = false
        AND (schedule_evidence ->> 'real_connection_opened')::boolean = false
        AND (schedule_evidence ->> 'raw_data_access_allowed')::boolean = false
        AND (schedule_evidence ->> 'import_dry_run_allowed')::boolean = false
        AND (schedule_evidence ->> 'import_write_allowed')::boolean = false
        AND (schedule_evidence ->> 'destructive_actions_allowed')::boolean = false
    ),
    job_evidence jsonb NOT NULL CHECK (
        jsonb_typeof(job_evidence) = 'object'
        AND job_evidence ->> 'schema_version' = 'legacy_sql_metadata_worker_queue_job.v1'
        AND job_evidence -> 'schedule_evidence' IS NOT NULL
        AND NOT (job_evidence -> 'schedule_evidence' ? 'connection_secret_ref')
        AND (job_evidence ->> 'default_compose_legacy_network_enabled')::boolean = false
        AND (job_evidence ->> 'network_connection_opened')::boolean = false
        AND (job_evidence ->> 'real_connection_opened')::boolean = false
        AND (job_evidence ->> 'raw_data_access_allowed')::boolean = false
        AND (job_evidence ->> 'import_dry_run_allowed')::boolean = false
        AND (job_evidence ->> 'import_write_allowed')::boolean = false
        AND (job_evidence ->> 'destructive_actions_allowed')::boolean = false
    ),
    enqueued_at_utc timestamptz NOT NULL,
    updated_at_utc timestamptz NOT NULL,
    evidence_hash text NOT NULL CHECK (evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    captured_at_utc timestamptz NOT NULL DEFAULT now(),
    schema_version text NOT NULL DEFAULT 'legacy_sql_metadata_worker_queue_job.v1' CHECK (
        schema_version = 'legacy_sql_metadata_worker_queue_job.v1'
    ),
    PRIMARY KEY (tenant_id, worker_idempotency_key_hash),
    UNIQUE (tenant_id, worker_job_ref),
    CHECK ((schedule_evidence ->> 'tenant_id') = tenant_id),
    CHECK ((schedule_evidence ->> 'module_id') = module_id),
    CHECK ((schedule_evidence ->> 'source_system_ref') = source_system_ref),
    CHECK ((schedule_evidence ->> 'connector_kind') = connector_kind),
    CHECK ((schedule_evidence ->> 'host_profile_ref') = host_profile_ref),
    CHECK ((schedule_evidence ->> 'evidence_hash') = schedule_evidence_hash),
    CHECK ((schedule_evidence ->> 'release_gate_evidence_hash') = release_gate_evidence_hash),
    CHECK ((schedule_evidence ->> 'metadata_worker_command_hash') = metadata_worker_command_hash),
    CHECK ((schedule_evidence ->> 'worker_queue_ref') = worker_queue_ref),
    CHECK ((job_evidence ->> 'tenant_id') = tenant_id),
    CHECK ((job_evidence ->> 'module_id') = module_id),
    CHECK ((job_evidence ->> 'source_system_ref') = source_system_ref),
    CHECK ((job_evidence ->> 'connector_kind') = connector_kind),
    CHECK ((job_evidence ->> 'host_profile_ref') = host_profile_ref),
    CHECK ((job_evidence ->> 'schedule_evidence_hash') = schedule_evidence_hash),
    CHECK ((job_evidence ->> 'schedule_evidence_ref') = schedule_evidence_ref),
    CHECK ((job_evidence ->> 'release_gate_evidence_hash') = release_gate_evidence_hash),
    CHECK ((job_evidence ->> 'metadata_worker_command_hash') = metadata_worker_command_hash),
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

COMMENT ON TABLE collabio.legacy_sql_metadata_worker_queue IS
    'Tenant-scoped metadata-only scheduling queue for Legacy SQL metadata worker jobs with idempotency, lease, retry, and restore evidence.';

COMMENT ON COLUMN collabio.legacy_sql_metadata_worker_queue.schedule_evidence IS
    'legacy_sql_host_profile_adapter_schedule.v1 JSON persisted for worker discovery. DSNs, raw SQL rows, sample values, table data, Secret references, import payloads, prompts, outputs, embeddings, transcripts, and destructive action payloads are excluded.';

COMMENT ON COLUMN collabio.legacy_sql_metadata_worker_queue.job_evidence IS
    'legacy_sql_metadata_worker_queue_job.v1 JSON. Contains queue state, idempotency hashes, lease/retry metadata, and restore evidence hashes only.';

CREATE INDEX IF NOT EXISTS legacy_sql_metadata_worker_queue_ready_idx
    ON collabio.legacy_sql_metadata_worker_queue (
        tenant_id,
        queue_status,
        next_attempt_after_utc,
        enqueued_at_utc
    );

CREATE INDEX IF NOT EXISTS legacy_sql_metadata_worker_queue_schedule_idx
    ON collabio.legacy_sql_metadata_worker_queue (
        tenant_id,
        schedule_evidence_hash,
        restore_evidence_hash
    );

ALTER TABLE collabio.legacy_sql_metadata_worker_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.legacy_sql_metadata_worker_queue FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS legacy_sql_metadata_worker_queue_tenant_select
    ON collabio.legacy_sql_metadata_worker_queue;
CREATE POLICY legacy_sql_metadata_worker_queue_tenant_select
    ON collabio.legacy_sql_metadata_worker_queue
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS legacy_sql_metadata_worker_queue_tenant_insert
    ON collabio.legacy_sql_metadata_worker_queue;
CREATE POLICY legacy_sql_metadata_worker_queue_tenant_insert
    ON collabio.legacy_sql_metadata_worker_queue
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS legacy_sql_metadata_worker_queue_tenant_lease_retry_update
    ON collabio.legacy_sql_metadata_worker_queue;
CREATE POLICY legacy_sql_metadata_worker_queue_tenant_lease_retry_update
    ON collabio.legacy_sql_metadata_worker_queue
    FOR UPDATE
    USING (tenant_id = collabio.current_tenant_id())
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS legacy_sql_metadata_worker_queue_no_hard_delete
    ON collabio.legacy_sql_metadata_worker_queue;
CREATE POLICY legacy_sql_metadata_worker_queue_no_hard_delete
    ON collabio.legacy_sql_metadata_worker_queue
    FOR DELETE
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.legacy_sql_metadata_worker_queue TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.legacy_sql_metadata_worker_queue TO collabio_worker';
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
        ) ON TABLE collabio.legacy_sql_metadata_worker_queue TO collabio_worker';
    END IF;
END
$$;
