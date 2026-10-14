-- Evidence snapshots and feedback proposals for contextual Copilot explanations.
-- Neither table is an execution/configuration surface.
create table copilot_decision_explanation (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  action_id uuid not null,
  actor_user_id uuid not null references auth.auth_user(id),
  context jsonb not null check (jsonb_typeof(context) = 'object'),
  narrative text not null check (btrim(narrative) <> ''),
  evidence jsonb not null check (jsonb_typeof(evidence) = 'array' and jsonb_array_length(evidence) > 0),
  created_at timestamptz not null default clock_timestamp(),
  unique (id, tenant_id),
  foreign key (action_id, tenant_id) references action(id, tenant_id) on delete restrict
);

create table copilot_feedback_proposal (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  explanation_id uuid not null,
  actor_user_id uuid not null references auth.auth_user(id),
  feedback text not null check (feedback in ('helpful','not_helpful','request_review')),
  comment text,
  status text not null default 'pending_review' check (status = 'pending_review'),
  created_at timestamptz not null default clock_timestamp(),
  foreign key (explanation_id, tenant_id)
    references copilot_decision_explanation(id, tenant_id) on delete restrict,
  check (feedback <> 'request_review' or btrim(coalesce(comment, '')) <> '')
);

create index copilot_decision_explanation_action_idx
  on copilot_decision_explanation(tenant_id, action_id, created_at desc);
create index copilot_feedback_proposal_review_idx
  on copilot_feedback_proposal(tenant_id, status, created_at desc);

create trigger copilot_decision_explanation_immutable before update on copilot_decision_explanation
  for each row execute function protect_configuration_version();
create trigger copilot_feedback_proposal_immutable before update on copilot_feedback_proposal
  for each row execute function protect_configuration_version();

do $$ declare t text; begin
  foreach t in array array['copilot_decision_explanation','copilot_feedback_proposal'] loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format('create policy tenant_isolation on %I using (tenant_id=nullif(current_setting(''app.tenant_id'',true),'''')::uuid) with check (tenant_id=nullif(current_setting(''app.tenant_id'',true),'''')::uuid)', t);
  end loop;
end $$;

grant select, insert on copilot_decision_explanation, copilot_feedback_proposal to axaty_app;
