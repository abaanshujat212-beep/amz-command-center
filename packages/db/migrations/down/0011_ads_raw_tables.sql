-- down/0011_ads_raw_tables.sql
-- Drop first-pass Ads raw landing tables.

drop table if exists raw.raw_ads_sp_purchased_product_daily;
drop table if exists raw.raw_ads_advertised_product_daily;
drop table if exists raw.raw_ads_sp_search_term_daily;
drop table if exists raw.raw_ads_sp_keyword_daily;
drop table if exists raw.raw_ads_sp_ad_group_daily;
drop table if exists raw.raw_ads_sp_placement_daily;
drop table if exists raw.raw_ads_sp_campaign_daily;

-- Keep the raw schema if other raw sources exist or future migrations use it.
