-- 0071_productivity_pilot_real_user_runtime_owner_ref.sql
-- Prevent raw principal identifiers from entering the hash-only runtime through an owner reference.

ALTER TABLE collabio.productivity_pilot_real_user_runtime_windows
    ADD CONSTRAINT real_user_pilot_runtime_owner_ref_no_raw_principal CHECK (
        lower(window_record ->> 'operations_owner_ref') !~ '^(principal|user|subject):'
    );

COMMENT ON CONSTRAINT real_user_pilot_runtime_owner_ref_no_raw_principal
    ON collabio.productivity_pilot_real_user_runtime_windows IS
    'The operations owner is an opaque control reference, never a raw principal identifier.';
