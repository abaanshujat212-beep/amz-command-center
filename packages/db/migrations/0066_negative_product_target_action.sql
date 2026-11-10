-- Enable the explicit, approval-gated negative product target action type.
alter table action drop constraint action_action_type_check;

alter table action
  add constraint action_action_type_check
  check (action_type in ('set_bid','set_budget','pause','enable',
                         'add_negative_exact','add_negative_phrase','add_negative_product',
                         'create_keyword','set_placement_modifier','flag'));
