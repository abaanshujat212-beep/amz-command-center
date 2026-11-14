#!/usr/bin/env python3
"""Compare two explicitly normalized PPC/commercial CSV exports for a settled window."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

GRAINS = {"campaign", "placement", "account"}
FIELDS = (
    "report_date", "grain", "entity_id", "placement", "is_settled", "currency",
    "spend", "ad_sales", "ad_orders", "total_sales", "budget_amount",
)
METRICS = {"spend", "ad_sales", "ad_orders", "acos", "tacos", "budget_amount"}
PLACEMENT_NAMES = {"top_of_search", "product_page", "rest_of_search", "off_amazon"}
PLACEMENT_METRICS = {
    f"placement.{placement}.{metric}"
    for placement in PLACEMENT_NAMES
    for metric in ("spend", "ad_sales", "ad_orders")
}
ZERO = Decimal(0)


@dataclass(frozen=True)
class Record:
    report_date: date
    grain: str
    entity_id: str
    placement: str
    currency: str
    values: dict[str, Decimal | None]


def parse_decimal(value: str, label: str, *, integer: bool = False) -> Decimal | None:
    if value == "":
        return None
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{label} is not a decimal: {value!r}") from exc
    if not result.is_finite() or (integer and result != result.to_integral_value()):
        raise ValueError(f"{label} must be a finite {'integer' if integer else 'decimal'}")
    return result


def load_csv(path: Path, start: date, end: date) -> tuple[list[Record], int, str]:
    digest = hashlib.sha256()
    with path.open("rb") as raw:
        for chunk in iter(lambda: raw.read(1024 * 1024), b""):
            digest.update(chunk)
    records: list[Record] = []
    seen: set[tuple[date, str, str, str]] = set()
    excluded = 0
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or set(reader.fieldnames) != set(FIELDS):
            raise ValueError(f"{path}: CSV header must contain exactly: {', '.join(FIELDS)}")
        for line, row in enumerate(reader, start=2):
            try:
                day = date.fromisoformat(row["report_date"])
                if day < start or day > end:
                    excluded += 1
                    continue
                grain = row["grain"]
                entity = row["entity_id"].strip()
                placement = row["placement"].strip()
                currency = row["currency"].strip()
                if grain not in GRAINS or not entity:
                    raise ValueError("grain must be campaign, placement, or account and entity_id nonempty")
                if not re.fullmatch(r"[A-Z]{3}", currency):
                    raise ValueError("currency must be an uppercase three-letter code")
                if row["is_settled"].strip().lower() != "true":
                    raise ValueError("all in-window rows must be marked is_settled=true")
                if grain == "placement" and placement not in PLACEMENT_NAMES:
                    raise ValueError(f"placement must be one of {sorted(PLACEMENT_NAMES)}")
                if grain != "placement" and placement:
                    raise ValueError("placement must be blank except on placement-grain rows")
                values = {
                    name: parse_decimal(row[name].strip(), f"{path}:{line}:{name}", integer=name == "ad_orders")
                    for name in ("spend", "ad_sales", "ad_orders", "total_sales", "budget_amount")
                }
                if grain in {"campaign", "placement"} and any(
                    values[name] is None for name in ("spend", "ad_sales", "ad_orders")
                ):
                    raise ValueError(f"{grain} rows require spend, ad_sales, and ad_orders")
                if grain == "account" and values["total_sales"] is None:
                    raise ValueError("account rows require total_sales")
                if grain != "campaign" and values["budget_amount"] is not None:
                    raise ValueError("budget_amount is allowed only on campaign rows")
                if grain != "account" and values["total_sales"] is not None:
                    raise ValueError("total_sales is allowed only on account rows")
                key = day, grain, entity, placement
                if key in seen:
                    raise ValueError(f"duplicate normalized row key: {key}")
                seen.add(key)
                records.append(Record(day, grain, entity, placement, currency, values))
            except (KeyError, ValueError) as exc:
                raise ValueError(f"{path}:{line}: {exc}") from exc
    if not records:
        raise ValueError(f"{path}: no in-window rows")
    return records, excluded, digest.hexdigest()


def total(rows: list[Record], field: str) -> Decimal | None:
    values = [row.values[field] for row in rows]
    if not values or any(value is None for value in values):
        return None
    return sum((value for value in values if value is not None), ZERO)


def ratio(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator is None or denominator == ZERO:
        return None
    return numerator / denominator


def aggregate(records: list[Record]) -> dict[str, Any]:
    campaign = [row for row in records if row.grain == "campaign"]
    placement = [row for row in records if row.grain == "placement"]
    account = [row for row in records if row.grain == "account"]
    spend = total(campaign, "spend")
    sales = total(campaign, "ad_sales")
    commerce_sales = total(account, "total_sales")

    budgets: dict[str, list[Record]] = {}
    for row in campaign:
        budgets.setdefault(row.entity_id, []).append(row)
    latest_budgets: list[Decimal] = []
    for snapshots in budgets.values():
        latest_date = max(row.report_date for row in snapshots)
        latest = [row.values["budget_amount"] for row in snapshots if row.report_date == latest_date]
        if len(latest) != 1 or latest[0] is None:
            return_value = None
            break
        latest_budgets.append(latest[0])
    else:
        return_value = sum(latest_budgets, ZERO) if budgets else None

    placements: dict[str, dict[str, Decimal | None]] = {}
    for name in sorted(PLACEMENT_NAMES):
        rows = [row for row in placement if row.placement == name]
        if rows:
            placements[name] = {
                "spend": total(rows, "spend"),
                "ad_sales": total(rows, "ad_sales"),
                "ad_orders": total(rows, "ad_orders"),
            }
    return {
        "spend": spend,
        "ad_sales": sales,
        "ad_orders": total(campaign, "ad_orders"),
        "total_sales": commerce_sales,
        "acos": ratio(spend, sales),
        "tacos": ratio(spend, commerce_sales),
        "budget_amount": return_value,
        "placements": placements,
        "campaign_row_count": len(campaign),
        "placement_row_count": len(placement),
        "account_row_count": len(account),
        "campaign_dates": sorted({row.report_date.isoformat() for row in campaign}),
        "placement_dates": sorted({row.report_date.isoformat() for row in placement}),
        "account_dates": sorted({row.report_date.isoformat() for row in account}),
    }


def as_text(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def tolerances(path: Path | None) -> dict[str, dict[str, Decimal]]:
    if path is None:
        return {}
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("tolerance JSON must be an object keyed by metric")
    result: dict[str, dict[str, Decimal]] = {}
    for metric, bounds in parsed.items():
        if metric not in METRICS | PLACEMENT_METRICS or not isinstance(bounds, dict) or not bounds:
            raise ValueError(f"invalid tolerance entry for {metric!r}")
        if set(bounds) - {"absolute", "relative"}:
            raise ValueError(f"unknown tolerance bound for {metric!r}")
        result[metric] = {}
        for bound, value in bounds.items():
            amount = Decimal(str(value))
            if not amount.is_finite() or amount < ZERO:
                raise ValueError(f"{metric}.{bound} must be a finite non-negative number")
            result[metric][bound] = amount
    return result


def comparison(metric: str, application: Decimal | None, reference: Decimal | None,
               bounds: dict[str, Decimal]) -> dict[str, Any]:
    delta = application - reference if application is not None and reference is not None else None
    relative = abs(delta) / abs(reference) if delta is not None and reference not in (None, ZERO) else None
    status = "unassessed"
    if application is None or reference is None:
        status = "incomplete"
    elif bounds:
        within_absolute = "absolute" not in bounds or abs(delta) <= bounds["absolute"]
        within_relative = "relative" not in bounds or (
            relative is not None and relative <= bounds["relative"]
        )
        status = "pass" if within_absolute and within_relative else "fail"
    return {
        "application": as_text(application),
        "reference": as_text(reference),
        "delta_application_minus_reference": as_text(delta),
        "relative_delta": as_text(relative),
        "tolerance": {key: as_text(value) for key, value in bounds.items()},
        "status": status,
    }


def make_report(app_records: list[Record], ref_records: list[Record], *, start: date, end: date,
                definitions: dict[str, str], limits: dict[str, dict[str, Decimal]],
                app_meta: dict[str, Any], ref_meta: dict[str, Any]) -> dict[str, Any]:
    app = aggregate(app_records)
    ref = aggregate(ref_records)
    currencies = {row.currency for row in app_records + ref_records}
    if len(currencies) != 1:
        raise ValueError(f"input exports must use the same currency; found {sorted(currencies)}")
    comparisons = {
        metric: comparison(metric, app[metric], ref[metric], limits.get(metric, {}))
        for metric in sorted(METRICS)
    }
    for label, summary in (("application", app), ("reference", ref)):
        if summary["campaign_row_count"] and summary["placement_row_count"]:
            for metric in ("spend", "ad_sales", "ad_orders"):
                ptotal = sum(
                    (value[metric] for value in summary["placements"].values() if value[metric] is not None),
                    ZERO,
                )
                ctotal = summary[metric]
                if ctotal != ptotal:
                    raise ValueError(f"{label} campaign/placement cross-foot failed for {metric}: {ctotal} != {ptotal}")
    placement_comparisons = {}
    for name in sorted(set(app["placements"]) | set(ref["placements"])):
        placement_comparisons[name] = {
            metric: comparison(f"{name}.{metric}",
                              app["placements"].get(name, {}).get(metric),
                              ref["placements"].get(name, {}).get(metric),
                              limits.get(f"placement.{name}.{metric}", {}))
            for metric in ("spend", "ad_sales", "ad_orders")
        }
    states = [item["status"] for item in comparisons.values()]
    states.extend(item["status"] for per_placement in placement_comparisons.values()
                  for item in per_placement.values())
    result = "fail" if "fail" in states else (
        "pass" if states and all(state == "pass" for state in states) else "unassessed"
    )
    return {
        "schema_version": 1,
        "window": {"start_inclusive": start.isoformat(), "end_inclusive": end.isoformat()},
        "currency": next(iter(currencies)),
        "definitions": definitions,
        "sources": {"application": app_meta, "reference": ref_meta},
        "application_summary": {
            key: as_text(value) if isinstance(value, Decimal) else value
            for key, value in app.items() if key != "placements"
        },
        "reference_summary": {
            key: as_text(value) if isinstance(value, Decimal) else value
            for key, value in ref.items() if key != "placements"
        },
        "comparisons": comparisons,
        "placement_comparisons": placement_comparisons,
        "result": result,
    }


def write_private(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".partial", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.chmod(temp, 0o600)
            json.dump(report, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        os.chmod(path, 0o600)
    except OSError:
        temp.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--application", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--definition", action="append", default=[], metavar="METRIC=TEXT",
                        help="explicit KPI definition; repeat for spend, ad_sales, ad_orders, acos, tacos, budget_amount")
    parser.add_argument("--tolerances", type=Path,
                        help="optional JSON metric tolerance map (missing metrics remain unassessed)")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.end < args.start:
            raise ValueError("--end must be on or after --start")
        definitions: dict[str, str] = {}
        for item in args.definition:
            metric, separator, text = item.partition("=")
            if not separator or metric not in METRICS or not text.strip():
                raise ValueError(f"invalid --definition {item!r}")
            if metric in definitions:
                raise ValueError(f"duplicate definition for {metric}")
            definitions[metric] = text.strip()
        if set(definitions) != METRICS:
            raise ValueError(f"provide explicit --definition for every metric: {', '.join(sorted(METRICS - definitions.keys()))}")
        app_records, app_excluded, app_hash = load_csv(args.application, args.start, args.end)
        ref_records, ref_excluded, ref_hash = load_csv(args.reference, args.start, args.end)
        report = make_report(
            app_records, ref_records, start=args.start, end=args.end, definitions=definitions,
            limits=tolerances(args.tolerances),
            app_meta={"path": args.application.name, "sha256": app_hash, "in_window_rows": len(app_records), "excluded_outside_window_rows": app_excluded},
            ref_meta={"path": args.reference.name, "sha256": ref_hash, "in_window_rows": len(ref_records), "excluded_outside_window_rows": ref_excluded},
        )
        write_private(args.output, report)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"reconciliation failed: {exc}", file=sys.stderr)
        return 1
    print(f"reconciliation report: {args.output} ({report['result']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
