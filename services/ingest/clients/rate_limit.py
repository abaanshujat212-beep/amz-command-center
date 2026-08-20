"""Token-bucket rate limiting and 429 handling shared by both Amazon clients.

SP-API publishes a rate and a burst per operation. Exceeding it returns 429 with
a Retry-After header, which we always respect — hammering a throttled endpoint
on a client's account is how access gets suspended.
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field

# operation -> (requests per second, burst)
SPAPI_LIMITS: dict[str, tuple[float, int]] = {
    "createReport": (0.0222, 10),
    "getReport": (2.0, 15),
    "getReportDocument": (0.0167, 15),
    "getOrders": (0.0167, 20),
    "getCatalogItem": (5.0, 40),
    "getInventorySummaries": (2.0, 30),
    "listFinancialEvents": (0.5, 30),
    # Sales & Traffic is limited to roughly 3 requests per 5 minutes.
    "salesAndTraffic": (0.01, 3),
}

ADS_LIMITS: dict[str, tuple[float, int]] = {
    "createReport": (1.0, 10),
    "getReport": (2.0, 20),
    "listProfiles": (1.0, 5),
    "updateBids": (1.0, 10),
}


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
            time.sleep(min(wait, 30))


class Throttled(Exception):
    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__("throttled by Amazon")
        self.retry_after = retry_after


def backoff_sleep(attempt: int, retry_after: float | None = None) -> float:
    """Retry-After wins; otherwise exponential backoff with jitter, capped."""
    if retry_after:
        return min(float(retry_after), 300.0)
    return min(2**attempt + random.random(), 120.0)


MAX_ATTEMPTS = 6
