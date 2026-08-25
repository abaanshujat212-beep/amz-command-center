"""CSV importer for the SKU cost ledger.

The economics mart depends on sku_cost_ledger. This importer gives the operator a
repeatable local workflow for loading COGS/FBA/freight/VAT/storage costs without
hand-writing SQL.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
REQUIRED = {"sku", "valid_from", "cogs"}
OPTIONAL_DEFAULTS = {
    "asin": None,
    "valid_to": None,
    "freight_in": "0",
    "amazon_referral_pct": "0.15",
    "fba_fee": "0",
    "storage_est": "0",
    "vat_rate": "0.20",
    "currency": "GBP",
    "note": None,
}
MONEY_FIELDS = ("cogs", "freight_in", "fba_fee", "storage_est")
PCT_FIELDS = ("amazon_referral_pct", "vat_rate")


@dataclass(frozen=True)
class CostRow:
    sku: str
    asin: str | None
    valid_from: dt.date
    valid_to: dt.date | None
    cogs: Decimal
    freight_in: Decimal
    amazon_referral_pct: Decimal
    fba_fee: Decimal
    storage_est: Decimal
    vat_rate: Decimal
    currency: str
    note: str | None


@dataclass
class ImportResult:
    read: int = 0
    imported: int = 0
    skipped: int = 0
    errors: list[str] | None = None

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []


def _date(value: str | None, *, field: str) -> dt.date | None:
    if value in (None, ""):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be YYYY-MM-DD, got {value!r}") from exc


def _decimal(value: str | None, *, field: str) -> Decimal:
    if value in (None, ""):
        raise ValueError(f"{field} is required")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be numeric, got {value!r}") from exc
    if number < 0:
        raise ValueError(f"{field} must be non-negative")
    return number


def parse_row(raw: dict[str, str | None], *, line_no: int) -> CostRow:
    missing = sorted(k for k in REQUIRED if not raw.get(k))
    if missing:
        raise ValueError(f"line {line_no}: missing required field(s): {', '.join(missing)}")
    row = {**OPTIONAL_DEFAULTS, **raw}
    valid_from = _date(row.get("valid_from"), field="valid_from")
    assert valid_from is not None
    valid_to = _date(row.get("valid_to"), field="valid_to")
    if valid_to is not None and valid_to <= valid_from:
        raise ValueError(f"line {line_no}: valid_to must be after valid_from")
    currency = str(row.get("currency") or "GBP").upper()
    if len(currency) != 3:
        raise ValueError(f"line {line_no}: currency must be a 3-letter code")
    return CostRow(
        sku=str(row["sku"]).strip(),
        asin=str(row["asin"]).strip() or None if row.get("asin") else None,
        valid_from=valid_from,
        valid_to=valid_to,
        cogs=_decimal(row.get("cogs"), field="cogs"),
        freight_in=_decimal(row.get("freight_in"), field="freight_in"),
        amazon_referral_pct=_decimal(row.get("amazon_referral_pct"), field="amazon_referral_pct"),
        fba_fee=_decimal(row.get("fba_fee"), field="fba_fee"),
        storage_est=_decimal(row.get("storage_est"), field="storage_est"),
        vat_rate=_decimal(row.get("vat_rate"), field="vat_rate"),
        currency=currency,
        note=str(row["note"]).strip() or None if row.get("note") else None,
    )


def load_csv(path: Path) -> list[CostRow]:
    rows: list[CostRow] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV has no header row")
        missing = sorted(REQUIRED - set(reader.fieldnames))
        if missing:
            raise ValueError(f"CSV missing required column(s): {', '.join(missing)}")
        for line_no, raw in enumerate(reader, start=2):
            rows.append(parse_row(raw, line_no=line_no))
    return rows


def upsert_cost_row(conn, tenant_id: str, row: CostRow) -> None:
    # Keep exactly one open window per SKU by closing the previous open row when
    # a new open row starts. Historical closed windows are preserved.
    if row.valid_to is None:
        conn.execute(
            """
            update sku_cost_ledger
               set valid_to = %s
             where tenant_id = %s and sku = %s and valid_to is null and valid_from < %s
            """,
            (row.valid_from, tenant_id, row.sku, row.valid_from),
        )
    conn.execute(
        """
        insert into sku_cost_ledger (
            tenant_id, sku, asin, valid_from, valid_to, cogs, freight_in,
            amazon_referral_pct, fba_fee, storage_est, vat_rate, currency, note
        ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (tenant_id, sku) where valid_to is null do update set
            asin = excluded.asin,
            valid_from = excluded.valid_from,
            cogs = excluded.cogs,
            freight_in = excluded.freight_in,
            amazon_referral_pct = excluded.amazon_referral_pct,
            fba_fee = excluded.fba_fee,
            storage_est = excluded.storage_est,
            vat_rate = excluded.vat_rate,
            currency = excluded.currency,
            note = excluded.note
        """,
        (
            tenant_id,
            row.sku,
            row.asin,
            row.valid_from,
            row.valid_to,
            row.cogs,
            row.freight_in,
            row.amazon_referral_pct,
            row.fba_fee,
            row.storage_est,
            row.vat_rate,
            row.currency,
            row.note,
        ),
    )


def import_costs(tenant_id: str, path: Path, *, database_url: str = DATABASE_URL) -> ImportResult:
    rows = load_csv(path)
    result = ImportResult(read=len(rows))
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        conn.execute("select set_tenant(%s)", (tenant_id,))
        for row in rows:
            upsert_cost_row(conn, tenant_id, row)
            result.imported += 1
        conn.commit()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Import SKU cost ledger CSV")
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--tenant-id", default=os.environ.get("DEV_TENANT_ID"))
    args = parser.parse_args()
    if not args.tenant_id:
        raise SystemExit("--tenant-id or DEV_TENANT_ID is required")
    result = import_costs(args.tenant_id, args.csv_path)
    print(f"cost rows read={result.read} imported={result.imported} skipped={result.skipped}")
