drop table if exists tenant_role_template;
alter table tenant_member drop column if exists access_scopes;
