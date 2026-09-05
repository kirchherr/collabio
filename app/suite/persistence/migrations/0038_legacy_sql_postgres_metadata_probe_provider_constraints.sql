-- 0038_legacy_sql_postgres_metadata_probe_provider_constraints.sql
-- Allow the metadata-only Legacy SQL connector chain to carry PostgreSQL provider evidence.
-- This does not enable raw data reads, import dry-runs, import writes, or destructive actions.

ALTER TABLE collabio.legacy_sql_host_profile_release_gate_evidence
    DROP CONSTRAINT IF EXISTS legacy_sql_host_profile_release_gate_evide_connector_kind_check;

ALTER TABLE collabio.legacy_sql_host_profile_release_gate_evidence
    DROP CONSTRAINT IF EXISTS legacy_sql_host_profile_release_gate_connector_kind_supported_check;

ALTER TABLE collabio.legacy_sql_host_profile_release_gate_evidence
    ADD CONSTRAINT legacy_sql_host_profile_release_gate_connector_kind_supported_check
    CHECK (connector_kind IN ('sqlserver', 'postgres'));

ALTER TABLE collabio.legacy_sql_metadata_worker_queue
    DROP CONSTRAINT IF EXISTS legacy_sql_metadata_worker_queue_connector_kind_check;

ALTER TABLE collabio.legacy_sql_metadata_worker_queue
    DROP CONSTRAINT IF EXISTS legacy_sql_metadata_worker_queue_connector_kind_supported_check;

ALTER TABLE collabio.legacy_sql_metadata_worker_queue
    ADD CONSTRAINT legacy_sql_metadata_worker_queue_connector_kind_supported_check
    CHECK (connector_kind IN ('sqlserver', 'postgres'));
