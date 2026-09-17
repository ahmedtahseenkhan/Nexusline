"""Rate limit for the connector monitoring feed, on the shared limiter.

A token bucket per connector (the id in its feed token): ``ccm_ingest_rate_per_minute``
results may burst, refilling at the same rate per minute. Shared across API workers
through Redis when it answers (see :mod:`app.services.rate_limit`).
"""
from __future__ import annotations

from app.services.rate_limit import RateLimiter

_feed: RateLimiter | None = None


def feed_limiter() -> RateLimiter:
    global _feed
    from app.core.config import settings

    limit = max(1, int(settings.ccm_ingest_rate_per_minute or 60))
    if _feed is None or _feed.capacity != limit:
        _feed = RateLimiter("connector-ingest", capacity=limit, per_second=limit / 60)
    return _feed
