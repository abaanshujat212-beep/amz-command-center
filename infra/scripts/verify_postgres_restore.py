#!/usr/bin/env python3
"""Verify a backup by restoring it into an empty, explicitly named scratch DB."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from backup_postgres import connection_env, run_command, sha256_file

EMPTY_DATABASE_SQL = """
select
  (select count(*) from pg_namespace where nspname not in ('pg_catalog', 'information_schema', 'public')) +
  (select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public') +
  (select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public') +
  (select count(*) from pg_type t join pg_namespace n on n.oid = t.typnamespace
    where n.nspname = 'public') +
  (select count(*) from pg_largeobject_metadata) +
  (select count(*) from pg_extension where extname <> 'plpgsql')
"""


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--backup", type=Path, required=True)
	args = parser.parse_args()
	target_url = os.environ.get("RESTORE_DATABASE_URL", "")
	if not target_url:
		parser.error("RESTORE_DATABASE_URL must point to a dedicated scratch database")
	psql = shutil.which("psql")
	pg_restore = shutil.which("pg_restore")
	if not psql or not pg_restore:
		parser.error("PostgreSQL client tools psql and pg_restore must be installed")

	manifest_path = args.backup.with_suffix(".manifest.json")
	try:
		manifest = json.loads(manifest_path.read_text())
		if not isinstance(manifest, dict):
			raise ValueError("backup manifest must contain a JSON object")
		globals_name = str(manifest.get("globals_file", ""))
		if not globals_name or Path(globals_name).name != globals_name:
			raise ValueError("backup manifest has an invalid globals filename")
		globals_path = manifest_path.parent / globals_name
		if (manifest.get("backup_file") != args.backup.name
				or manifest.get("backup_sha256") != sha256_file(args.backup)
				or manifest.get("globals_sha256") != sha256_file(globals_path)):
			raise ValueError("backup/global file name or SHA-256 does not match its manifest")
		with tempfile.TemporaryDirectory(prefix="axaty-restore-pgpass-") as temp_name:
			env, db_name = connection_env(target_url, Path(temp_name))
			if not db_name.endswith(("_scratch", "_restore")):
				raise ValueError("restore target database name must end in _scratch or _restore")
			if manifest.get("database_name") == db_name:
				raise ValueError("restore target must differ from the backup source database")
			count = run_command(
				[psql, "--no-psqlrc", "--tuples-only", "--no-align", "--dbname", db_name, "--command", EMPTY_DATABASE_SQL],
				env=env, check=True, capture_output=True, text=True,
			).stdout.strip()
			if count != "0":
				raise ValueError(f"restore target {db_name!r} is not empty; refusing to modify it")
			run_command(
				[pg_restore, "--exit-on-error", "--single-transaction", "--dbname", db_name, str(args.backup)],
				env=env, check=True,
			)
			check = run_command(
				[psql, "--no-psqlrc", "--tuples-only", "--no-align", "--dbname", db_name, "--command", "select count(*) from information_schema.tables where table_schema not in ('pg_catalog','information_schema')"],
				env=env, check=True, capture_output=True, text=True,
			).stdout.strip()
			if not check.isdigit() or int(check) == 0:
				raise ValueError("restored database has no user tables")
	except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
		print(f"restore verification failed: {exc}", file=sys.stderr)
		return 1

	print(f"restore verified in {db_name}: {check} user tables present")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
