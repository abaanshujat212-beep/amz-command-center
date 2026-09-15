-- 0031_portfolio_read_discovery.sql
-- Enumerate workspace-linked tenants for entitled portfolio readers without
-- granting tenant operation or exposing workspace tables to the app role.

create function public.session_workspace_portfolio_tenants(
  p_token text,
  p_workspace_id uuid,
  p_require_alerts boolean default false
)
returns table(
  tenant_id text,
  name text,
  slug text,
  role text
)
language sql
security definer
set search_path = pg_catalog
set row_security = off
as $$
  select t.id::text, t.name, t.slug, tm.role
    from auth.auth_session s
    join public.workspace_member wm
      on wm.user_id = s.user_id and wm.workspace_id = p_workspace_id
    join public.workspace w on w.id = wm.workspace_id
    join public.workspace_entitlement e on e.workspace_id = w.id
    join public.workspace_tenant wt on wt.workspace_id = w.id
    join public.tenant_member tm
      on tm.user_id = s.user_id and tm.tenant_id = wt.tenant_id
    join public.tenant t on t.id = tm.tenant_id
   where s.token = p_token
     and s.expires_at > now()
     and w.status = 'active'
     and t.status = 'active'
     and e.portfolio_enabled = true
     and e.cross_account_summary_enabled = true
     and wm.can_view_portfolio = true
     and (not p_require_alerts or e.portfolio_alerts_enabled = true)
   order by t.name, t.id
$$;

revoke all on function public.session_workspace_portfolio_tenants(text, uuid, boolean)
  from public;
grant execute on function public.session_workspace_portfolio_tenants(text, uuid, boolean)
  to axaty_app;
