-- 0046_lms_metadata_schema.sql
-- Initial LMS metadata schema for course catalog and enrollment status.
-- This does not install the LMS package, create tenant module state, expose LMS APIs, or store course content.

CREATE SCHEMA IF NOT EXISTS lms;

CREATE TABLE IF NOT EXISTS lms.courses (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    object_id text NOT NULL CHECK (object_id <> ''),
    object_type text NOT NULL DEFAULT 'lms.course' CHECK (object_type = 'lms.course'),
    owner_principal_id text NOT NULL CHECK (owner_principal_id <> ''),
    created_by text NOT NULL CHECK (created_by <> ''),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    updated_at_utc timestamptz NOT NULL DEFAULT now(),
    data_classification text NOT NULL DEFAULT 'internal' CHECK (data_classification = 'internal'),
    retention_policy_id text NOT NULL DEFAULT 'rp-standard' CHECK (retention_policy_id = 'rp-standard'),
    legal_hold_state text NOT NULL DEFAULT 'none' CHECK (legal_hold_state IN ('none', 'active')),
    lifecycle_state text NOT NULL DEFAULT 'draft' CHECK (
        lifecycle_state IN ('draft', 'active', 'retired', 'disposition_pending')
    ),
    kms_key_ref text NOT NULL CHECK (kms_key_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    source_system text NOT NULL CHECK (source_system ~ '^[a-z][a-z0-9_+.-]*$'),
    schema_version text NOT NULL DEFAULT 'lms_course.v1' CHECK (schema_version = 'lms_course.v1'),
    course_key text NOT NULL CHECK (course_key <> ''),
    title text NOT NULL CHECK (title <> ''),
    course_version_label text NOT NULL CHECK (course_version_label <> ''),
    catalog_state text NOT NULL DEFAULT 'draft' CHECK (catalog_state IN ('draft', 'active', 'retired')),
    published_at_utc timestamptz,
    source_object_ref text CHECK (source_object_ref IS NULL OR source_object_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    PRIMARY KEY (tenant_id, object_id),
    UNIQUE (tenant_id, course_key),
    CHECK (catalog_state <> 'active' OR published_at_utc IS NOT NULL),
    CHECK (catalog_state <> 'retired' OR lifecycle_state = 'retired')
);

CREATE TABLE IF NOT EXISTS lms.enrollments (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    object_id text NOT NULL CHECK (object_id <> ''),
    object_type text NOT NULL DEFAULT 'lms.enrollment' CHECK (object_type = 'lms.enrollment'),
    owner_principal_id text NOT NULL CHECK (owner_principal_id <> ''),
    created_by text NOT NULL CHECK (created_by <> ''),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    updated_at_utc timestamptz NOT NULL DEFAULT now(),
    data_classification text NOT NULL DEFAULT 'personal' CHECK (data_classification = 'personal'),
    retention_policy_id text NOT NULL DEFAULT 'rp-standard' CHECK (retention_policy_id = 'rp-standard'),
    legal_hold_state text NOT NULL DEFAULT 'none' CHECK (legal_hold_state IN ('none', 'active')),
    lifecycle_state text NOT NULL DEFAULT 'assigned' CHECK (
        lifecycle_state IN ('assigned', 'completed', 'retired', 'disposition_pending')
    ),
    kms_key_ref text NOT NULL CHECK (kms_key_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    source_system text NOT NULL CHECK (source_system ~ '^[a-z][a-z0-9_+.-]*$'),
    schema_version text NOT NULL DEFAULT 'lms_enrollment.v1' CHECK (schema_version = 'lms_enrollment.v1'),
    course_object_id text NOT NULL CHECK (course_object_id <> ''),
    learner_principal_id text NOT NULL CHECK (learner_principal_id <> ''),
    enrollment_state text NOT NULL DEFAULT 'assigned' CHECK (
        enrollment_state IN ('assigned', 'completed', 'cancelled', 'disposition_pending')
    ),
    assigned_at_utc timestamptz NOT NULL DEFAULT now(),
    due_at_utc timestamptz,
    completed_at_utc timestamptz,
    completion_evidence_object_id text CHECK (
        completion_evidence_object_id IS NULL OR completion_evidence_object_id <> ''
    ),
    PRIMARY KEY (tenant_id, object_id),
    UNIQUE (tenant_id, course_object_id, learner_principal_id),
    FOREIGN KEY (tenant_id, course_object_id)
        REFERENCES lms.courses (tenant_id, object_id),
    CHECK (enrollment_state <> 'completed' OR completed_at_utc IS NOT NULL),
    CHECK (enrollment_state <> 'completed' OR lifecycle_state = 'completed'),
    CHECK (enrollment_state <> 'disposition_pending' OR lifecycle_state = 'disposition_pending')
);

COMMENT ON SCHEMA lms IS
    'Learning Management module schema. Initial slice stores course/enrollment metadata only.';
COMMENT ON TABLE lms.courses IS
    'Tenant-scoped LMS course catalog metadata for lms.courses.read. Course content is not stored here.';
COMMENT ON TABLE lms.enrollments IS
    'Tenant-scoped LMS enrollment status metadata for lms.enrollments.read. Evidence blobs are not stored here.';
COMMENT ON COLUMN lms.courses.source_object_ref IS
    'Optional source-object reference for future authorized retrieval; no course content body is stored here.';
COMMENT ON COLUMN lms.enrollments.completion_evidence_object_id IS
    'Optional future lms.completion_evidence object ID; certificate files and evidence bodies remain out of scope.';

CREATE UNIQUE INDEX IF NOT EXISTS lms_courses_course_key_unique_idx
    ON lms.courses (tenant_id, course_key);

CREATE INDEX IF NOT EXISTS lms_courses_tenant_state_idx
    ON lms.courses (tenant_id, catalog_state, lifecycle_state);

CREATE INDEX IF NOT EXISTS lms_courses_retention_legal_hold_idx
    ON lms.courses (tenant_id, retention_policy_id, legal_hold_state, lifecycle_state);

CREATE INDEX IF NOT EXISTS lms_enrollments_course_learner_idx
    ON lms.enrollments (tenant_id, course_object_id, learner_principal_id);

CREATE INDEX IF NOT EXISTS lms_enrollments_learner_state_idx
    ON lms.enrollments (tenant_id, learner_principal_id, enrollment_state, lifecycle_state);

CREATE INDEX IF NOT EXISTS lms_enrollments_retention_legal_hold_idx
    ON lms.enrollments (tenant_id, retention_policy_id, legal_hold_state, lifecycle_state);

CREATE OR REPLACE FUNCTION lms.touch_updated_at_utc()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at_utc = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS lms_courses_touch_updated_at_utc ON lms.courses;
CREATE TRIGGER lms_courses_touch_updated_at_utc
    BEFORE UPDATE ON lms.courses
    FOR EACH ROW
    EXECUTE FUNCTION lms.touch_updated_at_utc();

DROP TRIGGER IF EXISTS lms_enrollments_touch_updated_at_utc ON lms.enrollments;
CREATE TRIGGER lms_enrollments_touch_updated_at_utc
    BEFORE UPDATE ON lms.enrollments
    FOR EACH ROW
    EXECUTE FUNCTION lms.touch_updated_at_utc();

ALTER TABLE lms.courses ENABLE ROW LEVEL SECURITY;
ALTER TABLE lms.courses FORCE ROW LEVEL SECURITY;
ALTER TABLE lms.enrollments ENABLE ROW LEVEL SECURITY;
ALTER TABLE lms.enrollments FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS lms_courses_tenant_select ON lms.courses;
CREATE POLICY lms_courses_tenant_select
    ON lms.courses
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS lms_courses_tenant_insert ON lms.courses;
CREATE POLICY lms_courses_tenant_insert
    ON lms.courses
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS lms_courses_tenant_update ON lms.courses;
CREATE POLICY lms_courses_tenant_update
    ON lms.courses
    FOR UPDATE
    USING (tenant_id = collabio.current_tenant_id())
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS lms_courses_no_hard_delete ON lms.courses;
CREATE POLICY lms_courses_no_hard_delete
    ON lms.courses
    FOR DELETE
    USING (false);

DROP POLICY IF EXISTS lms_enrollments_tenant_select ON lms.enrollments;
CREATE POLICY lms_enrollments_tenant_select
    ON lms.enrollments
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS lms_enrollments_tenant_insert ON lms.enrollments;
CREATE POLICY lms_enrollments_tenant_insert
    ON lms.enrollments
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS lms_enrollments_tenant_update ON lms.enrollments;
CREATE POLICY lms_enrollments_tenant_update
    ON lms.enrollments
    FOR UPDATE
    USING (tenant_id = collabio.current_tenant_id())
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS lms_enrollments_no_hard_delete ON lms.enrollments;
CREATE POLICY lms_enrollments_no_hard_delete
    ON lms.enrollments
    FOR DELETE
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA lms TO collabio_app';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE lms.courses TO collabio_app';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE lms.enrollments TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA lms TO collabio_worker';
        EXECUTE 'GRANT SELECT ON TABLE lms.courses TO collabio_worker';
        EXECUTE 'GRANT SELECT ON TABLE lms.enrollments TO collabio_worker';
    END IF;
END
$$;

UPDATE collabio.module_catalog
SET required_migration_versions = '["0007", "0008", "0009", "0010", "0011", "0046"]'::jsonb
WHERE module_id = 'lms'
  AND status = 'not_installed';
