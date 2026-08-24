-- 0010_llm_call.sql
--
-- Per-tenant record of every LLM call: provider, model, tokens, cost, latency,
-- outcome.
--
-- Why a table and not a log line: with bring-your-own-key (#35) the client pays
-- the provider directly. Without this table their usage exists only on the
-- provider's invoice, which means a runaway retry loop is discovered at the end
-- of the month by an accountant instead of at minute two by a budget check.
--
-- Two of the rules below are constraints rather than good intentions, because a
-- rule enforced only in application code is a rule that survives exactly until
-- someone adds a second code path.

create table if not exists llm_call (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references tenant(id) on delete cascade,

  -- Links to audit_log rows written as entity = 'copilot:<request_id>' so one
  -- question can be traced from asked, to model calls, to answer. Nullable:
  -- not every call comes from a copilot request (rule explanations, voice).
  request_id        uuid,
  purpose           text not null,

  provider          text not null,
  model             text not null,

  status            text not null
                    check (status in ('success','refused','error','timeout','budget_exceeded')),

  attempt           smallint not null default 1 check (attempt >= 1),

  -- The provider we fell back FROM, when a 429 or 5xx moved this call elsewhere.
  -- Null on a first attempt.
  fallback_from     text,

  prompt_tokens     integer check (prompt_tokens is null or prompt_tokens >= 0),
  completion_tokens integer check (completion_tokens is null or completion_tokens >= 0),
  total_tokens      integer check (total_tokens is null or total_tokens >= 0),

  -- Providers bill in USD; the product reports in GBP. The two are NOT mixed
  -- here. Converting at write time would bake one day's FX rate into a permanent
  -- record and make last month's spend change every time the rate moves.
  cost_usd          numeric(12,6) check (cost_usd is null or cost_usd >= 0),
  currency          text not null default 'USD',

  latency_ms        integer check (latency_ms is null or latency_ms >= 0),
  error             text,

  started_at        timestamptz not null default now(),
  finished_at       timestamptz
);

comment on table llm_call is
  'One row per LLM request attempt, per tenant. Basis for budget enforcement and cost reporting.';
comment on column llm_call.cost_usd is
  'Provider cost in its own currency. Never converted at write time.';
comment on column llm_call.fallback_from is
  'Provider this attempt fell back from after a 429/5xx. Never set for a refusal.';

alter table llm_call
  drop constraint if exists llm_call_refusal_is_never_shopped;
alter table llm_call
  add constraint llm_call_refusal_is_never_shopped
  check (not (status = 'refused' and fallback_from is not null));

alter table llm_call
  drop constraint if exists llm_call_blocked_calls_cost_nothing;
alter table llm_call
  add constraint llm_call_blocked_calls_cost_nothing
  check (
    status <> 'budget_exceeded'
    or (coalesce(cost_usd, 0) = 0 and coalesce(total_tokens, 0) = 0)
  );

alter table llm_call enable row level security;
alter table llm_call force row level security;

drop policy if exists tenant_isolation on llm_call;
create policy tenant_isolation on llm_call
  using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

-- Budget reads filter by tenant and a started_at lower bound. Do not use a
-- date_trunc(timestamptz) expression index here: Postgres rejects it because the
-- expression depends on timezone settings and is not immutable.
create index if not exists idx_llm_call_tenant_started
  on llm_call (tenant_id, started_at desc);

create or replace view v_llm_spend_this_month as
select
    tenant_id,
    currency,
    sum(coalesce(cost_usd, 0))  as spend,
    sum(coalesce(total_tokens, 0)) as tokens,
    count(*)                    as calls,
    max(started_at)             as last_call_at
from llm_call
where started_at >= date_trunc('month', now())
group by tenant_id, currency;

comment on view v_llm_spend_this_month is
  'Spend so far this calendar month. Read before dispatch, never after.';

grant select, insert on llm_call to axaty_app;
grant select on v_llm_spend_this_month to axaty_app;
