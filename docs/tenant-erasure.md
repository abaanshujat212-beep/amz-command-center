# Tenant data erasure

`infra/scripts/purge_tenant.py` is an operator-only erasure tool. It discovers physical tables with a `tenant_id` column, previews per-table row counts, and orders deletes child-before-parent using database foreign keys. The apply path deletes the tenant-scoped rows and tenant record in one transaction, then verifies that every discovered tenant table contains zero rows before commit.

The connection must be a database-owner/operator role with `BYPASSRLS` and delete/lock access; the command refuses app-role connections. It performs a read-only preview by default. The destructive path requires the tenant UUID twice, an operator identity, and a private JSON receipt path. The receipt is written with mode `0600` and records the rows removed by table. Tenant-scoped tables are locked without waiting so concurrent writes cannot race the verification. Cyclic foreign keys or restrictive references abort and roll back the transaction.

Load the operator database URL in a trusted shell, then preview:

```sh
uv run --locked python infra/scripts/purge_tenant.py --tenant-id 00000000-0000-0000-0000-000000000000
```

After the tenant owner has authorized erasure and the retention/legal hold review is complete, apply using the same exact UUID:

```sh
uv run --locked python infra/scripts/purge_tenant.py \
  --tenant-id 00000000-0000-0000-0000-000000000000 \
  --apply \
  --confirm-tenant-id 00000000-0000-0000-0000-000000000000 \
  --actor operator@example.com \
  --receipt /private/erasure-receipts/tenant-00000000-0000-0000-0000-000000000000.json
```

Do not run the destructive command against production until the organization has approved its retention and legal-hold policy, verified an encrypted backup, and selected an authorized operator. Database backups retain their own copies until their retention period expires; this tool does not erase backup media. Review the receipt and independently verify the deletion before closing a data-subject request.
