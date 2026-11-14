"""Validate sanitized Amazon report fixtures with production parsers, without DB writes."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import zlib
from collections import Counter
from pathlib import Path
from typing import Any

from services.ingest.pipelines import ads_daily, sales_traffic

MAX_FIXTURE_BYTES = 128 * 1024 * 1024


def inspect_ads_fixture(
    payload: bytes, dataset: str, fallback_date: dt.date
) -> dict[str, Any]:
    if dataset not in ads_daily.DATASETS:
        raise ValueError(f"unknown Ads dataset: {dataset}")
    rows = ads_daily.parse_report_payload(payload)
    date_counts: Counter[str] = Counter()
    keys: list[tuple[dt.date, str]] = []
    for row in rows:
        report_date = ads_daily.report_date_for(row, fallback_date)
        entity_id = ads_daily.entity_id_for(dataset, row)
        date_counts[report_date.isoformat()] += 1
        keys.append((report_date, entity_id))
    return {
        "provider": "ads_api",
        "dataset": dataset,
        "record_count": len(rows),
        "report_date_counts": dict(sorted(date_counts.items())),
        "duplicate_target_keys": _duplicate_count(keys),
    }


def inspect_sales_traffic_fixture(payload: bytes, fallback_date: dt.date) -> dict[str, Any]:
    rows = sales_traffic.parse_report_payload(payload)
    date_counts: Counter[str] = Counter()
    keys: list[tuple[dt.date, str]] = []
    for row in rows:
        report_date, entity_id, _ = sales_traffic.normalize_row(row, fallback_date)
        date_counts[report_date.isoformat()] += 1
        keys.append((report_date, entity_id))
    return {
        "provider": "sp_api",
        "dataset": sales_traffic.DATASET,
        "record_count": len(rows),
        "report_date_counts": dict(sorted(date_counts.items())),
        "duplicate_target_keys": _duplicate_count(keys),
    }


def _duplicate_count(keys: list[tuple[dt.date, str]]) -> int:
    return len(keys) - len(set(keys))


def inspect_file(path: Path, provider: str, dataset: str, fallback_date: dt.date) -> dict[str, Any]:
    size = path.stat().st_size
    if size > MAX_FIXTURE_BYTES:
        raise ValueError(f"fixture exceeds the {MAX_FIXTURE_BYTES // (1024 * 1024)} MiB limit")
    payload = path.read_bytes()
    if provider == "ads_api":
        summary = inspect_ads_fixture(payload, dataset, fallback_date)
    elif provider == "sp_api":
        if dataset != sales_traffic.DATASET:
            raise ValueError(f"SP-API fixture inspector supports only {sales_traffic.DATASET}")
        summary = inspect_sales_traffic_fixture(payload, fallback_date)
    else:
        raise ValueError(f"unsupported provider: {provider}")
    return {
        **summary,
        "fixture_file": path.name,
        "fixture_bytes": size,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "fallback_date": fallback_date.isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("ads_api", "sp_api"), required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--fallback-date", type=dt.date.fromisoformat, required=True)
    args = parser.parse_args()
    try:
        result = inspect_file(args.file, args.provider, args.dataset, args.fallback_date)
    except (OSError, ValueError, EOFError, zlib.error) as exc:
        print(f"fixture invalid: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
