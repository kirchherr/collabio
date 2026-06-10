DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        CREATE ROLE collabio_app LOGIN PASSWORD 'collabio_app';
    END IF;
END
$$;
