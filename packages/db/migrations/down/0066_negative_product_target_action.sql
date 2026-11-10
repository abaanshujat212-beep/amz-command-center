do $$ begin
  if exists (select 1 from action where action_type='add_negative_product') then
    raise exception 'cannot remove add_negative_product while action rows exist';
  end if;
end $$;

alter table action drop constraint if exists action_action_type_check;
alter table action
  add constraint action_action_type_check
  check (action_type in ('set_bid','set_budget','pause','enable',
                         'add_negative_exact','add_negative_phrase',
                         'create_keyword','set_placement_modifier','flag'));
