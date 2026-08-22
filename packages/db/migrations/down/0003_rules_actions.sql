-- Down: 0003_rules_actions.sql
--
-- Structural. Drops the rules/actions half of the schema. The view goes
-- first because it depends on action.

drop view if exists v_changes_today;

drop table if exists alert cascade;
drop table if exists sku_cost_ledger cascade;
drop table if exists rule_evaluation cascade;
drop table if exists action cascade;
drop table if exists rule cascade;
