"""Stable, provenance-carrying inputs for deterministic bid optimizers.

This module defines and normalizes signals only. It deliberately contains no
bid calculation or recommendation policy; those belong to the optimizer core.
"""

from __future__ import annotations

import datetime as dt
import math
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

SIGNAL_CONTRACT_VERSION = "r05.1"
SUPPORTED_ENTITY_TYPES = {"keyword", "target"}
REQUIRED_SIGNALS = (
    "current_bid", "match_type", "impressions", "clicks", "spend", "sales",
    "orders", "cpc", "acos", "roas", "freshness_days",
)
OPTIONAL_SIGNALS = (
    "break_even_acos",
    "contribution_margin_pct",
    "placement",
    "placement_modifier_pct",
    "volatility_cpc_cv",
    "organic_rank",
    "sponsored_rank",
    "share_of_voice",
    "inventory_days",
    "buy_box_share",
    "selling_price",
)
_OPTIONAL_NUMERIC = {
    "break_even_acos", "contribution_margin_pct", "placement_modifier_pct",
    "organic_rank", "sponsored_rank", "share_of_voice", "inventory_days",
    "buy_box_share", "selling_price",
}


class SignalContractError(ValueError):
    """Input rows cannot satisfy the normalized signal contract."""


@dataclass(frozen=True)
class NormalizedSignal:
    value: Any
    status: str
    source_relation: str | None
    source_ref: str | None
    observed_through: str | None
    reason: str | None = None


@dataclass(frozen=True)
class BidSignalSnapshot:
    contract_version: str
    tenant_id: str
    entity_type: str
    entity_id: str
    window_start: str
    window_end: str
    observed_days: int
    settled_days: int
    signals: Mapping[str, NormalizedSignal]

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "tenant_id": self.tenant_id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "observed_days": self.observed_days,
            "settled_days": self.settled_days,
            "signals": {key: asdict(value) for key, value in sorted(self.signals.items())},
        }


def _day(value: Any) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise SignalContractError(f"invalid report_date: {value!r}") from exc


def _number(value: Any, *, nonnegative: bool = True) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or (nonnegative and number < 0):
        return None
    return number


def _signal(
    value: Any,
    *,
    source_relation: str | None,
    source_ref: str | None,
    observed_through: dt.date,
    status: str | None = None,
    reason: str | None = None,
) -> NormalizedSignal:
    return NormalizedSignal(
        value=value,
        status=status or ("observed" if value is not None else "missing"),
        source_relation=source_relation,
        source_ref=source_ref,
        observed_through=observed_through.isoformat(),
        reason=reason,
    )


def _sum_field(
    rows: Sequence[Mapping[str, Any]], name: str
) -> tuple[float | None, str]:
    values = [_number(row.get(name)) for row in rows]
    known = [value for value in values if value is not None]
    if not known:
        return None, "missing"
    return sum(known), "observed" if len(known) == len(values) else "partial"


def _ratio_signal(
    totals: Mapping[str, tuple[float | None, str]],
    numerator: str,
    denominator: str,
    *,
    source_relation: str,
    source_ref: str,
    observed_through: dt.date,
) -> NormalizedSignal:
    top, top_status = totals[numerator]
    bottom, bottom_status = totals[denominator]
    if top is None or bottom is None:
        value, status, reason = None, "missing", "required source values are unavailable"
    elif bottom == 0:
        value, status, reason = None, "undefined", f"{denominator} is zero"
    else:
        value = top / bottom
        status = "observed" if top_status == bottom_status == "observed" else "partial"
        reason = "one or more settled daily values are unavailable" if status == "partial" else None
    return _signal(
        value,
        source_relation=source_relation,
        source_ref=source_ref,
        observed_through=observed_through,
        status=status,
        reason=reason,
    )


def build_bid_signal_snapshots(
    rows: Sequence[Mapping[str, Any]],
    *,
    tenant_id: str,
    through: dt.date,
    lookback_days: int,
    source_relation: str = "marts.mart_ppc_keyword_daily",
    context_signals: Mapping[tuple[str, str], Mapping[str, Mapping[str, Any]]] | None = None,
) -> list[BidSignalSnapshot]:
    """Aggregate one settled daily mart window per tenant/entity.

    Rows outside the requested tenant/window are ignored; unsettled rows count
    toward source coverage but never contribute to normalized metric values.
    Duplicate entity/day rows fail closed instead of silently double-counting.
    Optional context values must carry their own source and observation date.
    """
    if not tenant_id.strip():
        raise SignalContractError("tenant_id is required")
    if lookback_days < 1:
        raise SignalContractError("lookback_days must be positive")
    window_start = through - dt.timedelta(days=lookback_days - 1)
    grouped: dict[tuple[str, str], list[tuple[dt.date, Mapping[str, Any], bool]]] = defaultdict(list)
    seen_days: set[tuple[str, str, dt.date]] = set()
    for row in rows:
        if str(row.get("tenant_id") or "") != tenant_id:
            continue
        report_date = _day(row.get("report_date"))
        if not (window_start <= report_date <= through):
            continue
        entity_type = str(row.get("entity_type") or "keyword").strip().lower()
        entity_id = str(row.get("entity_id") or row.get("keyword_id") or "").strip()
        if entity_type not in SUPPORTED_ENTITY_TYPES:
            raise SignalContractError(f"unsupported bid entity type: {entity_type!r}")
        if not entity_id:
            raise SignalContractError("entity_id is required")
        daily_key = (entity_type, entity_id, report_date)
        if daily_key in seen_days:
            raise SignalContractError(f"duplicate settled row for {entity_type}/{entity_id} on {report_date}")
        seen_days.add(daily_key)
        grouped[(entity_type, entity_id)].append((report_date, row, row.get("is_settled") is True))

    snapshots: list[BidSignalSnapshot] = []
    for (entity_type, entity_id), all_rows in sorted(grouped.items()):
        all_rows.sort(key=lambda item: item[0])
        dated_rows = [(day, row) for day, row, settled in all_rows if settled]
        if not dated_rows:
            continue
        observed_through = dated_rows[-1][0]
        source_ref = f"{entity_type}:{entity_id}:{window_start}:{through}"
        daily = [row for _, row in dated_rows]
        signals: dict[str, NormalizedSignal] = {}

        totals: dict[str, tuple[float | None, str]] = {
            name: _sum_field(daily, name)
            for name in ("impressions", "clicks", "cost", "attributed_orders_7d", "attributed_sales_7d")
        }
        aliases = {
            "impressions": "impressions",
            "clicks": "clicks",
            "spend": "cost",
            "orders": "attributed_orders_7d",
            "sales": "attributed_sales_7d",
        }
        for signal_name, column in aliases.items():
            value, status = totals[column]
            signals[signal_name] = _signal(
                int(value) if signal_name in {"impressions", "clicks", "orders"} and value is not None else value,
                source_relation=source_relation,
                source_ref=source_ref,
                observed_through=observed_through,
                status=status,
                reason="one or more settled daily values are unavailable" if status == "partial" else None,
            )

        signals["cpc"] = _ratio_signal(
            totals, "cost", "clicks", source_relation=source_relation,
            source_ref=source_ref, observed_through=observed_through,
        )
        signals["acos"] = _ratio_signal(
            totals, "cost", "attributed_sales_7d", source_relation=source_relation,
            source_ref=source_ref, observed_through=observed_through,
        )
        signals["roas"] = _ratio_signal(
            totals, "attributed_sales_7d", "cost", source_relation=source_relation,
            source_ref=source_ref, observed_through=observed_through,
        )

        latest = daily[-1]
        match_types = {str(row.get("match_type") or "").strip().lower() for row in daily}
        match_types.discard("")
        match = next(iter(match_types)) if len(match_types) == 1 else None
        signals["current_bid"] = _signal(
            _number(latest.get("bid")), source_relation=source_relation,
            source_ref=source_ref, observed_through=observed_through,
            reason="latest settled bid is unavailable" if latest.get("bid") is None else None,
        )
        signals["match_type"] = _signal(
            match, source_relation=source_relation, source_ref=source_ref,
            observed_through=observed_through,
            status="observed" if match else ("invalid" if len(match_types) > 1 else "missing"),
            reason="match type changes within the window" if len(match_types) > 1 else None,
        )

        for field in ("break_even_acos", "contribution_margin_pct"):
            values = [
                _number(row.get(field), nonnegative=field != "contribution_margin_pct")
                for row in daily
            ]
            known = [value for value in values if value is not None]
            # The minimum observed break-even value is conservative across the window.
            value = min(known) if known else None
            signals[field] = _signal(
                value, source_relation=source_relation, source_ref=source_ref,
                observed_through=observed_through,
                status="observed" if value is not None and len(known) == len(values) else ("partial" if value is not None else "missing"),
                reason="economics are incomplete for part of the window" if value is not None and len(known) < len(values) else None,
            )

        daily_cpcs = []
        for row in daily:
            clicks, cost = _number(row.get("clicks")), _number(row.get("cost"))
            if clicks is not None and clicks > 0 and cost is not None:
                daily_cpcs.append(cost / clicks)
        if len(daily_cpcs) < 2:
            volatility, volatility_status, volatility_reason = None, "insufficient_data", "requires at least two settled daily CPC values"
        elif statistics.fmean(daily_cpcs) == 0:
            volatility, volatility_status, volatility_reason = None, "undefined", "mean daily CPC is zero"
        else:
            volatility = statistics.pstdev(daily_cpcs) / statistics.fmean(daily_cpcs)
            volatility_status = "observed" if len(daily_cpcs) == len(daily) else "partial"
            volatility_reason = None if volatility_status == "observed" else "daily CPC is unavailable for part of the window"
        signals["volatility_cpc_cv"] = _signal(
            volatility, source_relation=source_relation, source_ref=source_ref,
            observed_through=observed_through, status=volatility_status,
            reason=volatility_reason,
        )
        signals["freshness_days"] = _signal(
            (through - observed_through).days,
            source_relation=source_relation, source_ref=source_ref,
            observed_through=observed_through,
        )

        context = (context_signals or {}).get((entity_type, entity_id), {})
        for name in OPTIONAL_SIGNALS:
            existing = signals.get(name)
            if existing is not None and existing.status not in {
                "missing", "insufficient_data", "undefined"
            }:
                continue
            supplied = context.get(name)
            if supplied is None:
                if existing is not None:
                    continue
                signals[name] = _signal(
                    None, source_relation=None, source_ref=None,
                    observed_through=observed_through, status="missing",
                    reason="no verified source supplied this optional signal",
                )
                continue
            source, ref = supplied.get("source"), supplied.get("source_ref")
            observed = supplied.get("observed_at")
            if not source or not ref or observed is None:
                signals[name] = _signal(
                    None, source_relation=None, source_ref=None,
                    observed_through=observed_through, status="invalid",
                    reason="optional signal requires source, source_ref, and observed_at",
                )
                continue
            observed_day = _day(observed)
            value = supplied.get("value")
            if name in _OPTIONAL_NUMERIC:
                number = _number(value, nonnegative=name != "contribution_margin_pct")
                out_of_range = (
                    number is not None
                    and (
                        (name in {"share_of_voice", "buy_box_share"} and number > 1)
                        or (name in {"organic_rank", "sponsored_rank"} and number <= 0)
                    )
                )
                if number is None or out_of_range:
                    value = None
                    status, reason = "invalid", "optional numeric signal is outside its documented range"
                else:
                    value = number
                    status, reason = "observed", None
            else:
                status, reason = ("observed", None) if value is not None else ("missing", "source returned null")
                if name == "placement" and value is not None:
                    value = str(value).strip().lower().replace(" ", "_").replace("-", "_")
                    if value not in {"top_of_search", "product_page", "rest_of_search", "off_amazon"}:
                        value = None
                        status, reason = "invalid", "placement is not a supported canonical placement"
            signals[name] = _signal(
                value, source_relation=str(source), source_ref=str(ref),
                observed_through=observed_day, status=status, reason=reason,
            )

        snapshots.append(BidSignalSnapshot(
            contract_version=SIGNAL_CONTRACT_VERSION,
            tenant_id=tenant_id,
            entity_type=entity_type,
            entity_id=entity_id,
            window_start=window_start.isoformat(),
            window_end=through.isoformat(),
            observed_days=len(all_rows),
            settled_days=len(dated_rows),
            signals=signals,
        ))
    return snapshots
