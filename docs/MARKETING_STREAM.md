# Amazon Marketing Stream architecture and blocked state

Status: design only. As of 2026-11-13, do not create subscriptions, AWS
destinations, workers, or production rows until Amazon Ads API access and an
approved AWS destination are available. This design follows Amazon Marketing
Stream Version 2 (Stream v2); older examples that describe direct Firehose
messages or Version 1 notification datasets are not the implementation
contract.

## Readiness contract

Use the existing `external_dependency_state` row for the tenant and marketplace
with `module_key = 'ppc'`, `dependency_key = 'amazon_marketing_stream'`, and
`readiness_state = 'WAITING_FOR_MARKETING_STREAM'` while access or delivery is
unavailable. The readiness enum already supports this state. Keep module
visibility separate from dependency readiness. A blocked dependency is a
status, not a dataset: do not insert placeholder hourly rows, zero metrics, or
synthetic delivery events.

Only set `LIVE_READY` after an authenticated subscription and its destination
have been verified for the applicable advertiser account, marketplace, API
version, and tenant. Store evidence source and observation time as required by
the readiness schema. Never put credentials, tokens, or raw authorization
material in readiness metadata or audit details.

## Version 2 delivery model

Stream v2 is a push delivery of data files, not a sequence of metric deltas.
The configured destination consists of an S3 bucket for Parquet data and an
SQS queue for delivery notifications. An SQS notification identifies the
dataset and batch and supplies one or more S3 object URIs. A notification can
be split into multiple messages with the same delivery, dataset, and batch
metadata but different URI subsets. Consume each notification independently;
do not wait for or assemble a complete batch.

The exact dataset IDs, supported account types, dimensions, metric fields,
cadence, grain, and restatement window must come from the current Amazon Ads
API dataset catalog and the authorized subscription response. Keep this
catalog/API version with the ingest contract. Dataset delivery cadence can
differ from the hourly or daily grain of the records; do not infer one from
the other. A subscription may also cause historical restatement-period data
to arrive, so the initial load must use the same idempotent path as ongoing
delivery.

## Ingestion path

1. An operator records Ads API authorization and destination readiness. The
   S3 bucket and SQS queue must be in an Amazon-supported, matching region and
   their policies must grant only the required Stream service access.
2. A tenant-scoped subscription is created for one authorized advertiser
   account and an explicitly reviewed dataset. Manager accounts and multi-
   advertiser requests are not valid substitutes for advertiser-scoped
   subscriptions.
3. The worker receives an SQS notification, validates its schema and expected
   dataset, and durably records the notification before acknowledging it.
   Retries must be safe if the same files or records arrive again.
4. The worker downloads every listed S3 object, validates Parquet schema and
   advertiser scope, and stores source metadata alongside the raw record:
   dataset/API version, advertiser account, record dimensions, batch version,
   source time window, arrival time, and source object reference.
5. Normalize into the hourly/daily staging model only after schema and scope
   validation. Preserve the source grain and nulls. A null means unavailable
   or inapplicable; it must not be converted to zero.
6. For a repeated record key, retain the record with the highest batch
   version. Key records using all documented dimension fields, not the S3 key,
   delivery ID, or batch ID. A later version is a restatement of the total for
   that record/window, not an additive delta.
7. Publish pipeline-run and freshness state through existing ingestion and
   readiness surfaces. Data from this stream can inform proposals, but must
   not trigger an Amazon mutation without the existing approval and action
   worker controls.

## Retry, replay, and retention

Use bounded retry with backoff for transient SQS/S3 and database failures.
After the configured receive limit, send the notification to a dead-letter
queue and raise a tenant-safe operational alert. Keep the original notification
and object references so an operator can replay them through the same
idempotent path after correcting the failure. Do not claim a delivery is
complete merely because an SQS message was received; completion requires all
listed objects to be processed or explicitly quarantined.

Retain raw objects and normalized records only under the product's approved
data-retention policy. Record deletion and replay behavior before production
access is enabled. Monitor subscription status, queue age/depth, dead-letter
count, object-processing failures, schema changes, and per-dataset freshness.
Dataset cadence and allowed regions are configuration from the current API
catalog, not hard-coded assumptions.

## Security boundaries

- Resolve advertiser account to tenant through the authorized account mapping;
  never trust a notification alone to select a tenant.
- Validate every record's advertiser dimensions before persistence and enforce
  tenant isolation in database access.
- Keep AWS credentials in the existing secret-management boundary and scope
  policies to the dedicated destination. Do not reuse a bucket containing
  unrelated application objects.
- Treat dataset schemas and payloads as external input. Reject or quarantine
  unknown schema versions instead of coercing fields silently.
- Stream v2 has no Amazon usage fee, but S3, SQS, KMS, and query/storage use may
  incur AWS costs. Estimate and monitor those costs before enabling a tenant.

## Existing project seams

Reuse the tenant/marketplace readiness schema in migration `0021`, pipeline
run history, raw-to-staging dbt flow, tenant transaction helpers, and shared
endpoint/rate-limit catalog. Add subscription and dataset contracts only
after current API access is available for verification. Do not create a
parallel module-visibility, alert, or tenant model.

## Current sources

- [Amazon Ads API: Stream v2 FAQ](https://advertising.amazon.com/API/docs/en-us/guides/amazon-marketing-stream/v2/faq)
- [Amazon Ads API: Set up your Stream v2 destination](https://advertising.amazon.com/API/docs/en-us/guides/amazon-marketing-stream/v2/set-up-your-destination)
- [Amazon Ads: Amazon Marketing Stream overview](https://advertising.amazon.com/solutions/products/amazon-marketing-stream)

These sources were checked on 2026-11-13. Re-check the API version, dataset
catalog, delivery guarantees, and regional requirements before implementation.
