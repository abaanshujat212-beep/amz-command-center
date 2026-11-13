-- Read-only, tenant-scoped evidence for recorded same-entity changes that
-- overlap persisted verification measurement windows.
create function verification_confounding_evidence(
  p_tenant_id uuid,
  p_action_id uuid,
  p_horizon_days integer
)
returns table (
  confounding_status text,
  confounders jsonb,
  confounder_count integer,
  evidence_truncated boolean
)
language sql
stable
security invoker
set search_path=public,pg_temp
as $$
  with focal as (
    select a.tenant_id,a.id,a.entity_type,a.entity_id,s.status,
      (s.window_before_start::timestamp at time zone 'UTC') before_start,
      (s.window_before_end::timestamp at time zone 'UTC') before_end,
      (s.window_after_start::timestamp at time zone 'UTC') after_start,
      (s.window_after_end::timestamp at time zone 'UTC') after_end
    from action_verification_snapshot s
    join action a on a.id=s.action_id and a.tenant_id=s.tenant_id
    where s.tenant_id=p_tenant_id and s.action_id=p_action_id
      and s.horizon_days=p_horizon_days
  ), overlap_events as (
    -- An applied action is a point event. Only the focal action's apply event
    -- is excluded; its rollback is itself a material event in the window.
    select 'axaty'::text source,'baseline'::text window_name,
      other.action_type::text change_kind,null::text source_ref,
      other.applied_at changed_at,other.id::text action_id,null::text signal_id
    from focal f join action other on other.tenant_id=f.tenant_id
      and other.entity_type=f.entity_type and other.entity_id=f.entity_id
    where other.id<>f.id and other.action_type<>'flag'
      and other.status in ('applied','verified','rolled_back')
      and other.applied_at>=f.before_start and other.applied_at<f.before_end
    union all
    select 'axaty','after',other.action_type::text,null::text,
      other.applied_at,other.id::text,null::text
    from focal f join action other on other.tenant_id=f.tenant_id
      and other.entity_type=f.entity_type and other.entity_id=f.entity_id
    where other.id<>f.id and other.action_type<>'flag'
      and other.status in ('applied','verified','rolled_back')
      and other.applied_at>=f.after_start and other.applied_at<f.after_end
    union all
    select 'axaty','baseline',('rollback:'||other.action_type)::text,
      null::text,other.rolled_back_at,other.id::text,null::text
    from focal f join action other on other.tenant_id=f.tenant_id
      and other.entity_type=f.entity_type and other.entity_id=f.entity_id
    where other.action_type<>'flag' and other.rolled_back_at>=f.before_start
      and other.rolled_back_at<f.before_end
    union all
    select 'axaty','after',('rollback:'||other.action_type)::text,
      null::text,other.rolled_back_at,other.id::text,null::text
    from focal f join action other on other.tenant_id=f.tenant_id
      and other.entity_type=f.entity_type and other.entity_id=f.entity_id
    where other.action_type<>'flag' and other.rolled_back_at>=f.after_start
      and other.rolled_back_at<f.after_end
    union all
    -- expires_at is collision-detection TTL, not the historical event's effect
    -- interval. Confounding is based on observed_at falling inside the window.
    select signal.source::text,'baseline',signal.change_kind::text,
      signal.source_ref,signal.observed_at,null::text,signal.id::text
    from focal f join entity_change_signal signal on signal.tenant_id=f.tenant_id
      and signal.entity_type=f.entity_type and signal.entity_id=f.entity_id
    where signal.observed_at<=now() and signal.observed_at>=f.before_start
      and signal.observed_at<f.before_end
    union all
    select signal.source::text,'after',signal.change_kind::text,
      signal.source_ref,signal.observed_at,null::text,signal.id::text
    from focal f join entity_change_signal signal on signal.tenant_id=f.tenant_id
      and signal.entity_type=f.entity_type and signal.entity_id=f.entity_id
    where signal.observed_at<=now() and signal.observed_at>=f.after_start
      and signal.observed_at<f.after_end
  ), limited as (
    select * from overlap_events
    order by changed_at desc,source,window_name,change_kind,
      coalesce(source_ref,''),coalesce(action_id,signal_id,'')
    limit 20
  ), totals as (
    select count(*)::integer amount from overlap_events
  )
  select case when totals.amount>0 then 'CONFOUNDED'
      when focal.status='COMPLETE' then 'NO_RECORDED_CHANGES' else 'PENDING' end,
    coalesce((select jsonb_agg(jsonb_build_object(
      'source',limited.source,'window',limited.window_name,
      'change_kind',limited.change_kind,'source_ref',limited.source_ref,
      'changed_at',limited.changed_at,'action_id',limited.action_id,
      'signal_id',limited.signal_id
    ) order by limited.changed_at desc,limited.source,limited.window_name,
      limited.change_kind,coalesce(limited.source_ref,''),
      coalesce(limited.action_id,limited.signal_id,'')) from limited),'[]'::jsonb),
    totals.amount,totals.amount>(select count(*) from limited)
  from focal cross join totals
$$;

revoke all on function verification_confounding_evidence(uuid,uuid,integer) from public;
grant execute on function verification_confounding_evidence(uuid,uuid,integer) to axaty_app;
