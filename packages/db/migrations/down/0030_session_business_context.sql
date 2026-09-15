drop function if exists public.session_workspace_tenant_authorization(text, uuid, uuid);

alter table auth.auth_session
  drop column if exists active_ads_profile_id,
  drop column if exists active_marketplace_context_id,
  drop column if exists active_channel_account_id,
  drop column if exists active_brand_id,
  drop column if exists active_workspace_id;
