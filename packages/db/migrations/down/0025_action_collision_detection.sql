drop function if exists detect_action_collision(uuid,text,text,uuid,timestamptz);
drop index if exists uq_action_one_active_entity_change;
drop table if exists entity_change_signal;
