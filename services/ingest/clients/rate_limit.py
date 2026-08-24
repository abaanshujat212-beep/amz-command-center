"""Token-bucket rate limiting and 429 handling shared by both Amazon clients.

The numbers live in packages/shared/endpoints.py, keyed by endpoint key. This
module turns them into buckets; it does not restate them.

That matters because this file previously carried its own SPAPI_LIMITS and
ADS_LIMITS dicts keyed by invented operation names, and they had already drifted
from the catalog. Rate limits are exactly the kind of fact that is copied once
'for convenience' and then silently disagrees.

Two honest gaps, both encoded rather than papered over:

  * Amazon does NOT publish Ads API rate limits — they are dynamic. So Ads
    endpoints have rate_limit_rps=None, get no bucket, and are governed purely by
    Retry-After on 429. A guessed constant would look like pacing while still
    being throttled.
  * Sales & Traffic is limited per REPORT TYPE (~3 requests / 5 minutes), not per
    endpoint. Every SP-API report shares sp.reports.create, so that limit cannot
    be expressed as an endpoint bucket and is kept separate below.
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field

from packages.shared import endpoints as ep


@dataclass
class TokenBucket:
    rate: float
    burst: int
    _tokens: float = field(init=False)
    _last: float = field(init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def __post_init__(self) -> None:
        self._tokens = float(self.burst)
        self._last = time.monotonic()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(
                    self.burst, self._tokens + (now - self._last) * self.rate
                )
                self._last = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                wait = (1 - self._tokens) / self.rate
            # Capped so a 45-second-per-request endpoint cannot park a worker
            # forever without the loop being observable.
            time.sleep(min(wait, 30))


class Throttled(Exception):
    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__("throttled by Amazon")
        self.retry_after = retry_after


# One bucket per endpoint key, created on first use and shared process-wide.
# Buckets must be shared: two buckets for one endpoint means twice the rate,
# which is how a well-behaved-looking client gets an account throttled.
_buckets: dict[str, TokenBucket] = {}
_buckets_lock = threading.Lock()


def limiter_for(endpoint_key: str) -> TokenBucket | None:
    """Bucket for an endpoint, or None when Amazon publishes no limit.

    Raises ep.UnknownEndpoint for an uncatalogued key rather than returning None,
    because None here means 'no published limit' and a typo must not borrow that
    meaning — it would read as 'unlimited'.
    """
    endpoint = ep.endpoint(endpoint_key)
    if endpoint.rate_limit_rps is None:
        return None
    with _buckets_lock:
        bucket = _buckets.get(endpoint_key)
        if bucket is None:
            bucket = TokenBucket(
                rate=endpoint.rate_limit_rps,
                burst=endpoint.burst or 1,
            )
            _buckets[endpoint_key] = bucket
        return bucket


def acquire(endpoint_key: str) -> None:
    """Block until this endpoint may be called again."""
    bucket = limiter_for(endpoint_key)
    if bucket is not None:
        bucket.acquire()


# --- report-type limits ---------------------------------------------------
#
# These are NOT endpoint limits. They apply to a specific reportType requested
# through sp.reports.create, so they are enforced in addition to that endpoint's
# own bucket.
REPORT_TYPE_LIMITS: dict[str, tuple[float, int]] = {
    # ~3 requests per 5 minutes.
    "GET_SALES_AND_TRAFFIC_REPORT": (0.01, 3),
}

_report_buckets: dict[str, TokenBucket] = {}


def acquire_report_type(report_type: str) -> None:
    """Extra throttle for report types Amazon limits more tightly than the endpoint."""
    limit = REPORT_TYPE_LIMITS.get(report_type)
    if limit is None:
        return
    with _buckets_lock:
        bucket = _report_buckets.get(report_type)
        if bucket is None:
            bucket = TokenBucket(rate=limit[0], burst=limit[1])
            _report_buckets[report_type] = bucket
    bucket.acquire()


def backoff_sleep(attempt: int, retry_after: float | None = None) -> float:
    """Retry-After wins; otherwise exponential backoff with jitter, capped.

    Retry-After is not advisory. Ignoring it on a client's account is how API
    access gets suspended, and suspension is not a technical problem we can fix
    from here.
    """
    if retry_after:
        return min(float(retry_after), 300.0)
    return min(2**attempt + random.random(), 120.0)


MAX_ATTEMPTS = 6

# Report creation must NOT be retried blindly: each attempt consumes a scarce
# slot (one per 45s) and may leave a duplicate report queued. Retry the poll and
# the download, not the creation.
NON_RETRYABLE_ENDPOINTS = frozenset({"sp.reports.create", "ads.reports.create"})
