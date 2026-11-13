-- Rollback restores the historical CRUD privileges inherited from 0002.
grant update, delete on table action_experiment_outcome to axaty_app;
