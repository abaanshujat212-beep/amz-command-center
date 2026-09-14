import datetime as dt

from services.rules.freshness import FreshnessState, resolve_source_freshness

NOW = dt.datetime(2026, 9, 14, 8, tzinfo=dt.timezone.utc)
CUTOFF = dt.date(2026, 9, 11)


class Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.params = None

    def execute(self, _sql, params):
        self.params = params

    def fetchall(self):
        return self.rows


def row(**updates):
    value = {
        "dataset": "ads_sp_keyword_daily",
        "last_complete_date": CUTOFF,
        "last_attempt_at": NOW,
        "last_status": "success",
        "run_status": "success",
        "finished_at": NOW - dt.timedelta(hours=2),
        "date_to": CUTOFF,
    }
    value.update(updates)
    return value


def resolve(rows):
    cur = Cursor(rows)
    result = resolve_source_freshness(
        cur,
        tenant_id="tenant-a",
        scope="keyword",
        now=NOW,
        settled_cutoff=CUTOFF,
        max_age_hours=48,
    )
    assert cur.params[1:] == ("tenant-a", "tenant-a")
    return result


def test_freshness_comes_from_persisted_finished_at_and_watermark():
    result = resolve([row()])
    assert result.state is FreshnessState.FRESH
    assert result.data_loaded_at == NOW - dt.timedelta(hours=2)
    assert result.data_through == CUTOFF


def test_missing_evidence_fails_closed():
    assert resolve([]).state is FreshnessState.MISSING
    assert resolve([row(finished_at=None)]).state is FreshnessState.MISSING


def test_failed_and_partial_sources_fail_closed():
    assert resolve([row(run_status="failed")]).state is FreshnessState.FAILED
    assert resolve([row(last_status="partial")]).state is FreshnessState.PARTIAL


def test_stale_source_fails_closed_without_now_fallback():
    result = resolve([row(finished_at=NOW - dt.timedelta(hours=72))])
    assert result.state is FreshnessState.STALE
    assert result.data_loaded_at != NOW


def test_latest_unsettled_watermark_is_clamped_to_settled_cutoff():
    result = resolve([row(last_complete_date=CUTOFF + dt.timedelta(days=2))])
    assert result.state is FreshnessState.FRESH
    assert result.data_through == CUTOFF
