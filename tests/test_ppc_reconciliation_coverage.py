from datetime import date
from decimal import Decimal

from infra.scripts.reconcile_ppc_exports import METRICS, Record, make_report

D1 = date(2026, 10, 1)
D2 = date(2026, 10, 2)
D3 = date(2026, 10, 3)


def records(*days: date) -> list[Record]:
    return [
        Record(day, grain, "account" if grain == "account" else "campaign",
               "top_of_search" if grain == "placement" else "", "GBP", {
                   "spend": Decimal(2),
                   "ad_sales": Decimal(10),
                   "ad_orders": Decimal(1),
                   "budget_amount": Decimal(4),
                   "total_sales": Decimal(20),
               })
        for day in days for grain in ("campaign", "placement", "account")
    ]


def report(app: list[Record], ref: list[Record], end: date = D2) -> dict:
    limits = {
        key: {"absolute": Decimal(0)} for key in (
            *METRICS, "placement.top_of_search.spend", "placement.top_of_search.ad_sales",
            "placement.top_of_search.ad_orders",
        )
    }
    return make_report(app, ref, start=D1, end=end, definitions={}, limits=limits,
                       app_meta={}, ref_meta={})


def test_aligned_covered_window_preserves_pass():
    result = report(records(D1, D2), records(D1, D2))
    assert result["result"] == "pass"
    assert result["coverage"]["complete"] is True


def test_equal_totals_on_different_dates_cannot_pass():
    result = report(records(D1), records(D2))
    assert result["comparisons"]["spend"]["status"] == "pass"
    assert result["result"] == "incomplete"
    dates = result["coverage"]["by_grain"]["campaign"]
    assert dates["application_only_dates"] == ["2026-10-01"]
    assert dates["reference_only_dates"] == ["2026-10-02"]
    assert "date_mismatch" in dates["reasons"]


def test_both_sources_without_placement_evidence_cannot_pass():
    partial = [row for row in records(D1, D2) if row.grain != "placement"]
    result = report(partial, partial)
    assert result["result"] == "incomplete"
    assert result["coverage"]["by_grain"]["placement"]["reasons"] == [
        "application_missing", "reference_missing",
    ]


def test_matching_partial_days_do_not_certify_full_window():
    result = report(records(D1, D3), records(D1, D3), end=D3)
    assert result["result"] == "incomplete"
    assert result["coverage"]["by_grain"]["account"]["reasons"] == [
        "application_incomplete_window", "reference_incomplete_window",
    ]


def test_placement_date_mismatch_detected_even_when_placement_grain_dates_match():
    app, ref = records(D1, D2), records(D1, D2)
    for rows, offset in ((app, 1), (ref, 4)):
        old = rows[offset]
        rows[offset] = Record(old.report_date, old.grain, old.entity_id,
                              "rest_of_search", old.currency, old.values)
    result = report(app, ref)
    assert result["coverage"]["by_grain"]["placement"]["reasons"] == []
    assert result["coverage"]["by_grain"]["placement.top_of_search"]["reasons"] == [
        "date_mismatch",
    ]
    assert result["result"] == "incomplete"
