# Third-party notices

This project studies open-source Amazon tooling and reimplements patterns rather than copying files.
Where code or model design is derived from a third party, it is listed here with its license.

## Wrapped / adopted libraries (installed as dependencies)

| Project | License | Use |
| --- | --- | --- |
| [python-amazon-sp-api](https://github.com/saleweaver/python-amazon-sp-api) | MIT | SP-API client, wrapped behind our own interface |
| [python-amazon-ad-api](https://github.com/denisneuf/python-amazon-ad-api) | MIT | Ads API client, wrapped behind our own interface |
| [dlt](https://github.com/dlt-hub/dlt) | Apache-2.0 | Extract/load pipelines |
| [dbt-core](https://github.com/dbt-labs/dbt-core) | Apache-2.0 | Transformations |
| [Better Auth](https://github.com/better-auth/better-auth) | MIT | Auth + organizations |
| [Metabase](https://github.com/metabase/metabase) | AGPL-3.0 (separate container, not linked) | Internal BI only |

## Design references (patterns studied, no files copied)

| Project | License | What we learned from it |
| --- | --- | --- |
| [amzn/selling-partner-api-models](https://github.com/amzn/selling-partner-api-models) | Apache-2.0 | Official report schemas — column names and types |
| [fivetran/dbt_amazon_ads](https://github.com/fivetran/dbt_amazon_ads) | verify before use | Mart layout for ad performance |
| [ScaleLeap/amazon-marketplaces](https://github.com/ScaleLeap/amazon-marketplaces) | verify before use | Marketplace ID / endpoint mapping |

## Rule

**Copy the pattern, not the file.** Any file-level reuse must be recorded above with its license before merge.
