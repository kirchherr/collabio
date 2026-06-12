DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        CREATE ROLE collabio_app LOGIN PASSWORD 'collabio_app';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        CREATE ROLE collabio_worker LOGIN PASSWORD 'collabio_worker';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_audit_writer') THEN
        CREATE ROLE collabio_audit_writer LOGIN PASSWORD 'collabio_audit_writer';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_authz_admin') THEN
        CREATE ROLE collabio_authz_admin LOGIN PASSWORD 'collabio_authz_admin';
    END IF;
END
$$;
