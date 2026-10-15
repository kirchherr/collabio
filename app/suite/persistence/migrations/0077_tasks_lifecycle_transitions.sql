-- 0077_tasks_lifecycle_transitions.sql
-- Append-only task lifecycle transitions with per-task hash-chain evidence.

CREATE TABLE IF NOT EXISTS tasks.lifecycle_transitions (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    object_id text NOT NULL CHECK (object_id <> ''),
    task_object_id text NOT NULL CHECK (task_object_id <> ''),
    activity_object_id text NOT NULL CHECK (activity_object_id <> ''),
    mutation_reference text NOT NULL CHECK (mutation_reference ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    command_hash text NOT NULL CHECK (command_hash ~ '^sha256:[a-f0-9]{64}$'),
    sequence_no bigint NOT NULL CHECK (sequence_no > 0),
    previous_transition_hash text NOT NULL CHECK (previous_transition_hash ~ '^sha256:[a-f0-9]{64}$'),
    from_state text NOT NULL CHECK (
        from_state IN ('assigned', 'in_progress', 'blocked', 'completed', 'cancelled')
    ),
    to_state text NOT NULL CHECK (
        to_state IN ('in_progress', 'blocked', 'completed', 'cancelled', 'archived')
    ),
    transition_kind text NOT NULL CHECK (
        transition_kind IN ('started', 'blocked', 'resumed', 'completed', 'cancelled', 'archived')
    ),
    transitioned_by text NOT NULL CHECK (transitioned_by <> ''),
    transitioned_at_utc timestamptz NOT NULL,
    confirmation_statement_hash text CHECK (
        confirmation_statement_hash IS NULL OR confirmation_statement_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    transition_hash text NOT NULL CHECK (transition_hash ~ '^sha256:[a-f0-9]{64}$'),
    source_system text NOT NULL DEFAULT 'native' CHECK (source_system ~ '^[a-z][a-z0-9_+.-]*$'),
    schema_version text NOT NULL DEFAULT 'task_lifecycle_transition.v1'
        CHECK (schema_version = 'task_lifecycle_transition.v1'),
    PRIMARY KEY (tenant_id, object_id),
    UNIQUE (tenant_id, mutation_reference),
    UNIQUE (tenant_id, transition_hash),
    UNIQUE (tenant_id, task_object_id, sequence_no),
    FOREIGN KEY (tenant_id, task_object_id) REFERENCES tasks.items (tenant_id, object_id),
    FOREIGN KEY (tenant_id, activity_object_id) REFERENCES tasks.activities (tenant_id, object_id),
    CHECK (from_state <> to_state),
    CHECK (
        (from_state = 'assigned' AND transition_kind = 'started' AND to_state = 'in_progress')
        OR (from_state = 'assigned' AND transition_kind = 'blocked' AND to_state = 'blocked')
        OR (from_state = 'assigned' AND transition_kind = 'completed' AND to_state = 'completed')
        OR (from_state = 'in_progress' AND transition_kind = 'blocked' AND to_state = 'blocked')
        OR (from_state = 'in_progress' AND transition_kind = 'completed' AND to_state = 'completed')
        OR (from_state = 'blocked' AND transition_kind = 'resumed' AND to_state = 'in_progress')
        OR (from_state IN ('assigned', 'in_progress', 'blocked') AND transition_kind = 'cancelled'
            AND to_state = 'cancelled')
        OR (from_state IN ('completed', 'cancelled') AND transition_kind = 'archived'
            AND to_state = 'archived')
    ),
    CHECK (
        (to_state IN ('cancelled', 'archived') AND confirmation_statement_hash IS NOT NULL)
        OR (to_state NOT IN ('cancelled', 'archived') AND confirmation_statement_hash IS NULL)
    )
);

COMMENT ON TABLE tasks.lifecycle_transitions IS
    'Append-only authoritative task lifecycle events. Current task state is derived from the latest sequence.';
COMMENT ON COLUMN tasks.lifecycle_transitions.confirmation_statement_hash IS
    'Hash-only evidence of exact human confirmation for cancellation or archival; raw confirmation is forbidden.';

CREATE INDEX IF NOT EXISTS tasks_lifecycle_transitions_latest_idx
    ON tasks.lifecycle_transitions (tenant_id, task_object_id, sequence_no DESC);
CREATE INDEX IF NOT EXISTS tasks_lifecycle_transitions_actor_time_idx
    ON tasks.lifecycle_transitions (tenant_id, transitioned_by, transitioned_at_utc DESC);

CREATE OR REPLACE FUNCTION tasks.validate_lifecycle_transition_append()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    base_state text;
    base_audit_chain_ref text;
    linked_activity_task_object_id text;
    linked_activity_created_by text;
    linked_activity_occurred_at_utc timestamptz;
    prior_sequence_no bigint;
    prior_transition_hash text;
    prior_to_state text;
BEGIN
    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            NEW.tenant_id || ':task-transition:' || NEW.task_object_id,
            0
        )
    );

    SELECT lifecycle_state, audit_chain_ref
      INTO base_state, base_audit_chain_ref
      FROM tasks.items
     WHERE tenant_id = NEW.tenant_id
       AND object_id = NEW.task_object_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'task lifecycle transition references a missing task';
    END IF;
    IF NEW.audit_chain_ref <> base_audit_chain_ref THEN
        RAISE EXCEPTION 'task lifecycle transition audit chain does not match its task';
    END IF;

    SELECT task_object_id, created_by, occurred_at_utc
      INTO linked_activity_task_object_id, linked_activity_created_by,
           linked_activity_occurred_at_utc
      FROM tasks.activities
     WHERE tenant_id = NEW.tenant_id
       AND object_id = NEW.activity_object_id;
    IF NOT FOUND OR linked_activity_task_object_id <> NEW.task_object_id THEN
        RAISE EXCEPTION 'task lifecycle transition activity does not match its task';
    END IF;
    IF linked_activity_created_by <> NEW.transitioned_by
       OR linked_activity_occurred_at_utc <> NEW.transitioned_at_utc THEN
        RAISE EXCEPTION 'task lifecycle transition activity evidence is inconsistent';
    END IF;

    SELECT sequence_no, transition_hash, to_state
      INTO prior_sequence_no, prior_transition_hash, prior_to_state
      FROM tasks.lifecycle_transitions
     WHERE tenant_id = NEW.tenant_id
       AND task_object_id = NEW.task_object_id
     ORDER BY sequence_no DESC
     LIMIT 1;

    IF prior_sequence_no IS NULL THEN
        IF NEW.sequence_no <> 1
           OR NEW.previous_transition_hash <> 'sha256:' || repeat('0', 64)
           OR NEW.from_state <> base_state THEN
            RAISE EXCEPTION 'invalid first task lifecycle transition chain link';
        END IF;
    ELSIF NEW.sequence_no <> prior_sequence_no + 1
       OR NEW.previous_transition_hash <> prior_transition_hash
       OR NEW.from_state <> prior_to_state THEN
        RAISE EXCEPTION 'invalid task lifecycle transition chain link';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER tasks_lifecycle_transitions_validate_append
BEFORE INSERT ON tasks.lifecycle_transitions
FOR EACH ROW EXECUTE FUNCTION tasks.validate_lifecycle_transition_append();

ALTER TABLE tasks.lifecycle_transitions ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks.lifecycle_transitions FORCE ROW LEVEL SECURITY;

CREATE POLICY tasks_lifecycle_transitions_tenant_select
    ON tasks.lifecycle_transitions FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());
CREATE POLICY tasks_lifecycle_transitions_tenant_insert
    ON tasks.lifecycle_transitions FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());
CREATE POLICY tasks_lifecycle_transitions_no_update
    ON tasks.lifecycle_transitions FOR UPDATE USING (false) WITH CHECK (false);
CREATE POLICY tasks_lifecycle_transitions_no_hard_delete
    ON tasks.lifecycle_transitions FOR DELETE USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_authz_admin') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE tasks.lifecycle_transitions TO collabio_authz_admin';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT SELECT ON TABLE tasks.lifecycle_transitions TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT SELECT ON TABLE tasks.lifecycle_transitions TO collabio_worker';
    END IF;
END
$$;

UPDATE collabio.module_catalog
SET module_version = '0.3.0',
    description = (
        'Optional governed Tasks and Activities module with tenant-gated task creation, '
        'append-only lifecycle transitions and authoritative activity history. Notifications, '
        'integrations, RAG and AI remain separate gates.'
    ),
    required_migration_versions = '["0050", "0059", "0077"]'::jsonb
WHERE module_id = 'tasks_activities';
