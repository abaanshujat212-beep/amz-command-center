-- 0004_fix_changes_today.sql
-- Repair the daily-change guardrail lookup.
--
-- The original view read after_value->>'budget' / before_value->>'budget', but
-- the rules engine writes {"value": n} for every action type. Postgres returns
-- NULL for a missing JSON key rather than erroring, so the view kept reporting
-- budget_delta_today = 0 and the 'max budget increase per day' guardrail could
-- never fire. A guardrail that silently always passes is worse than no
-- guardrail, because it is trusted.
--
-- Also narrows the sum to set_budget actions and to INCREASES only. A rule that
-- cuts a budget must not create headroom for another rule to raise one.

create or replace view v_changes_today as
with today as (

    select
        tenant_id,
        action_type,
        (before_value->>'value')::numeric as before_num,
        (after_value ->>'value')::numeric as after_num
    from action
    where status in ('applied', 'verified')
      and applied_at >= date_trunc('day', now())

)

select
    tenant_id,
    count(*) as applied_today,
    coalesce(
        sum(
            case
                when action_type = 'set_budget'
                     and after_num is not null
                then greatest(after_num - coalesce(before_num, 0), 0)
            end
        ),
        0
    ) as budget_delta_today
from today
group by 1;

grant select on v_changes_today to axaty_app;
