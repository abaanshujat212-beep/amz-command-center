"""Migration runner: ledger, checksums, per-file transactions, explicit down path.

    python -m packages.db.migrate status
    python -m packages.db.migrate up
    python -m packages.db.migrate down [--steps N]
    python -m packages.db.migrate baseline

Why this exists: the previous Makefile target was

    for f in $(ls packages/db/migrations/*.sql | sort); do psql < $f; done

which replayed every file on every run. With ON_ERROR_STOP=1 the second run
aborts at the first non-idempotent statement, and there was no record of what
had already been applied. See docs/adr/003-migrations.md.

Runs from the host against DATABASE_URL (docker publishes 5432), not inside
the container, so the same command works against a remote database later.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
DOWN_DIR = MIGRATIONS_DIR / "down"
FILENAME_RE = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")

LEDGER_DDL = """
create table if not exists schema_migrations (
    version    text primary key,
    name       text not null,
    checksum   text not null,
    applied_at timestamptz not null default now()
)
"""


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    path: Path

    @property
    def sql(self) -> str:
        return self.path.read_text(encoding="utf-8")

    @property
    def checksum(self) -> str:
        # Short sha256 of the raw bytes. Long enough to catch an edit, short
        # enough to eyeball in `status` output.
        return hashlib.sha256(self.path.read_bytes()).hexdigest()[:16]

    @property
    def down_path(self) -> Path:
        return DOWN_DIR / self.path.name

    @property
    def reversible(self) -> bool:
        return self.down_path.exists()


def fail(lines: list[str]) -> None:
    for line in lines:
        print(f"error: {line}", file=sys.stderr)
    raise SystemExit(1)


def discover() -> list[Migration]:
    """Every forward migration, ordered by version."""
    found: list[Migration] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        match = FILENAME_RE.match(path.name)
        if match is None:
            fail([f"bad migration filename {path.name!r}: expected NNNN_snake_case.sql"])
            raise AssertionError("unreachable")
        found.append(Migration(version=match.group(1), name=path.stem, path=path))

    versions = [m.version for m in found]
    duplicates = sorted({v for v in versions if versions.count(v) > 1})
    if duplicates:
        fail([f"duplicate migration version(s): {', '.join(duplicates)}"])
    return found


def connect():
    url = os.environ.get("DATABASE_URL")
    if not url:
        fail([
            "DATABASE_URL is not set.",
            "The Makefile sources .env for you; if running by hand, do that first.",
        ])
    try:
        import psycopg
    except ImportError:
        fail(["psycopg is not installed: pip install 'psycopg[binary]'"])
        raise AssertionError("unreachable")
    return psycopg.connect(url, autocommit=False)


def read_ledger(conn) -> dict[str, str]:
    """version -> checksum. Creates the ledger table on first use."""
    with conn.cursor() as cur:
        cur.execute(LEDGER_DDL)
        cur.execute("select version, checksum from schema_migrations")
        rows = cur.fetchall()
    conn.commit()
    return {version: checksum for version, checksum in rows}


def integrity_problems(migrations: list[Migration], ledger: dict[str, str]) -> list[str]:
    """Drift between what was applied and what is on disk now."""
    problems: list[str] = []
    for m in migrations:
        recorded = ledger.get(m.version)
        if recorded is not None and recorded != m.checksum:
            problems.append(
                f"{m.version} {m.name}: file was edited after it was applied "
                f"(ledger {recorded}, file {m.checksum}). "
                "Write a new migration instead of editing an applied one."
            )
    orphans = sorted(set(ledger) - {m.version for m in migrations})
    for version in orphans:
        problems.append(f"{version}: recorded as applied but its file no longer exists")
    return problems


def cmd_status(_args: argparse.Namespace) -> None:
    migrations = discover()
    with connect() as conn:
        ledger = read_ledger(conn)

    print(f"{'ver':<5} {'state':<9} {'down':<5} name")
    for m in migrations:
        state = "applied" if m.version in ledger else "pending"
        print(f"{m.version:<5} {state:<9} {'yes' if m.reversible else 'no':<5} {m.name}")

    pending = sum(1 for m in migrations if m.version not in ledger)
    print(f"\n{len(migrations) - pending} applied, {pending} pending")

    for problem in integrity_problems(migrations, ledger):
        print(f"warning: {problem}", file=sys.stderr)


def cmd_up(_args: argparse.Namespace) -> None:
    migrations = discover()
    with connect() as conn:
        ledger = read_ledger(conn)
        problems = integrity_problems(migrations, ledger)
        if problems:
            fail(problems)

        pending = [m for m in migrations if m.version not in ledger]
        if not pending:
            print(f"nothing to do: {len(migrations)} migrations already applied")
            return

        for m in pending:
            print(f"applying {m.version} {m.name}")
            with conn.cursor() as cur:
                cur.execute(m.sql)
                cur.execute(
                    "insert into schema_migrations (version, name, checksum) "
                    "values (%s, %s, %s)",
                    (m.version, m.name, m.checksum),
                )
            # One transaction per migration: a later failure cannot undo an
            # earlier success, and the ledger always matches reality.
            conn.commit()
            note = "" if m.reversible else "  [forward-only: no down file]"
            print(f"  ok {m.checksum}{note}")

    print(f"applied {len(pending)} migration(s)")


def cmd_down(args: argparse.Namespace) -> None:
    by_version = {m.version: m for m in discover()}
    with connect() as conn:
        ledger = read_ledger(conn)
        if not ledger:
            print("nothing applied")
            return

        targets = sorted(ledger, reverse=True)[: args.steps]
        for version in targets:
            m = by_version.get(version)
            if m is None:
                fail([f"{version} is in the ledger but its file is gone; cannot reverse it"])
                raise AssertionError("unreachable")
            if not m.reversible:
                fail([
                    f"{m.version} {m.name} has no down file at {m.down_path}.",
                    "Structural migrations ship one; see ADR 003 for the rule.",
                    "For a full local reset use `make clean`, which drops the volumes.",
                ])
            print(f"reverting {m.version} {m.name}")
            with conn.cursor() as cur:
                cur.execute(m.down_path.read_text(encoding="utf-8"))
                cur.execute("delete from schema_migrations where version = %s", (m.version,))
            conn.commit()

    print(f"reverted {len(targets)} migration(s)")


def cmd_baseline(_args: argparse.Namespace) -> None:
    """Adopt a database that was already migrated by the old shell loop.

    Records every file as applied *without running it*. Only correct when the
    schema already matches; it is a one-time bridge, not a repair tool.
    """
    migrations = discover()
    with connect() as conn:
        ledger = read_ledger(conn)
        adopted = 0
        with conn.cursor() as cur:
            for m in migrations:
                if m.version in ledger:
                    continue
                cur.execute(
                    "insert into schema_migrations (version, name, checksum) "
                    "values (%s, %s, %s)",
                    (m.version, m.name, m.checksum),
                )
                adopted += 1
        conn.commit()
    print(f"baselined {adopted} migration(s) as applied without running them")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="packages.db.migrate")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="list applied and pending migrations").set_defaults(func=cmd_status)
    sub.add_parser("up", help="apply every pending migration").set_defaults(func=cmd_up)

    down = sub.add_parser("down", help="revert the most recently applied migration(s)")
    down.add_argument("--steps", type=int, default=1, help="how many to revert (default 1)")
    down.set_defaults(func=cmd_down)

    sub.add_parser("baseline", help="record all files as applied without running them").set_defaults(func=cmd_baseline)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
