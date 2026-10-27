-- 0068_productivity_pilot_real_user_runtime_policy_name.sql
-- Replace PostgreSQL's automatically truncated identifier with an explicit stable policy name.

ALTER POLICY productivity_pilot_real_user_runtime_observations_no_hard_delet
    ON collabio.productivity_pilot_real_user_runtime_observations
    RENAME TO productivity_pilot_real_user_runtime_obs_no_hard_delete;
