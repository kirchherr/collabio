-- 0070_productivity_pilot_real_user_closure_owner_refs.sql
-- Keep owner references opaque so the hash-only closure cannot persist raw principal identifiers.

ALTER TABLE collabio.productivity_pilot_real_user_closure_reports
    ADD CONSTRAINT real_user_pilot_closure_owner_refs_no_raw_principals CHECK (
        lower(closure_record ->> 'operations_owner_ref') !~ '^(principal|user|subject):'
        AND lower(closure_record ->> 'recovery_owner_ref') !~ '^(principal|user|subject):'
    );

COMMENT ON CONSTRAINT real_user_pilot_closure_owner_refs_no_raw_principals
    ON collabio.productivity_pilot_real_user_closure_reports IS
    'Owner references are opaque control references, never raw principal identifiers.';
