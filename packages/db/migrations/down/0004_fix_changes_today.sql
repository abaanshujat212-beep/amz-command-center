-- Down: 0004_fix_changes_today.sql
--
-- 0004 was a repair: `create or replace view v_changes_today` to fix a delta
-- that read after_value->>'budget' while the engine writes {"value": n}.
--
-- A literal inverse would restore that broken definition. It is not restored
-- on purpose -- reverting to a view whose guardrail silently always passed
-- has no value, and would reintroduce a defect that took a cross-read to
-- find. Instead the view is dropped, and `migrate up` recreates the fixed
-- one.
--
-- Consequence to be aware of: stopping here leaves 0003 applied without its
-- view. `services/rules/guardrails.py` reads v_changes_today for the daily
-- budget-increase cap, so run `up` again before running the engine.

drop view if exists v_changes_today;
