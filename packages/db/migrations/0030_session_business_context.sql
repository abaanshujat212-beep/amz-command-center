-- 0030_session_business_context.sql
-- Optional active hierarchy pointers. They are untrusted session state and must
-- be revalidated before use; existing tenant-only sessions remain valid.

alter table auth.auth_session
  add column active_workspace_id uuid references public.workspace(id) on delete set null,
  add column active_brand_id uuid,
  add column active_channel_account_id uuid,
  add column active_marketplace_context_id uuid,
  add column active_ads_profile_id uuid;

create function public.session_workspace_tenant_authorization(
  p_token text,
  p_workspace_id uuid,
  p_tenant_id uuid
)
returns table(
  workspace_role text,
  can_view_portfolio boolean,
  can_operate_tenants boolean
)
language sql
security definer
set search_path = pg_catalog
set row_security = off
as $$
  select m.role, m.can_view_portfolio, m.can_operate_tenants
    from auth.auth_session s
    join public.workspace_member m
      on m.user_id = s.user_id and m.workspace_id = p_workspace_id
    join public.workspace w on w.id = m.workspace_id
    join public.workspace_entitlement e on e.workspace_id = w.id
    join public.workspace_tenant wt
      on wt.workspace_id = w.id and wt.tenant_id = p_tenant_id
   where s.token = p_token
     and s.expires_at > now()
     and w.status = 'active'
     and e.portfolio_enabled = true
     and m.can_operate_tenants = true
$$;

revoke all on function public.session_workspace_tenant_authorization(text, uuid, uuid)
  from public;
grant execute on function public.session_workspace_tenant_authorization(text, uuid, uuid)
  to axaty_app;
