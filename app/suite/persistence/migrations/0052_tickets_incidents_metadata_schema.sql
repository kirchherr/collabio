-- 0052_tickets_incidents_metadata_schema.sql
-- Initial Tickets & Incidents metadata schema for ticket state and event history.
-- This does not create tenant module state, expose Tickets & Incidents APIs, start workers, or store message bodies/files.

CREATE SCHEMA IF NOT EXISTS tickets;

CREATE TABLE IF NOT EXISTS tickets.ticket_items (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    object_id text NOT NULL CHECK (object_id <> ''),
    object_type text NOT NULL DEFAULT 'ticket.ticket' CHECK (object_type = 'ticket.ticket'),
    owner_principal_id text NOT NULL CHECK (owner_principal_id <> ''),
    created_by text NOT NULL CHECK (created_by <> ''),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    updated_at_utc timestamptz NOT NULL DEFAULT now(),
    data_classification text NOT NULL DEFAULT 'personal' CHECK (data_classification IN ('personal', 'legal_hold')),
    retention_policy_id text NOT NULL DEFAULT 'rp-standard' CHECK (
        retention_policy_id IN ('rp-standard', 'rp-restricted', 'rp-legal-hold')
    ),
    legal_hold_state text NOT NULL DEFAULT 'none' CHECK (legal_hold_state IN ('none', 'active')),
    lifecycle_state text NOT NULL DEFAULT 'new' CHECK (
        lifecycle_state IN (
            'new',
            'open',
            'triaged',
            'in_progress',
            'waiting',
            'resolved',
            'cancelled',
            'archived',
            'disposition_pending'
        )
    ),
    kms_key_ref text NOT NULL CHECK (kms_key_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    source_system text NOT NULL CHECK (source_system ~ '^[a-z][a-z0-9_+.-]*$'),
    schema_version text NOT NULL DEFAULT 'ticket_item.v1' CHECK (schema_version = 'ticket_item.v1'),
    ticket_id text NOT NULL CHECK (ticket_id <> ''),
    ticket_number text NOT NULL CHECK (ticket_number <> ''),
    ticket_status text NOT NULL DEFAULT 'new' CHECK (
        ticket_status IN ('new', 'open', 'triaged', 'in_progress', 'waiting', 'resolved', 'cancelled', 'archived')
    ),
    priority text NOT NULL DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
    subject_redacted text NOT NULL CHECK (subject_redacted <> ''),
    sla_state text NOT NULL DEFAULT 'not_started' CHECK (
        sla_state IN ('not_started', 'on_track', 'at_risk', 'breached', 'paused', 'completed')
    ),
    PRIMARY KEY (tenant_id, ticket_id),
    UNIQUE (tenant_id, object_id),
    UNIQUE (tenant_id, ticket_number),
    CHECK (object_id = ticket_id),
    CHECK (ticket_status <> 'archived' OR lifecycle_state = 'archived'),
    CHECK (ticket_status <> 'resolved' OR lifecycle_state = 'resolved')
);

CREATE TABLE IF NOT EXISTS tickets.ticket_events (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    object_id text NOT NULL CHECK (object_id <> ''),
    object_type text NOT NULL DEFAULT 'ticket.event' CHECK (object_type = 'ticket.event'),
    owner_principal_id text NOT NULL CHECK (owner_principal_id <> ''),
    created_by text NOT NULL CHECK (created_by <> ''),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    updated_at_utc timestamptz NOT NULL DEFAULT now(),
    data_classification text NOT NULL DEFAULT 'personal' CHECK (data_classification IN ('personal', 'legal_hold')),
    retention_policy_id text NOT NULL DEFAULT 'rp-standard' CHECK (
        retention_policy_id IN ('rp-standard', 'rp-restricted', 'rp-legal-hold')
    ),
    legal_hold_state text NOT NULL DEFAULT 'none' CHECK (legal_hold_state IN ('none', 'active')),
    lifecycle_state text NOT NULL DEFAULT 'open' CHECK (
        lifecycle_state IN ('open', 'in_progress', 'waiting', 'resolved', 'cancelled', 'disposition_pending')
    ),
    kms_key_ref text NOT NULL CHECK (kms_key_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    source_system text NOT NULL CHECK (source_system ~ '^[a-z][a-z0-9_+.-]*$'),
    schema_version text NOT NULL DEFAULT 'ticket_event.v1' CHECK (schema_version = 'ticket_event.v1'),
    event_id text NOT NULL CHECK (event_id <> ''),
    ticket_id text NOT NULL CHECK (ticket_id <> ''),
    event_type text NOT NULL CHECK (
        event_type IN ('created', 'status_changed', 'assignment_changed', 'sla_changed', 'note_redacted')
    ),
    event_status text NOT NULL DEFAULT 'open' CHECK (
        event_status IN ('open', 'in_progress', 'waiting', 'resolved', 'cancelled')
    ),
    event_summary_redacted text NOT NULL CHECK (event_summary_redacted <> ''),
    occurred_at_utc timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, event_id),
    UNIQUE (tenant_id, object_id),
    FOREIGN KEY (tenant_id, ticket_id)
        REFERENCES tickets.ticket_items (tenant_id, ticket_id),
    CHECK (object_id = event_id),
    CHECK (event_status <> 'resolved' OR lifecycle_state = 'resolved'),
    CHECK (event_status <> 'cancelled' OR lifecycle_state = 'cancelled')
);

COMMENT ON SCHEMA tickets IS
    'Tickets and Incidents module schema. Initial slice stores ticket/event metadata only.';
COMMENT ON TABLE tickets.ticket_items IS
    'Tenant-scoped ticket metadata for tickets.items.read. Message bodies and files stay out of this table.';
COMMENT ON TABLE tickets.ticket_events IS
    'Tenant-scoped ticket event metadata for tickets.events.read. Event messages and files stay out of this table.';
COMMENT ON COLUMN tickets.ticket_items.subject_redacted IS
    'Redacted subject line only; full message text stays in governed source-object storage.';
COMMENT ON COLUMN tickets.ticket_events.event_summary_redacted IS
    'Redacted event summary only; full event text stays in governed source-object storage.';

CREATE UNIQUE INDEX IF NOT EXISTS tickets_ticket_items_number_unique_idx
    ON tickets.ticket_items (tenant_id, ticket_number);

CREATE INDEX IF NOT EXISTS tickets_ticket_items_tenant_status_idx
    ON tickets.ticket_items (tenant_id, ticket_status, lifecycle_state);

CREATE INDEX IF NOT EXISTS tickets_ticket_items_sla_idx
    ON tickets.ticket_items (tenant_id, sla_state, priority, lifecycle_state);

CREATE INDEX IF NOT EXISTS tickets_ticket_items_retention_legal_hold_idx
    ON tickets.ticket_items (tenant_id, retention_policy_id, legal_hold_state, lifecycle_state);

CREATE INDEX IF NOT EXISTS tickets_ticket_events_ticket_time_idx
    ON tickets.ticket_events (tenant_id, ticket_id, occurred_at_utc);

CREATE INDEX IF NOT EXISTS tickets_ticket_events_type_status_idx
    ON tickets.ticket_events (tenant_id, event_type, event_status, lifecycle_state);

CREATE INDEX IF NOT EXISTS tickets_ticket_events_retention_legal_hold_idx
    ON tickets.ticket_events (tenant_id, retention_policy_id, legal_hold_state, lifecycle_state);

CREATE OR REPLACE FUNCTION tickets.touch_updated_at_utc()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at_utc = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS tickets_ticket_items_touch_updated_at_utc ON tickets.ticket_items;
CREATE TRIGGER tickets_ticket_items_touch_updated_at_utc
    BEFORE UPDATE ON tickets.ticket_items
    FOR EACH ROW
    EXECUTE FUNCTION tickets.touch_updated_at_utc();

DROP TRIGGER IF EXISTS tickets_ticket_events_touch_updated_at_utc ON tickets.ticket_events;
CREATE TRIGGER tickets_ticket_events_touch_updated_at_utc
    BEFORE UPDATE ON tickets.ticket_events
    FOR EACH ROW
    EXECUTE FUNCTION tickets.touch_updated_at_utc();

ALTER TABLE tickets.ticket_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE tickets.ticket_items FORCE ROW LEVEL SECURITY;
ALTER TABLE tickets.ticket_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE tickets.ticket_events FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tickets_ticket_items_tenant_select ON tickets.ticket_items;
CREATE POLICY tickets_ticket_items_tenant_select
    ON tickets.ticket_items
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS tickets_ticket_items_tenant_insert ON tickets.ticket_items;
CREATE POLICY tickets_ticket_items_tenant_insert
    ON tickets.ticket_items
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS tickets_ticket_items_tenant_update ON tickets.ticket_items;
CREATE POLICY tickets_ticket_items_tenant_update
    ON tickets.ticket_items
    FOR UPDATE
    USING (tenant_id = collabio.current_tenant_id())
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS tickets_ticket_items_no_hard_delete ON tickets.ticket_items;
CREATE POLICY tickets_ticket_items_no_hard_delete
    ON tickets.ticket_items
    FOR DELETE
    USING (false);

DROP POLICY IF EXISTS tickets_ticket_events_tenant_select ON tickets.ticket_events;
CREATE POLICY tickets_ticket_events_tenant_select
    ON tickets.ticket_events
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS tickets_ticket_events_tenant_insert ON tickets.ticket_events;
CREATE POLICY tickets_ticket_events_tenant_insert
    ON tickets.ticket_events
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS tickets_ticket_events_no_update ON tickets.ticket_events;
CREATE POLICY tickets_ticket_events_no_update
    ON tickets.ticket_events
    FOR UPDATE
    USING (false)
    WITH CHECK (false);

DROP POLICY IF EXISTS tickets_ticket_events_no_hard_delete ON tickets.ticket_events;
CREATE POLICY tickets_ticket_events_no_hard_delete
    ON tickets.ticket_events
    FOR DELETE
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA tickets TO collabio_app';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE tickets.ticket_items TO collabio_app';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE tickets.ticket_events TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA tickets TO collabio_worker';
        EXECUTE 'GRANT SELECT ON TABLE tickets.ticket_items TO collabio_worker';
        EXECUTE 'GRANT SELECT ON TABLE tickets.ticket_events TO collabio_worker';
    END IF;
END
$$;

UPDATE collabio.module_catalog
SET required_migration_versions = '["0051", "0052"]'::jsonb
WHERE module_id = 'tickets_incidents'
  AND status = 'not_installed';
