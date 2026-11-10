import re

from services.rules.query import build_candidate_sql


def test_search_term_query_carries_only_unambiguous_negative_destinations():
    sql = re.sub(r"\s+", " ", build_candidate_sql("search_term", "true"))
    assert "min(campaign_id)::text as source_campaign_id" in sql
    assert "min(ad_group_id)::text as source_ad_group_id" in sql
    assert "count(distinct campaign_id) as source_campaign_count" in sql
    assert "count(distinct ad_group_id) as source_ad_group_count" in sql
