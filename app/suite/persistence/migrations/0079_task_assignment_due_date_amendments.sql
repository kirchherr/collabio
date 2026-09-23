-- 0079_task_assignment_due_date_amendments.sql
-- Append-only task reassignment and due-date amendments with ACL rebinding evidence.

CREATE TABLE IF NOT EXISTS tasks.amendments (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    object_id text NOT NULL CHECK (object_id <> ''),
    task_object_id text NOT NULL CHECK (task_object_id <> ''),
    activity_object_id text NOT NULL CHECK (activity_object_id <> ''),
    mutation_reference text NOT NULL CHECK (mutation_reference ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    command_hash text NOT NULL CHECK (command_hash ~ '^sha256:[a-f0-9]{64}$'),
    sequence_no bigint NOT NULL CHECK (sequence_no > 0),
    previous_amendment_hash text NOT NULL CHECK (previous_amendment_hash ~ '^sha256:[a-f0-9]{64}$'),
    from_assigned_principal_id text NOT NULL CHECK (from_assigned_principal_id <> ''),
    to_assigned_principal_id text NOT NULL CHECK (to_assigned_principal_id <> ''),
    from_due_at_utc timestamptz,
    to_due_at_utc timestamptz,
    assignment_changed boolean NOT NULL,
    due_date_changed boolean NOT NULL,
    amended_by text NOT NULL CHECK (amended_by <> ''),
    amended_at_utc timestamptz NOT NULL,
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    amendment_hash text NOT NULL CHECK (amendment_hash ~ '^sha256:[a-f0-9]{64}$'),
    source_system text NOT NULL DEFAULT 'native' CHECK (source_system ~ '^[a-z][a-z0-9_+.-]*$'),
    schema_version text NOT NULL DEFAULT 'task_amendment.v1'
        CHECK (schema_version = 'task_amendment.v1'),
    PRIMARY KEY (tenant_id, object_id),
    UNIQUE (tenant_id, mutation_reference),
    UNIQUE (tenant_id, amendment_hash),
    UNIQUE (tenant_id, task_object_id, sequence_no),
    FOREIGN KEY (tenant_id, task_object_id) REFERENCES tasks.items (tenant_id, object_id),
    FOREIGN KEY (tenant_id, activity_object_id) REFERENCES tasks.activities (tenant_id, object_id),
    CHECK (assignment_changed = (from_assigned_principal_id <> to_assigned_principal_id)),
    CHECK (due_date_changed = (from_due_at_utc IS DISTINCT FROM to_due_at_utc)),
    CHECK (assignment_changed OR due_date_changed)
);

COMMENT ON TABLE tasks.amendments IS
    'Append-only authoritative task assignment and due-date changes. Current values are projected from the latest sequence.';
COMMENT ON COLUMN tasks.amendments.command_hash IS
    'Idempotency evidence over the normalized amendment command and actor; no activity summary is logged separately.';

CREATE INDEX IF NOT EXISTS tasks_amendments_latest_idx
    ON tasks.amendments (tenant_id, task_object_id, sequence_no DESC);
CREATE INDEX IF NOT EXISTS tasks_amendments_actor_time_idx
    ON tasks.amendments (tenant_id, amended_by, amended_at_utc DESC);

CREATE OR REPLACE FUNCTION tasks.validate_amendment_append()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    base_assignee text;
    base_due_at_utc timestamptz;
    base_state text;
    base_created_by text;
    base_audit_chain_ref text;
    current_state text;
    linked_activity_task_object_id text;
    linked_activity_type text;
    linked_activity_created_by text;
    linked_activity_occurred_at_utc timestamptz;
    prior_sequence_no bigint;
    prior_amendment_hash text;
    prior_assignee text;
    prior_due_at_utc timestamptz;
BEGIN
    PERFORM pg_advisory_xact_lock(
        hashtextextended(NEW.tenant_id || ':task:' || NEW.task_object_id, 0)
    );

    SELECT assigned_principal_id, due_at_utc, lifecycle_state, created_by, audit_chain_ref
      INTO base_assignee, base_due_at_utc, base_state, base_created_by, base_audit_chain_ref
      FROM tasks.items
     WHERE tenant_id = NEW.tenant_id
       AND object_id = NEW.task_object_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'task amendment references a missing task';
    END IF;
    IF NEW.audit_chain_ref <> base_audit_chain_ref THEN
        RAISE EXCEPTION 'task amendment audit chain does not match its task';
    END IF;

    SELECT task_object_id, activity_type, created_by, occurred_at_utc
      INTO linked_activity_task_object_id, linked_activity_type,
           linked_activity_created_by, linked_activity_occurred_at_utc
      FROM tasks.activities
     WHERE tenant_id = NEW.tenant_id
       AND object_id = NEW.activity_object_id;
    IF NOT FOUND OR linked_activity_task_object_id <> NEW.task_object_id THEN
        RAISE EXCEPTION 'task amendment activity does not match its task';
    END IF;
    IF linked_activity_created_by <> NEW.amended_by
       OR linked_activity_occurred_at_utc <> NEW.amended_at_utc THEN
        RAISE EXCEPTION 'task amendment activity evidence is inconsistent';
    END IF;
    IF (NEW.assignment_changed AND linked_activity_type <> 'assigned')
       OR (NOT NEW.assignment_changed AND linked_activity_type <> 'due_date_changed') THEN
        RAISE EXCEPTION 'task amendment activity type is inconsistent';
    END IF;

    SELECT sequence_no, amendment_hash, to_assigned_principal_id, to_due_at_utc
      INTO prior_sequence_no, prior_amendment_hash, prior_assignee, prior_due_at_utc
      FROM tasks.amendments
     WHERE tenant_id = NEW.tenant_id
       AND task_object_id = NEW.task_object_id
     ORDER BY sequence_no DESC
     LIMIT 1;

    IF prior_sequence_no IS NULL THEN
        IF NEW.sequence_no <> 1
           OR NEW.previous_amendment_hash <> 'sha256:' || repeat('0', 64)
           OR NEW.from_assigned_principal_id <> base_assignee
           OR NEW.from_due_at_utc IS DISTINCT FROM base_due_at_utc THEN
            RAISE EXCEPTION 'invalid first task amendment chain link';
        END IF;
    ELSIF NEW.sequence_no <> prior_sequence_no + 1
       OR NEW.previous_amendment_hash <> prior_amendment_hash
       OR NEW.from_assigned_principal_id <> prior_assignee
       OR NEW.from_due_at_utc IS DISTINCT FROM prior_due_at_utc THEN
        RAISE EXCEPTION 'invalid task amendment chain link';
    END IF;

    SELECT COALESCE(
        (
            SELECT to_state
            FROM tasks.lifecycle_transitions
            WHERE tenant_id = NEW.tenant_id
              AND task_object_id = NEW.task_object_id
            ORDER BY sequence_no DESC
            LIMIT 1
        ),
        base_state
    ) INTO current_state;
    IF current_state IN ('completed', 'cancelled', 'archived') THEN
        RAISE EXCEPTION 'terminal tasks cannot be reassigned or rescheduled';
    END IF;

    IF NEW.assignment_changed THEN
        IF NOT EXISTS (
            SELECT 1
            FROM collabio.tenant_principals AS principal
            JOIN collabio.tenant_principal_memberships AS membership
              ON membership.tenant_id = principal.tenant_id
             AND membership.issuer = principal.issuer
             AND membership.subject = principal.subject
            WHERE principal.tenant_id = NEW.tenant_id
              AND principal.user_id = NEW.to_assigned_principal_id
              AND principal.status = 'active'
              AND membership.status = 'active'
        ) THEN
            RAISE EXCEPTION 'task amendment target principal is not active';
        END IF;
        IF NEW.from_assigned_principal_id <> base_created_by AND EXISTS (
            SELECT 1
            FROM collabio.object_acl_entries
            WHERE tenant_id = NEW.tenant_id
              AND object_id = NEW.task_object_id
              AND object_type = 'task.task'
              AND acl_subject_type = 'user'
              AND acl_subject_id = NEW.from_assigned_principal_id
              AND permission = 'write'
              AND status = 'active'
              AND audit_chain_ref = NEW.audit_chain_ref
        ) THEN
            RAISE EXCEPTION 'task amendment did not revoke the prior assignment ACL';
        END IF;
        IF NEW.to_assigned_principal_id <> base_created_by AND NOT EXISTS (
            SELECT 1
            FROM collabio.object_acl_entries
            WHERE tenant_id = NEW.tenant_id
              AND object_id = NEW.task_object_id
              AND object_type = 'task.task'
              AND acl_subject_type = 'user'
              AND acl_subject_id = NEW.to_assigned_principal_id
              AND permission = 'write'
              AND status = 'active'
              AND audit_chain_ref = NEW.audit_chain_ref
        ) THEN
            RAISE EXCEPTION 'task amendment target assignment ACL is missing';
        END IF;
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER tasks_amendments_validate_append
BEFORE INSERT ON tasks.amendments
FOR EACH ROW EXECUTE FUNCTION tasks.validate_amendment_append();

ALTER TABLE tasks.amendments ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks.amendments FORCE ROW LEVEL SECURITY;

CREATE POLICY tasks_amendments_tenant_select
    ON tasks.amendments FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());
CREATE POLICY tasks_amendments_tenant_insert
    ON tasks.amendments FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());
CREATE POLICY tasks_amendments_no_update
    ON tasks.amendments FOR UPDATE USING (false) WITH CHECK (false);
CREATE POLICY tasks_amendments_no_hard_delete
    ON tasks.amendments FOR DELETE USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_authz_admin') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE tasks.amendments TO collabio_authz_admin';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT SELECT ON TABLE tasks.amendments TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT SELECT ON TABLE tasks.amendments TO collabio_worker';
    END IF;
END
$$;

UPDATE collabio.module_catalog
SET module_version = '0.4.0',
    description = (
        'Optional governed Tasks and Activities module with tenant-gated task creation, '
        'append-only lifecycle transitions, versioned assignment and due-date amendments, '
        'ACL rebinding and authoritative activity history. Notifications, integrations, RAG '
        'and AI remain separate gates.'
    ),
    required_migration_versions = '["0050", "0059", "0077", "0079"]'::jsonb
WHERE module_id = 'tasks_activities';
