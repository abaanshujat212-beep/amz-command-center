# SP-API sandbox Sales & Traffic smoke

This is a UK, one-day Reports API test. Configure a disposable **local** PostgreSQL database with a different name from the normal pipeline database. Run the existing migrations and seed a throwaway tenant there. Do not run this against production or reuse live credentials.

Supply dedicated sandbox-only values through your local secret/environment configuration (never commit these):

- `SPAPI_SANDBOX_DATABASE_URL`: loopback connection for the disposable database. Do not set `DATABASE_URL` to the same database when running the smoke.
- `SPAPI_SANDBOX_CLIENT_ID`, `SPAPI_SANDBOX_CLIENT_SECRET`, `SPAPI_SANDBOX_REFRESH_TOKEN`: approved sandbox credentials. There is no credential fallback to the live pipeline or its vault.

Run the isolated smoke with the disposable tenant UUID:

```bash
python -m services.ingest.pipelines.sales_traffic --tenant-id <disposable-tenant-uuid> --sandbox
```

The runner uses only the official EU sandbox endpoint and the UK marketplace (`A1F83G8C2ARO7P`). It requests yesterday's `DAY` / `CHILD` Sales & Traffic report, or the day before `--today YYYY-MM-DD`. Nonempty, unique ASIN/day rows are required: an empty, unsupported or incompatible sandbox response is a blocker, not a success. The runner exercises normal raw upserts twice to verify duplicate-free replay, then rolls back. It never advances the regular watermark, records production freshness or persists sandbox token changes. Do not save or share credential values, signed URLs or raw report bodies.

On success the command prints only the date, market, row count and replay/rollback result. On failure it exits nonzero with the safe diagnostic. Record the observed result in #94 and note whether the sandbox could supply a suitable one-day payload. Sandbox output does not prove production Ads consent, production report coverage, or KPI reconciliation.
