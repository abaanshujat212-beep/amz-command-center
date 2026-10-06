drop function if exists validate_report_schedule_timezone() cascade;
drop table if exists report_delivery_run;
drop table if exists report_delivery_schedule;

create or replace function route_alert_to_notification()
returns trigger
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  v_event_id uuid;
  v_source text;
  v_source_ref text;
  v_dedupe_key text;
begin
  if new.detail ? 'notification_source' then
    v_source := new.detail->>'notification_source';
    if v_source not in ('scheduler','action_worker','inventory_engine','internal') then
      raise exception 'unsupported notification source: %', v_source;
    end if;
  elsif new.detail ? 'scheduler_kind' then
    v_source := 'scheduler';
  elsif new.detail ? 'action_id' or new.detail->>'provider' = 'ads_api' then
    v_source := 'action_worker';
  else
    v_source := 'internal';
  end if;

  v_source_ref := coalesce(
    nullif(new.detail->>'notification_source_ref', ''),
    nullif(new.entity_ref, ''),
    new.id::text
  );
  v_dedupe_key := coalesce(nullif(new.dedupe_key, ''), new.id::text);

  insert into notification_event (
    tenant_id,event_type,source,source_ref,dedupe_key,severity,title,payload,occurred_at
  ) values (
    new.tenant_id,new.kind,v_source,v_source_ref,v_dedupe_key,new.severity,new.title,
    coalesce(new.detail->'event_payload',new.detail,'{}'::jsonb),new.created_at
  )
  on conflict (tenant_id,source,dedupe_key) do nothing
  returning id into v_event_id;

  if v_event_id is null then
    select id into v_event_id from notification_event
     where tenant_id = new.tenant_id and source = v_source and dedupe_key = v_dedupe_key;
  end if;

  update alert set notification_event_id = v_event_id where id = new.id;

  insert into notification_delivery (
    tenant_id,event_id,channel,status,attempt,retry_eligible,alert_id,
    cost_amount,delivered_at
  ) values (
    new.tenant_id,v_event_id,'in_app','DELIVERED',1,false,new.id,0,new.created_at
  ) on conflict (tenant_id,event_id,channel) do nothing;

  insert into notification_delivery (
    tenant_id,event_id,channel,status,attempt,retry_eligible,error,cost_amount
  )
  select new.tenant_id,v_event_id,channel,'BLOCKED_CONFIGURATION',0,false,
         'channel is not configured',0
    from unnest(array['email','whatsapp','sms']::text[]) as channel
  on conflict (tenant_id,event_id,channel) do nothing;

  return new;
end
$$;

alter table notification_consent_event drop constraint if exists notification_consent_event_purpose_check;
alter table notification_consent_event add constraint notification_consent_event_purpose_check
  check (purpose in ('operational_alert'));

alter table notification_route_preference drop constraint if exists notification_route_preference_event_type_check;
alter table notification_route_preference add constraint notification_route_preference_event_type_check check (event_type in (
  '*','auth_expiring','auth_expired','pipeline_failed','data_stale',
  'blast_radius_halt','budget_guard','action_failed','economics_incomplete',
  'low_inventory','projected_stockout','reorder_due','inbound_delayed',
  'excess_stock','unusual_demand'
));
alter table notification_event drop constraint if exists notification_event_source_check;
alter table notification_event add constraint notification_event_source_check check (source in (
  'scheduler','action_worker','inventory_engine','internal'
));
alter table notification_event drop constraint if exists notification_event_event_type_check;
alter table notification_event add constraint notification_event_event_type_check check (event_type in (
  'auth_expiring','auth_expired','pipeline_failed','data_stale',
  'blast_radius_halt','budget_guard','action_failed','economics_incomplete',
  'low_inventory','projected_stockout','reorder_due','inbound_delayed',
  'excess_stock','unusual_demand'
));
alter table alert drop constraint if exists alert_kind_check;
alter table alert add constraint alert_kind_check check (kind in (
  'auth_expiring','auth_expired','pipeline_failed','data_stale',
  'blast_radius_halt','budget_guard','action_failed','economics_incomplete',
  'low_inventory','projected_stockout','reorder_due','inbound_delayed',
  'excess_stock','unusual_demand'
));
