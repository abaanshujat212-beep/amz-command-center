#!/usr/bin/env python3
"""Preview or transactionally erase one tenant and its tenant-scoped records."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row


def tenant_tables(connection: psycopg.Connection) -> list[dict[str, object]]:
    return connection.execute(
        """select c.oid::bigint as oid, n.nspname as schema_name, c.relname as table_name
             from pg_catalog.pg_class c
             join pg_catalog.pg_namespace n on n.oid=c.relnamespace
             join pg_catalog.pg_attribute a on a.attrelid=c.oid
            where c.relkind in ('r','p') and not c.relispartition
              and a.attname='tenant_id' and a.attnum>0 and not a.attisdropped
              and n.nspname not in ('information_schema','pg_catalog')
              and left(n.nspname,3)<>'pg_'
            order by n.nspname,c.relname""",
    ).fetchall()


def delete_order(connection: psycopg.Connection, tables: list[dict[str, object]]) -> list[int]:
    """Return tenant tables in child-before-parent foreign-key order."""
    table_ids = {int(table["oid"]) for table in tables}
    edges = connection.execute(
        """select con.conrelid::bigint as child, con.confrelid::bigint as parent
             from pg_catalog.pg_constraint con
            where con.contype='f'""",
    ).fetchall()

    graph = {table_id: set() for table_id in table_ids}
    indegree = {table_id: 0 for table_id in table_ids}

    for edge in edges:
        child = int(edge["child"])
        parent = int(edge["parent"])
        if child in table_ids and parent in table_ids and parent not in graph[child]:
            graph[child].add(parent)
            indegree[parent] += 1

    ready = sorted(table_id for table_id, degree in indegree.items() if degree == 0)
    ordered: list[int] = []
    while ready:
        child = ready.pop(0)
        ordered.append(child)
        for parent in sorted(graph[child]):
            indegree[parent] -= 1
            if indegree[parent] == 0:
                ready.append(parent)
                ready.sort()
    if len(ordered) != len(table_ids):
        raise ValueError("tenant-scoped tables have a cyclic foreign-key graph; refusing purge")
    return ordered


def rls_bypass_available(connection: psycopg.Connection) -> bool:
    row = connection.execute(
        "select rolsuper or rolbypassrls as allowed "
        "from pg_catalog.pg_roles where rolname=current_user"
    ).fetchone()
    return bool(row and row["allowed"])


def table_counts(
    connection: psycopg.Connection, tables: list[dict[str, object]], tenant_id: uuid.UUID
) -> dict[int, int]:
    counts: dict[int, int] = {}
    for table in tables:
        table_id = int(table["oid"])
        statement = sql.SQL("select count(*) as row_count from {} where tenant_id=%s").format(
            sql.Identifier(str(table["schema_name"]), str(table["table_name"]))
        )
        counts[table_id] = int(
            connection.execute(statement, (tenant_id,)).fetchone()["row_count"]
        )
    return counts


def atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".partial", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.chmod(temporary, 0o600)
            json.dump(payload, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


def purge_tenant(
    database_url: str,
    tenant_id: uuid.UUID,
    *,
    apply: bool = False,
    actor: str | None = None,
    receipt_path: Path | None = None,
) -> dict[str, object]:
    receipt_written = False
    committed = False
    summary: dict[str, object] = {}
    try:
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            with connection.transaction():
                if not apply:
                    connection.execute("set transaction read only")
                connection.execute("set local statement_timeout='300s'")
                if not rls_bypass_available(connection):
                    raise ValueError(
                        "DATABASE_URL must use a restricted operator role with BYPASSRLS"
                    )
                tenant = connection.execute(
                    "select id::text as id,name,status from public.tenant where id=%s"
                    + (" for update" if apply else ""),
                    (tenant_id,),
                ).fetchone()
                if tenant is None:
                    raise ValueError(f"tenant {tenant_id} does not exist or is not visible")

                tables = tenant_tables(connection)
                order = delete_order(connection, tables)
                if apply:
                    for table in tables:
                        lock = sql.SQL(
                            "lock table {} in share row exclusive mode nowait"
                        ).format(
                            sql.Identifier(str(table["schema_name"]), str(table["table_name"]))
                        )
                        connection.execute(lock)
                before = table_counts(connection, tables, tenant_id)
                tables_by_id = {int(table["oid"]): table for table in tables}
                summary = {
                    "tenant_id": str(tenant_id),
                    "tenant_name": tenant["name"],
                    "tenant_status": tenant["status"],
                    "tables_with_rows": sum(count > 0 for count in before.values()),
                    "rows_by_table": {
                        f"{table['schema_name']}.{table['table_name']}": before[int(table["oid"])]
                        for table in tables
                        if before[int(table["oid"])] > 0
                    },
                    "total_rows": sum(before.values()),
                    "applied": apply,
                }
                if not apply:
                    return summary

                for table_id in order:
                    table = tables_by_id[table_id]
                    statement = sql.SQL("delete from {} where tenant_id=%s").format(
                        sql.Identifier(str(table["schema_name"]), str(table["table_name"]))
                    )
                    connection.execute(statement, (tenant_id,))

                deleted = connection.execute(
                    "delete from public.tenant where id=%s returning id", (tenant_id,)
                ).fetchone()
                if deleted is None:
                    raise RuntimeError("tenant row disappeared before deletion")

                remaining = table_counts(connection, tables, tenant_id)
                leftovers = {
                    f"{table['schema_name']}.{table['table_name']}": remaining[int(table["oid"])]
                    for table in tables
                    if remaining[int(table["oid"])] > 0
                }
                if leftovers:
                    raise RuntimeError(f"tenant purge left rows; transaction rolled back: {leftovers}")

                if receipt_path is None or actor is None:
                    raise ValueError("an apply operation requires an actor and receipt path")
                if receipt_path.exists():
                    raise FileExistsError(f"receipt already exists: {receipt_path}")
                pending = {
                    **summary,
                    "actor": actor,
                    "status": "commit_pending",
                    "completed_at_utc": datetime.now(UTC).isoformat(),
                    "verification": "all discovered tenant_id tables contain zero rows",
                }
                atomic_json(receipt_path, pending)
                receipt_written = True

        committed = apply
        if apply and receipt_path is not None:
            summary["actor"] = actor
            summary["status"] = "completed"
            summary["completed_at_utc"] = datetime.now(UTC).isoformat()
            summary["verification"] = "all discovered tenant_id tables contain zero rows"
            atomic_json(receipt_path, summary)
        return summary
    except Exception:
        if receipt_written and not committed and receipt_path is not None:
            receipt_path.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True, type=uuid.UUID)
    parser.add_argument("--apply", action="store_true", help="irreversibly delete tenant data")
    parser.add_argument("--confirm-tenant-id", type=uuid.UUID)
    parser.add_argument("--actor", help="operator identity recorded in the receipt")
    parser.add_argument("--receipt", type=Path, help="private JSON receipt path required with --apply")
    args = parser.parse_args()
    if args.apply:
        if args.confirm_tenant_id != args.tenant_id:
            parser.error("--apply requires --confirm-tenant-id to exactly match --tenant-id")
        if not args.actor or not args.actor.strip():
            parser.error("--apply requires a non-empty --actor")
        if args.receipt is None:
            parser.error("--apply requires --receipt")
    elif args.confirm_tenant_id or args.actor or args.receipt:
        parser.error("--confirm-tenant-id, --actor and --receipt are only valid with --apply")
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        parser.error("DATABASE_URL is required")
    try:
        result = purge_tenant(
            database_url,
            args.tenant_id,
            apply=args.apply,
            actor=args.actor,
            receipt_path=args.receipt,
        )
    except (OSError, psycopg.Error, RuntimeError, ValueError) as exc:
        print(f"tenant purge failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    if not args.apply:
        print("Preview only. No rows were changed. Repeat with --apply and exact confirmation to purge.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
