-- 0078_time_approval_decisions.sql
-- Append-only time approval submission and maker-checker decision evidence.

CREATE TABLE IF NOT EXISTS time_tracking.approval_decisions (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    object_id text NOT NULL CHECK (object_id <> ''),
    approval_object_id text NOT NULL CHECK (approval_object_id <> ''),
    entry_object_id text NOT NULL CHECK (entry_object_id <> ''),
    mutation_reference text NOT NULL CHECK (mutation_reference ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    command_hash text NOT NULL CHECK (command_hash ~ '^sha256:[a-f0-9]{64}$'),
    sequence_no bigint NOT NULL CHECK (sequence_no > 0),
    previous_decision_hash text NOT NULL CHECK (previous_decision_hash ~ '^sha256:[a-f0-9]{64}$'),
    from_state text NOT NULL CHECK (from_state IN ('not_submitted', 'submitted')),
    to_state text NOT NULL CHECK (
        to_state IN ('submitted', 'approved', 'rejected', 'correction_requested')
    ),
    action text NOT NULL CHECK (action IN ('submit', 'approve', 'reject', 'request_correction')),
    decided_by text NOT NULL CHECK (decided_by <> ''),
    decided_at_utc timestamptz NOT NULL,
    confirmation_statement_hash text CHECK (
        confirmation_statement_hash IS NULL OR confirmation_statement_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    decision_hash text NOT NULL CHECK (decision_hash ~ '^sha256:[a-f0-9]{64}$'),
    source_system text NOT NULL DEFAULT 'native' CHECK (source_system ~ '^[a-z][a-z0-9_+.-]*$'),
    schema_version text NOT NULL DEFAULT 'time_approval_decision.v1'
        CHECK (schema_version = 'time_approval_decision.v1'),
    PRIMARY KEY (tenant_id, object_id),
    UNIQUE (tenant_id, mutation_reference),
    UNIQUE (tenant_id, decision_hash),
    UNIQUE (tenant_id, approval_object_id, sequence_no),
    FOREIGN KEY (tenant_id, approval_object_id) REFERENCES time_tracking.approvals (tenant_id, object_id),
    FOREIGN KEY (tenant_id, entry_object_id) REFERENCES time_tracking.entries (tenant_id, object_id),
    CHECK (from_state <> to_state),
    CHECK (
        (from_state = 'not_submitted' AND action = 'submit' AND to_state = 'submitted')
        OR (from_state = 'submitted' AND action = 'approve' AND to_state = 'approved')
        OR (from_state = 'submitted' AND action = 'reject' AND to_state = 'rejected')
        OR (from_state = 'submitted' AND action = 'request_correction'
            AND to_state = 'correction_requested')
    ),
    CHECK (
        (action = 'submit' AND confirmation_statement_hash IS NULL)
        OR (action <> 'submit' AND confirmation_statement_hash IS NOT NULL)
    )
);

COMMENT ON TABLE time_tracking.approval_decisions IS
    'Append-only submission and decision chain. Current entry and approval state is derived from latest sequence.';
COMMENT ON COLUMN time_tracking.approval_decisions.confirmation_statement_hash IS
    'Hash-only evidence of exact human decision confirmation; raw confirmation is forbidden.';

CREATE INDEX IF NOT EXISTS time_approval_decisions_latest_idx
    ON time_tracking.approval_decisions (tenant_id, approval_object_id, sequence_no DESC);
CREATE INDEX IF NOT EXISTS time_approval_decisions_actor_time_idx
    ON time_tracking.approval_decisions (tenant_id, decided_by, decided_at_utc DESC);

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

    SELECT sequence_no, decision_hash, to_state
      INTO prior_sequence_no, prior_decision_hash, prior_to_state
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
    RETURN NEW;
END
$$;

CREATE TRIGGER time_approval_decisions_validate_append
BEFORE INSERT ON time_tracking.approval_decisions
FOR EACH ROW EXECUTE FUNCTION time_tracking.validate_approval_decision_append();

ALTER TABLE time_tracking.approval_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE time_tracking.approval_decisions FORCE ROW LEVEL SECURITY;

CREATE POLICY time_approval_decisions_tenant_select
    ON time_tracking.approval_decisions FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());
CREATE POLICY time_approval_decisions_tenant_insert
    ON time_tracking.approval_decisions FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());
CREATE POLICY time_approval_decisions_no_update
    ON time_tracking.approval_decisions FOR UPDATE USING (false) WITH CHECK (false);
CREATE POLICY time_approval_decisions_no_hard_delete
    ON time_tracking.approval_decisions FOR DELETE USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_authz_admin') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE time_tracking.approval_decisions TO collabio_authz_admin';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT SELECT ON TABLE time_tracking.approval_decisions TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT SELECT ON TABLE time_tracking.approval_decisions TO collabio_worker';
    END IF;
END
$$;

UPDATE collabio.module_catalog
SET module_version = '0.2.0',
    description = (
        'Optional governed Time Tracking module with tenant-gated entry creation, append-only '
        'submission and maker-checker approval decisions. Corrections, payroll exports and '
        'automation remain separate gates.'
    ),
    required_migration_versions = '["0060", "0078"]'::jsonb
WHERE module_id = 'time_tracking';
