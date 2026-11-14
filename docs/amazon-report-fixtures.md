# Offline Amazon report fixture inspection

Use `services.ingest.fixture_inspector` to check a sanitized Ads or Sales & Traffic report file with the same parsers and row normalizers used by ingestion. The command makes no database connection, does not call Amazon, and never prints report contents.

```sh
uv run --locked python -m services.ingest.fixture_inspector \
  --provider ads_api \
  --dataset ads_sp_campaign_daily \
  --file /private/fixtures/ads-campaign.json.gz \
  --fallback-date 2026-11-01

uv run --locked python -m services.ingest.fixture_inspector \
  --provider sp_api \
  --dataset sales_traffic_asin_daily \
  --file /private/fixtures/sales-traffic.json.gz \
  --fallback-date 2026-11-01
```

The JSON summary reports record counts by source date, duplicate keys that would collide in the raw-table grain, the fixture filename and SHA-256 digest. Rows with invalid structures or missing entity identifiers fail inspection instead of being silently discarded. Only use sanitized files; these reports may contain commercially sensitive seller data. Fixture inspection never writes into tenant tables, so it cannot advance production watermarks or contaminate marts.
