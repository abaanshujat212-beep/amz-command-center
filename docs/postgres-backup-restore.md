# PostgreSQL backup and restore verification

These commands create and verify PostgreSQL custom-format backups. They are an operator tool, not a configured production schedule: deploy them on a trusted host with PostgreSQL client tools, `DATABASE_URL`, and encrypted off-host storage configured. Do not commit dumps, manifests, connection strings, or credentials.

## Create a backup

Install `pg_dump` and `pg_restore` matching the server's PostgreSQL major version. Then run:

```sh
make backup-postgres BACKUP_DIR=/var/backups/axaty
```

The command writes a mode-0600 custom-format `.dump`, a mode-0600 `.globals.sql` containing PostgreSQL roles/tablespaces, and a JSON manifest with filenames, database name, UTC timestamp and SHA-256 digests. The archive is validated with `pg_restore --list` before publishing the files. The connection password is placed in a short-lived mode-0600 pgpass file; it is removed when the command exits. The globals file can contain password hashes and must be treated as highly sensitive. Protect the destination directory and copy all three artifacts to encrypted off-host storage. Configure off-host encryption, access control, retention and monitoring in the deployment platform; a successful local dump alone is not a backup strategy.

Set a documented recovery point objective (RPO), recovery time objective (RTO), and retention schedule before production launch. Alert if a scheduled backup or off-host copy fails. Keep multiple daily backups and a longer monthly history according to the client's retention agreement. Never put a credential-bearing database URL in command-line arguments, logs, cron definitions, or this repository.

## Verify a backup in a scratch database

Create a dedicated empty database on an isolated PostgreSQL server, for example `axaty_restore`. Set `RESTORE_DATABASE_URL` through the deployment secret store, then run:

```sh
make verify-postgres-backup BACKUP_FILE=/var/backups/axaty/axaty-YYYYMMDDTHHMMSSZ.dump
```

Before running the verifier, provision the database's required PostgreSQL roles on the isolated restore server from the reviewed `.globals.sql` file (for example with `psql --dbname postgres --file ...`) using an appropriately privileged operator. Review the SQL and protect its password hashes; never restore globals to a shared or production cluster as part of this drill. The verifier requires the adjacent manifest, checks both SHA-256 digests and filenames, requires the target database name to end in `_scratch` or `_restore`, and refuses any target containing user objects. Restore preserves ownership and ACLs and runs in one transaction; missing required roles fail the restore. It reports success only after confirming user tables exist. Use a disposable isolated database; the script does not drop or clean existing objects. Remove the scratch database after recording the drill result.

For a weekly restore drill, record the backup timestamp, source database identifier, target, duration, restored table count, checksum result, operator, and any errors. This repository does not claim a restore drill has been performed; production readiness requires an operator to perform and record one, then compare the observed recovery time with the chosen RTO. Avoid restoring sensitive production data to an environment without equivalent access controls.

## Limits

- The backup is not encrypted by this script. Protect all artifacts and use encrypted off-host storage before handling production data.
- A dump stored only on the database host does not protect against host loss.
- Extensions and PostgreSQL major-version compatibility must be verified in the target environment.
- This verifies structural restoration and table presence, not business-level reconciliation. Include application smoke checks and compare critical tenant/month row counts during the operational drill.
