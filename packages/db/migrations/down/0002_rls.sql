-- Down: 0002_rls.sql
--
-- Removes the policies and turns RLS off again. Kept separate from 0001 so a
-- policy change can be reverted without dropping any data.
--
-- Note the order inside each block: drop the policy first, then NO FORCE,
-- then DISABLE. Leaving FORCE on a table with no policy would lock even the
-- owner out of every row -- a far worse state than no RLS at all.

drop policy if exists tenant_self on tenant;
alter table tenant no force row level security;
alter table tenant disable row level security;

drop policy if exists tenant_isolation on tenant_member;
alter table tenant_member no force row level security;
alter table tenant_member disable row level security;

drop policy if exists tenant_isolation on tenant_settings;
alter table tenant_settings no force row level security;
alter table tenant_settings disable row level security;

drop policy if exists tenant_isolation on tenant_quota;
alter table tenant_quota no force row level security;
alter table tenant_quota disable row level security;

drop policy if exists tenant_isolation on amazon_connection;
alter table amazon_connection no force row level security;
alter table amazon_connection disable row level security;

drop policy if exists tenant_isolation on ads_profile;
alter table ads_profile no force row level security;
alter table ads_profile disable row level security;

drop policy if exists tenant_isolation on selling_account;
alter table selling_account no force row level security;
alter table selling_account disable row level security;

drop policy if exists tenant_isolation on sync_watermark;
alter table sync_watermark no force row level security;
alter table sync_watermark disable row level security;

drop policy if exists tenant_isolation on pipeline_run;
alter table pipeline_run no force row level security;
alter table pipeline_run disable row level security;

drop policy if exists tenant_isolation on audit_log;
alter table audit_log no force row level security;
alter table audit_log disable row level security;
