-- 0002 grants CRUD to future public tables by default. Keep experiment
-- outcomes as append-only evidence by removing inherited mutation privileges.
revoke update, delete, truncate on table action_experiment_outcome from axaty_app;
grant select, insert on table action_experiment_outcome to axaty_app;
