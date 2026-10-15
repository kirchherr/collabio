-- 0080_time_entry_corrections_resubmission.sql
-- Versioned time-entry corrections and approval resubmission bound to an exact correction hash.

CREATE TABLE IF NOT EXISTS time_tracking.entry_corrections (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    object_id text NOT NULL CHECK (object_id <> ''),
    entry_object_id text NOT NULL CHECK (entry_object_id <> ''),
    approval_object_id text NOT NULL CHECK (approval_object_id <> ''),
    mutation_reference text NOT NULL CHECK (mutation_reference ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    command_hash text NOT NULL CHECK (command_hash ~ '^sha256:[a-f0-9]{64}$'),
    revision_no bigint NOT NULL CHECK (revision_no > 0),
    previous_correction_hash text NOT NULL CHECK (previous_correction_hash ~ '^sha256:[a-f0-9]{64}$'),
    correction_request_decision_hash text NOT NULL
        CHECK (correction_request_decision_hash ~ '^sha256:[a-f0-9]{64}$'),
    corrected_by text NOT NULL CHECK (corrected_by <> ''),
    corrected_at_utc timestamptz NOT NULL,
    work_date date NOT NULL,
    started_at_utc timestamptz NOT NULL,
    ended_at_utc timestamptz NOT NULL,
    duration_minutes integer NOT NULL CHECK (duration_minutes BETWEEN 1 AND 1440),
    project_reference text CHECK (
        project_reference IS NULL OR project_reference ~ '^[a-z0-9][a-z0-9_+.-]*:.+'
    ),
    cost_center_reference text CHECK (
        cost_center_reference IS NULL OR cost_center_reference ~ '^[a-z0-9][a-z0-9_+.-]*:.+'
    ),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    correction_hash text NOT NULL CHECK (correction_hash ~ '^sha256:[a-f0-9]{64}$'),
    source_system text NOT NULL DEFAULT 'native' CHECK (source_system ~ '^[a-z][a-z0-9_+.-]*$'),
    schema_version text NOT NULL DEFAULT 'time_entry_correction.v1'
        CHECK (schema_version = 'time_entry_correction.v1'),
    PRIMARY KEY (tenant_id, object_id),
    UNIQUE (tenant_id, mutation_reference),
    UNIQUE (tenant_id, correction_hash),
    UNIQUE (tenant_id, entry_object_id, revision_no),
    FOREIGN KEY (tenant_id, entry_object_id) REFERENCES time_tracking.entries (tenant_id, object_id),
    FOREIGN KEY (tenant_id, approval_object_id) REFERENCES time_tracking.approvals (tenant_id, object_id),
    CHECK (ended_at_utc > started_at_utc),
    CHECK (EXTRACT(EPOCH FROM (ended_at_utc - started_at_utc)) = duration_minutes * 60)
);

COMMENT ON TABLE time_tracking.entry_corrections IS
    'Append-only full metadata revisions created only in response to the current correction-request decision.';
COMMENT ON COLUMN time_tracking.entry_corrections.correction_request_decision_hash IS
    'Binds the correction to the exact approval decision that requested it.';

CREATE INDEX IF NOT EXISTS time_entry_corrections_latest_idx
    ON time_tracking.entry_corrections (tenant_id, entry_object_id, revision_no DESC);
CREATE INDEX IF NOT EXISTS time_entry_corrections_actor_time_idx
    ON time_tracking.entry_corrections (tenant_id, corrected_by, corrected_at_utc DESC);

ALTER TABLE time_tracking.approval_decisions
    ADD COLUMN IF NOT EXISTS correction_revision_no bigint,
    ADD COLUMN IF NOT EXISTS correction_hash text;

ALTER TABLE time_tracking.approval_decisions
    DROP CONSTRAINT IF EXISTS approval_decisions_from_state_check;
ALTER TABLE time_tracking.approval_decisions
    DROP CONSTRAINT IF EXISTS approval_decisions_schema_version_check;
ALTER TABLE time_tracking.approval_decisions
    DROP CONSTRAINT IF EXISTS approval_decisions_check1;

ALTER TABLE time_tracking.approval_decisions
    ALTER COLUMN schema_version SET DEFAULT 'time_approval_decision.v2';
ALTER TABLE time_tracking.approval_decisions
    ADD CONSTRAINT time_approval_decisions_from_state_check
        CHECK (from_state IN ('not_submitted', 'submitted', 'correction_requested')),
    ADD CONSTRAINT time_approval_decisions_transition_check
        CHECK (
            (from_state = 'not_submitted' AND action = 'submit' AND to_state = 'submitted')
            OR (from_state = 'correction_requested' AND action = 'submit' AND to_state = 'submitted')
            OR (from_state = 'submitted' AND action = 'approve' AND to_state = 'approved')
            OR (from_state = 'submitted' AND action = 'reject' AND to_state = 'rejected')
            OR (from_state = 'submitted' AND action = 'request_correction'
                AND to_state = 'correction_requested')
        ),
    ADD CONSTRAINT time_approval_decisions_correction_binding_check
        CHECK (
            (
                from_state = 'correction_requested'
                AND action = 'submit'
                AND correction_revision_no IS NOT NULL
                AND correction_revision_no > 0
                AND correction_hash ~ '^sha256:[a-f0-9]{64}$'
            )
            OR (
                NOT (from_state = 'correction_requested' AND action = 'submit')
                AND correction_revision_no IS NULL
                AND correction_hash IS NULL
            )
        ),
    ADD CONSTRAINT time_approval_decisions_schema_version_check
        CHECK (schema_version IN ('time_approval_decision.v1', 'time_approval_decision.v2')),
    ADD CONSTRAINT time_approval_decisions_correction_hash_fk
        FOREIGN KEY (tenant_id, correction_hash)
        REFERENCES time_tracking.entry_corrections (tenant_id, correction_hash);

CREATE OR REPLACE FUNCTION time_tracking.validate_entry_correction_append()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    linked_entry_object_id text;
    linked_audit_chain_ref text;
    latest_decision_hash text;
    latest_decision_state text;
    prior_revision_no bigint;
    prior_correction_hash text;
BEGIN
    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            NEW.tenant_id || ':time-approval-decision:' || NEW.approval_object_id,
            0
        )
    );

    SELECT entry_object_id, audit_chain_ref
      INTO linked_entry_object_id, linked_audit_chain_ref
      FROM time_tracking.approvals
     WHERE tenant_id = NEW.tenant_id
       AND object_id = NEW.approval_object_id;
    IF NOT FOUND OR linked_entry_object_id <> NEW.entry_object_id THEN
        RAISE EXCEPTION 'time entry correction approval does not match its entry';
    END IF;
    IF NEW.audit_chain_ref <> linked_audit_chain_ref THEN
        RAISE EXCEPTION 'time entry correction audit chain does not match its approval';
    END IF;

    SELECT decision_hash, to_state
      INTO latest_decision_hash, latest_decision_state
      FROM time_tracking.approval_decisions
     WHERE tenant_id = NEW.tenant_id
       AND approval_object_id = NEW.approval_object_id
     ORDER BY sequence_no DESC
     LIMIT 1;
    IF latest_decision_state IS DISTINCT FROM 'correction_requested'
       OR latest_decision_hash IS DISTINCT FROM NEW.correction_request_decision_hash THEN
        RAISE EXCEPTION 'time entry correction is not bound to the current correction request';
    END IF;

    SELECT revision_no, correction_hash
      INTO prior_revision_no, prior_correction_hash
      FROM time_tracking.entry_corrections
     WHERE tenant_id = NEW.tenant_id
       AND entry_object_id = NEW.entry_object_id
     ORDER BY revision_no DESC
     LIMIT 1;
    IF prior_revision_no IS NULL THEN
        IF NEW.revision_no <> 1
           OR NEW.previous_correction_hash <> 'sha256:' || repeat('0', 64) THEN
            RAISE EXCEPTION 'invalid first time entry correction chain link';
        END IF;
    ELSIF NEW.revision_no <> prior_revision_no + 1
       OR NEW.previous_correction_hash <> prior_correction_hash THEN
        RAISE EXCEPTION 'invalid time entry correction chain link';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER time_entry_corrections_validate_append
BEFORE INSERT ON time_tracking.entry_corrections
FOR EACH ROW EXECUTE FUNCTION time_tracking.validate_entry_correction_append();

CREATE OR REPLACE FUNCTION time_tracking.validate_approval_decision_append()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    linked_entry_object_id text;
    linked_worker_principal_id text;
    linked_created_by text;
    base_approval_state text;
    base_audit_chain_ref text;
    prior_sequence_no bigint;
    prior_decision_hash text;
    prior_to_state text;
    prior_decided_at_utc timestamptz;
    latest_correction_revision_no bigint;
    latest_correction_hash text;
    latest_correction_request_hash text;
    latest_corrected_at_utc timestamptz;
BEGIN
    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            NEW.tenant_id || ':time-approval-decision:' || NEW.approval_object_id,
            0
        )
    );

    SELECT entry_object_id, worker_principal_id, created_by, approval_state, audit_chain_ref
      INTO linked_entry_object_id, linked_worker_principal_id, linked_created_by,
           base_approval_state, base_audit_chain_ref
      FROM time_tracking.approvals
     WHERE tenant_id = NEW.tenant_id
       AND object_id = NEW.approval_object_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'time approval decision references a missing approval';
    END IF;
    IF NEW.entry_object_id <> linked_entry_object_id THEN
        RAISE EXCEPTION 'time approval decision entry does not match its approval';
    END IF;
    IF NEW.audit_chain_ref <> base_audit_chain_ref THEN
        RAISE EXCEPTION 'time approval decision audit chain does not match its approval';
    END IF;
    IF NEW.action <> 'submit'
       AND NEW.decided_by IN (linked_worker_principal_id, linked_created_by) THEN
        RAISE EXCEPTION 'time approval maker-checker separation required';
    END IF;

    SELECT sequence_no, decision_hash, to_state, decided_at_utc
      INTO prior_sequence_no, prior_decision_hash, prior_to_state, prior_decided_at_utc
      FROM time_tracking.approval_decisions
     WHERE tenant_id = NEW.tenant_id
       AND approval_object_id = NEW.approval_object_id
     ORDER BY sequence_no DESC
     LIMIT 1;

    IF prior_sequence_no IS NULL THEN
        IF NEW.sequence_no <> 1
           OR NEW.previous_decision_hash <> 'sha256:' || repeat('0', 64)
           OR NEW.from_state <> base_approval_state THEN
            RAISE EXCEPTION 'invalid first time approval decision chain link';
        END IF;
    ELSIF NEW.sequence_no <> prior_sequence_no + 1
       OR NEW.previous_decision_hash <> prior_decision_hash
       OR NEW.from_state <> prior_to_state THEN
        RAISE EXCEPTION 'invalid time approval decision chain link';
    END IF;

    IF NEW.from_state = 'correction_requested' AND NEW.action = 'submit' THEN
        SELECT revision_no, correction_hash, correction_request_decision_hash, corrected_at_utc
          INTO latest_correction_revision_no, latest_correction_hash,
               latest_correction_request_hash, latest_corrected_at_utc
          FROM time_tracking.entry_corrections
         WHERE tenant_id = NEW.tenant_id
           AND entry_object_id = NEW.entry_object_id
         ORDER BY revision_no DESC
         LIMIT 1;
        IF latest_correction_revision_no IS NULL
           OR NEW.correction_revision_no <> latest_correction_revision_no
           OR NEW.correction_hash <> latest_correction_hash
           OR latest_correction_request_hash <> prior_decision_hash
           OR latest_corrected_at_utc <= prior_decided_at_utc THEN
            RAISE EXCEPTION 'time approval resubmission is not bound to the latest requested correction';
        END IF;
    END IF;
    RETURN NEW;
END
$$;

ALTER TABLE time_tracking.entry_corrections ENABLE ROW LEVEL SECURITY;
ALTER TABLE time_tracking.entry_corrections FORCE ROW LEVEL SECURITY;

CREATE POLICY time_entry_corrections_tenant_select
    ON time_tracking.entry_corrections FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());
CREATE POLICY time_entry_corrections_tenant_insert
    ON time_tracking.entry_corrections FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());
CREATE POLICY time_entry_corrections_no_update
    ON time_tracking.entry_corrections FOR UPDATE USING (false) WITH CHECK (false);
CREATE POLICY time_entry_corrections_no_hard_delete
    ON time_tracking.entry_corrections FOR DELETE USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_authz_admin') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE time_tracking.entry_corrections TO collabio_authz_admin';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT SELECT ON TABLE time_tracking.entry_corrections TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT SELECT ON TABLE time_tracking.entry_corrections TO collabio_worker';
    END IF;
END
$$;

UPDATE collabio.module_catalog
SET module_version = '0.3.0',
    description = (
        'Optional governed Time Tracking module with tenant-gated entry creation, append-only '
        'submission and maker-checker approval decisions, versioned correction requests and '
        'resubmission bound to an exact correction hash. Payroll exports and automation remain '
        'separate gates.'
    ),
    required_migration_versions = '["0060", "0078", "0080"]'::jsonb
WHERE module_id = 'time_tracking';
