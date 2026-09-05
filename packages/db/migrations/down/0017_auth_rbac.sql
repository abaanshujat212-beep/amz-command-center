drop index if exists tenant_member_one_owner;
alter table tenant_member drop constraint if exists tenant_member_role_check;
alter table tenant_member add constraint tenant_member_role_check
  check (role in ('owner','admin','analyst','viewer'));
drop schema if exists auth cascade;
