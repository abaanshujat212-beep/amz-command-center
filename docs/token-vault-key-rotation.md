# Amazon token vault key rotation

`amazon_connection.key_version` identifies the KEK that wrapped each per-row data key. The service now decrypts only with the exact recorded version. `KEK_BASE64`/`KEK_VERSION` select the current key; `KEK_PREVIOUS_BASE64`/`KEK_PREVIOUS_VERSION` allow a rollout to read the prior version while new/rewrapped tokens use the current key.

## Rotation procedure

1. Take and verify a database backup. Keep the old KEK in the secret manager and preserve it for the retention period of backups containing that key version.
2. Generate a new random 32-byte KEK and increment `KEK_VERSION`. Put the old key/version in the previous-key variables.
3. Roll out the new current and previous key configuration to every ingest worker and action worker. Confirm all processes can read old tokens before touching rows. Do not run an old-only worker after rewrapping begins; it cannot read new-version ciphertext.
4. For each tenant, first inspect a dry run:

   ```sh
   make rotate-token-vault TENANT_ID=<tenant-uuid>
   ```

   The dry run decrypts every stored token for that tenant, reports only counts/version, and makes no writes. Missing keys, corrupt ciphertext, or DB errors fail closed.
5. Apply each tenant separately after reviewing its dry-run result:

   ```sh
   make rotate-token-vault TENANT_ID=<tenant-uuid> APPLY=true
   ```

   The command locks that tenant's connection rows in one transaction, rewraps ciphertext, updates `key_version`, and writes an audit row with old/new versions. Plaintext is never logged or written to disk. A failure rolls back that tenant's batch.
6. With an appropriately privileged database session, confirm no live rows still use an older version:

   ```sql
   select key_version, count(*)
   from amazon_connection
   where refresh_token_encrypted is not null
   group by key_version
   order by key_version;
   ```

   Repeat dry-run/apply for any remaining tenant. Remove the previous key from runtime configuration only after all workers use the new current key and no live row requires the old version. Keep historical keys separately for retained backups; restoring an older backup requires its matching KEK version on the isolated restore environment.

## Safeguards and limits

- Always deploy the dual-key reader everywhere before applying any rewrap.
- The command requires an explicit tenant UUID and defaults to dry-run. It neither contacts Amazon nor rotates Amazon-issued refresh tokens.
- Audit rows include connection ID and key versions only, never ciphertext or plaintext token values.
- Only the current and one previous KEK are configured for live reads at a time. Rewrap all rows before starting another rotation.
- This procedure does not replace secret-manager access control, encrypted backups, or recovery of the key itself. Losing every copy of a KEK makes its ciphertext unrecoverable.
