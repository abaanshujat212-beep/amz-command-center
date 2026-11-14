#!/usr/bin/env python3
"""Create a private, verified PostgreSQL custom-format backup and manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit


def connection_env(database_url: str, temp_dir: Path) -> tuple[dict[str, str], str]:
	parsed = urlsplit(database_url)
	if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname or not parsed.path.strip("/"):
		raise ValueError("DATABASE_URL must be a PostgreSQL URL with a database name")
	password = unquote(parsed.password or "")
	env = os.environ.copy()
	env.pop("DATABASE_URL", None)
	env.pop("RESTORE_DATABASE_URL", None)
	env.pop("PGPASSWORD", None)
	if password:
		pgpass = temp_dir / "pgpass"
		fields = [parsed.hostname, str(parsed.port or 5432), parsed.path.strip("/"), unquote(parsed.username or "*"), password]
		pgpass.write_text(":".join(field.replace("\\", "\\\\").replace(":", "\\:") for field in fields) + "\n")
		pgpass.chmod(0o600)
		env["PGPASSFILE"] = str(pgpass)
	if parsed.hostname:
		env["PGHOST"] = parsed.hostname
	env["PGPORT"] = str(parsed.port or 5432)
	if parsed.username:
		env["PGUSER"] = unquote(parsed.username)
	pg_names = {"sslmode": "PGSSLMODE", "sslrootcert": "PGSSLROOTCERT", "sslcert": "PGSSLCERT",
		"sslkey": "PGSSLKEY", "connect_timeout": "PGCONNECT_TIMEOUT", "application_name": "PGAPPNAME",
		"options": "PGOPTIONS"}
	for key, value in parse_qsl(parsed.query):
		if key in pg_names:
			env[pg_names[key]] = value
	return env, unquote(parsed.path.strip("/"))


def sha256_file(path: Path) -> str:
	digest = hashlib.sha256()
	with path.open("rb") as stream:
		for chunk in iter(lambda: stream.read(1024 * 1024), b""):
			digest.update(chunk)
	return digest.hexdigest()


def run_command(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
	# Fixed executable paths and an argv list are used; no shell parsing occurs.
	return subprocess.run(argv, **kwargs)  # noqa: S603


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--output-dir", type=Path, required=True)
	args = parser.parse_args()
	database_url = os.environ.get("DATABASE_URL", "")
	if not database_url:
		parser.error("DATABASE_URL is required")
	pg_dump = shutil.which("pg_dump")
	pg_dumpall = shutil.which("pg_dumpall")
	pg_restore = shutil.which("pg_restore")
	if not pg_dump or not pg_dumpall or not pg_restore:
		parser.error("PostgreSQL client tools pg_dump, pg_dumpall and pg_restore must be installed")

	args.output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
	stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
	backup = args.output_dir / f"axaty-{stamp}.dump"
	globals = args.output_dir / f"axaty-{stamp}.globals.sql"
	manifest = args.output_dir / f"axaty-{stamp}.manifest.json"
	fd, partial_name = tempfile.mkstemp(prefix=f".{backup.name}.", suffix=".partial", dir=args.output_dir)
	os.close(fd)
	partial = Path(partial_name)
	fd, globals_partial_name = tempfile.mkstemp(prefix=f".{globals.name}.", suffix=".partial", dir=args.output_dir)
	os.close(fd)
	globals_partial = Path(globals_partial_name)

	try:
		with tempfile.TemporaryDirectory(prefix="axaty-pgpass-") as temp_name:
			env, db_name = connection_env(database_url, Path(temp_name))
			run_command([pg_dumpall, "--globals-only", "--dbname", db_name, "--file", str(globals_partial)], env=env, check=True)
			os.chmod(globals_partial, 0o600)
			run_command(
				[pg_dump, "--format=custom", "--file", str(partial), "--dbname", db_name],
				env=env, check=True,
			)
			run_command([pg_restore, "--list", str(partial)], env=env, check=True, stdout=subprocess.DEVNULL)
			backup_digest = sha256_file(partial)
			globals_digest = sha256_file(globals_partial)
			os.chmod(partial, 0o600)
			os.replace(partial, backup)
			os.replace(globals_partial, globals)
			payload = {
				"format": "postgresql-custom",
				"database_name": db_name,
				"created_at_utc": datetime.now(UTC).isoformat(),
				"backup_file": backup.name,
				"backup_sha256": backup_digest,
				"globals_file": globals.name,
				"globals_sha256": globals_digest,
			}
			manifest_tmp = manifest.with_suffix(".json.partial")
			manifest_tmp.write_text(json.dumps(payload, indent=2) + "\n")
			os.chmod(manifest_tmp, 0o600)
			os.replace(manifest_tmp, manifest)
	except (OSError, ValueError, subprocess.CalledProcessError) as exc:
		partial.unlink(missing_ok=True)
		globals_partial.unlink(missing_ok=True)
		print(f"backup failed: {exc}", file=sys.stderr)
		return 1

	print(f"verified backup: {backup}")
	print(f"global roles and tablespaces (sensitive): {globals}")
	print(f"manifest: {manifest}")
	print("Copy both files to encrypted off-host storage and retain according to policy.")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
