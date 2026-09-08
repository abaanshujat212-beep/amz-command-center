-- Bootstrap tenant discovery from a valid session before tenant selection.
-- A user ID alone is never sufficient to enumerate memberships.
create or replace function public.session_memberships(p_token text)
returns table(tenant_id text, name text, slug text, role text)
language sql security definer
set search_path = pg_catalog
set row_security = off
as $$
  select t.id::text, t.name, t.slug, m.role
  from auth.auth_session s
  join public.tenant_member m on m.user_id = s.user_id
  join public.tenant t on t.id = m.tenant_id
  where s.token = p_token and s.expires_at > now() and t.status = 'active'
  order by t.name
$$;
revoke all on function public.session_memberships(text) from public;
grant execute on function public.session_memberships(text) to axaty_app;
