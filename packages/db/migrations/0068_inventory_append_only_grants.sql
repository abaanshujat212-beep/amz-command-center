-- 0002 grants CRUD to future public tables through ALTER DEFAULT PRIVILEGES.
-- 0067's narrower GRANT is additive: explicitly remove inherited history writes.
revoke update, delete, truncate on table inventory_position_snapshot from axaty_app;
grant select, insert on table inventory_position_snapshot to axaty_app;

-- Deleting a location cascades its snapshots, so location removal is restricted too.
-- Keep metadata/active-state updates; tenant erasure remains a separate lifecycle.
revoke delete, truncate on table inventory_location from axaty_app;
grant select, insert, update on table inventory_location to axaty_app;
