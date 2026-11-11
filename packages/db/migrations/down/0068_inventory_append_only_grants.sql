-- Rollback deliberately restores the pre-0068 CRUD privileges inherited from 0002.
-- This weakens inventory history protection; use only as an explicit migration rollback.
-- TRUNCATE was not part of the historical defaults and is not restored.
grant update, delete on table inventory_position_snapshot to axaty_app;
grant delete on table inventory_location to axaty_app;
