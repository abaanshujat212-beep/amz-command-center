# SP-API sandbox setup

Use this flow when SP-API sandbox access is available and you want the app to fetch sandbox data for the single local tenant.

## 1. Fill local keys only

Copy `.env.example` to `.env` and fill these values locally. Do not commit `.env`.

```bash
SPAPI_CLIENT_ID=...
SPAPI_CLIENT_SECRET=...
SPAPI_REFRESH_TOKEN=...
SPAPI_REGION=eu
SPAPI_ENDPOINT=https://sandbox.sellingpartnerapi-eu.amazon.com
SPAPI_SELLER_ACCOUNT_ID=sandbox
MARKETPLACE_ID=A1F83G8C2ARO7P
DEV_TENANT_SLUG=dev
KEK_BASE64=...
KEK_VERSION=1
```

For the current local setup, the default tenant slug is `dev`, so you only need to put the keys in `.env` unless you intentionally seeded a different tenant.

## 2. Start local stack and seed tenant

```bash
make up
python -m packages.db.migrate up
python -m packages.db.seed --name "Dev Tenant" --slug dev
python -m packages.db.seed_spapi_sandbox
```

The sandbox seed command encrypts `SPAPI_REFRESH_TOKEN` before storing it in `amazon_connection`.

## 3. Run Sales & Traffic sandbox smoke

```bash
python -m services.ingest.pipelines.sales_traffic --tenant-id $(python - <<'PY'
from packages.db.seed import tenant_id_for
print(tenant_id_for('dev'))
PY
) --sandbox
```

If the sandbox reports API returns a limited or synthetic payload, paste the exact response/error on issue #94.

## 4. Keep Ads deferred

This setup is only for SP-API sandbox reads. Ads API testing and Ads write-back stay deferred until the SP-API sandbox flow is proven.
