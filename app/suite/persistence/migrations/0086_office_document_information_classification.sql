-- Versioned user-facing information classification for native Office documents.
-- This is deliberately separate from the canonical source data_classification,
-- which remains `internal` and continues to drive storage/retention controls.
ALTER TABLE office.documents
    ADD COLUMN information_classification text NOT NULL DEFAULT 'internal'
    CHECK (information_classification IN ('public', 'internal', 'confidential', 'restricted'));

ALTER TABLE office.document_versions
    ADD COLUMN information_classification text NOT NULL DEFAULT 'internal'
    CHECK (information_classification IN ('public', 'internal', 'confidential', 'restricted'));

CREATE OR REPLACE FUNCTION office.guard_document_head()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    IF (to_jsonb(NEW) - ARRAY['title', 'information_classification', 'current_version_id', 'updated_at_utc', 'kms_key_ref'])
       IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['title', 'information_classification', 'current_version_id', 'updated_at_utc', 'kms_key_ref']) THEN
        RAISE EXCEPTION 'office document identity is immutable';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM office.document_versions
        WHERE tenant_id = NEW.tenant_id AND object_id = NEW.object_id AND version_id = NEW.current_version_id
          AND title = NEW.title AND information_classification = NEW.information_classification
          AND created_at_utc = NEW.updated_at_utc
          AND (version_id = OLD.current_version_id OR previous_version_id = OLD.current_version_id)
    ) THEN
        RAISE EXCEPTION 'office document head must reference a saved successor';
    END IF;
    RETURN NEW;
END
$$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        GRANT UPDATE (information_classification) ON office.documents TO collabio_app;
    END IF;
END
$$;

UPDATE collabio.module_catalog
SET module_version = '0.4.0',
    required_migration_versions = '["0083", "0084", "0085", "0086"]'::jsonb
WHERE module_id = 'office_documents';
