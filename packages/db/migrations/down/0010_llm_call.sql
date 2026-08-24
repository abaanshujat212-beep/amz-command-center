-- Down for 0010.
--
-- Dropping llm_call loses the cost and token history for every tenant. There is
-- no second copy: the provider's invoice is the only other record, and it is
-- neither per-tenant nor per-request. Export before reversing this in anything
-- other than local development.

drop view if exists v_llm_spend_this_month;

drop index if exists idx_llm_call_tenant_month;
drop index if exists idx_llm_call_tenant_started;

drop policy if exists tenant_isolation on llm_call;

drop table if exists llm_call;
