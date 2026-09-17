-- 0081_task_mutation_serialization.sql
-- Serialize lifecycle transitions and assignment/due-date amendments for one task.

CREATE OR REPLACE FUNCTION tasks.acquire_task_mutation_lock()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(
        hashtextextended(NEW.tenant_id || ':task:' || NEW.task_object_id, 0)
    );
    RETURN NEW;
END
$$;

COMMENT ON FUNCTION tasks.acquire_task_mutation_lock() IS
    'Serializes all lifecycle and planning mutations for one tenant task before validation.';

CREATE TRIGGER tasks_lifecycle_transitions_serialize_task_mutations
BEFORE INSERT ON tasks.lifecycle_transitions
FOR EACH ROW EXECUTE FUNCTION tasks.acquire_task_mutation_lock();

UPDATE collabio.module_catalog
SET module_version = '0.4.1',
    description = (
        'Optional governed Tasks and Activities module with tenant-gated task creation, '
        'append-only serialized lifecycle transitions, versioned assignment and due-date '
        'amendments, ACL rebinding and authoritative activity history. Notifications, '
        'integrations, RAG and AI remain separate gates.'
    ),
    required_migration_versions = '["0050", "0059", "0077", "0079", "0081"]'::jsonb
WHERE module_id = 'tasks_activities';
