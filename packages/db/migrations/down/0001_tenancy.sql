-- Down: 0001_tenancy.sql
--
-- Structural migration, so it ships a reverse. cascade is deliberate: it
-- takes the RLS policies, indexes and foreign keys with each table, which is
-- why 0002's down does not need to run first for this to succeed.

drop table if exists audit_log cascade;
drop table if exists pipeline_run cascade;
drop table if exists sync_watermark cascade;
drop table if exists selling_account cascade;
drop table if exists ads_profile cascade;
drop table if exists amazon_connection cascade;
drop table if exists tenant_quota cascade;
drop table if exists tenant_settings cascade;
drop table if exists tenant_member cascade;
drop table if exists tenant cascade;

drop function if exists set_tenant(uuid);
