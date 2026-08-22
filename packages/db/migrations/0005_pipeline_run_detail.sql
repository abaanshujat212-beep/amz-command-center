-- 0005_pipeline_run_detail.sql
-- The rules engine records a per-run summary (rules run, entities evaluated,
-- matched, proposed, and a count per guardrail that blocked something). That
-- summary is the only way to answer "why did nothing get proposed today?"
-- without re-running the engine, so it needs somewhere to live.

alter table pipeline_run
  add column if not exists detail jsonb;

-- Runs that are not tied to an ingest window (like rules evaluation) leave
-- date_from/date_to null, so make the intent explicit rather than implied.
comment on column pipeline_run.detail is
  'Free-form run summary. For dataset=rules_evaluate this is the RunSummary '
  'dataclass: rules_run, entities_evaluated, matched, proposed, blocked{}, errors[].';
