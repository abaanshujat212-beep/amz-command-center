drop index if exists recommendation_entity_idx;
drop index if exists recommendation_filter_idx;
drop table if exists recommendation_evidence;
drop table if exists optimizer_run;
drop trigger if exists action_recommendation_metadata_immutable on action;
drop trigger if exists rule_evaluation_recommendation_metadata_immutable on rule_evaluation;
drop function if exists protect_optimizer_run();
drop function if exists protect_action_recommendation_metadata();
alter table action drop constraint if exists action_lookback_check, drop constraint if exists action_risk_check,
  drop constraint if exists action_confidence_check, drop constraint if exists action_recommendation_type_check,
  drop column if exists expected_behavior, drop column if exists economic_effect, drop column if exists strategy_snapshot,
  drop column if exists objective_snapshot, drop column if exists lookback_days, drop column if exists risk,
  drop column if exists confidence, drop column if exists recommendation_type;
alter table rule_evaluation drop constraint if exists rule_evaluation_lookback_check,
  drop constraint if exists rule_evaluation_risk_check, drop constraint if exists rule_evaluation_confidence_check,
  drop constraint if exists rule_evaluation_recommendation_type_check, drop constraint if exists uq_rule_evaluation_id_tenant,
  drop column if exists expected_behavior,
  drop column if exists economic_effect, drop column if exists strategy_snapshot, drop column if exists objective_snapshot,
  drop column if exists lookback_days, drop column if exists risk, drop column if exists confidence,
  drop column if exists recommendation_type;
