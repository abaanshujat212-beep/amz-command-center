-- 0025_action_collision_detection.sql
-- Tenant-scoped pre-approval collision evidence and active action exclusion.

create table if not exists entity_change_signal (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenant(id) on delete cascade,
  marketplace_id  text,
  entity_type     text not null,
  entity_id       text not null,
  source           text not null check (source in ('manual','amazon_native')),
  change_kind      text not null,
  source_ref       text,
  observed_at      timestamptz not null,
  expires_at       timestamptz not null,
  evidence         jsonb not null default '{}'::jsonb,
  recorded_at      timestamptz not null default now(),
  check (expires_at > observed_at),
  unique (tenant_id, source, source_ref)
);

create index if not exists idx_entity_change_signal_active
  on entity_change_signal (tenant_id, entity_type, entity_id, expires_at desc);

-- A diagnostic flag is not a financial mutation and does not claim the entity.
-- Existing proposal creation uses ON CONFLICT DO NOTHING, so concurrent rule
-- runs deterministically retain the first active proposal without an exception.
create unique index if not exists uq_action_one_active_entity_change
  on action (tenant_id, entity_type, entity_id)
  where status in ('pending','approved') and action_type <> 'flag';

create or replace function detect_action_collision(
  p_tenant_id uuid,
  p_entity_type text,
  p_entity_id text,
  p_candidate_action_id uuid default null,
  p_at timestamptz default now()
)
returns table (
  collision_kind text,
  conflicting_action_id uuid,
  change_signal_id uuid,
  evidence jsonb
)
language sql
stable
security invoker
set search_path = public, pg_temp
as $$
  with collisions as (
    select
      1 as priority,
      'active_action'::text as collision_kind,
      a.id as conflicting_action_id,
      null::uuid as change_signal_id,
      jsonb_build_object(
        'status', a.status,
        'action_type', a.action_type,
        'requested_at', a.requested_at
      ) as evidence
    from action a
    where a.tenant_id = p_tenant_id
      and a.entity_type = p_entity_type
      and a.entity_id = p_entity_id
      and a.action_type <> 'flag'
      and a.status in ('pending','approved')
      and (p_candidate_action_id is null or a.id <> p_candidate_action_id)

    union all

    select
      case s.source when 'manual' then 2 else 3 end,
      (s.source || '_change')::text,
      null::uuid,
      s.id,
      jsonb_build_object(
        'source', s.source,
        'change_kind', s.change_kind,
        'source_ref', s.source_ref,
        'observed_at', s.observed_at,
        'expires_at', s.expires_at
      ) || s.evidence
    from entity_change_signal s
    where s.tenant_id = p_tenant_id
      and s.entity_type = p_entity_type
      and s.entity_id = p_entity_id
      and s.observed_at <= p_at
      and s.expires_at > p_at

    union all

    select
      4,
      'recent_axaty_change'::text,
      a.id,
      null::uuid,
      jsonb_build_object(
        'status', a.status,
        'action_type', a.action_type,
        'applied_at', a.applied_at
      )
    from action a
    where a.tenant_id = p_tenant_id
      and a.entity_type = p_entity_type
      and a.entity_id = p_entity_id
      and a.action_type <> 'flag'
      and a.status in ('applied','verified','rolled_back')
      and a.applied_at is not null
      and a.applied_at > p_at - interval '72 hours'
      and (p_candidate_action_id is null or a.id <> p_candidate_action_id)
  )
  select collision_kind, conflicting_action_id, change_signal_id, evidence
  from collisions
  order by priority, coalesce((evidence->>'requested_at')::timestamptz,
                              (evidence->>'observed_at')::timestamptz,
                              (evidence->>'applied_at')::timestamptz) desc nulls last
  limit 1
$$;

alter table entity_change_signal enable row level security;
alter table entity_change_signal force row level security;
drop policy if exists tenant_isolation on entity_change_signal;
create policy tenant_isolation on entity_change_signal
  using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

grant select, insert on entity_change_signal to axaty_app;
revoke update, delete on entity_change_signal from axaty_app;
revoke all on function detect_action_collision(uuid,text,text,uuid,timestamptz) from public;
grant execute on function detect_action_collision(uuid,text,text,uuid,timestamptz) to axaty_app;
