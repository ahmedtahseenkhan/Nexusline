"""A small token-bucket rate limiter for machine-facing endpoints (phase 4).

Push feeds authenticate with a long-lived token rather than a user session, so nothing
else stops a misconfigured integration (or a stolen token) from posting thousands of
readings a minute. Each :class:`RateLimiter` names a bucket family, how many calls may
burst (``capacity``) and how fast the bucket refills (``per_second``):

    KRI_FEED = RateLimiter("kri-feed", capacity=20, per_second=20 / 60)
    decision = await KRI_FEED.hit(str(kri_id))
    if not decision.allowed:
        raise too_many_requests(decision)

Storage: Redis (``settings.redis_url``) when it answers, so every API worker shares one
bucket; otherwise an in-process bucket per worker, which still caps a runaway client.
A Redis failure never fails the request — the limiter falls back to memory and retries
Redis after :data:`REDIS_RETRY_SECONDS`. ``RATE_LIMIT_BACKEND=memory`` skips Redis.
"""
from __future__ import annotations

import logging
import math
import os
import threading
import time
from dataclasses import dataclass

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

#: After Redis fails, use memory for this long before trying Redis again.
REDIS_RETRY_SECONDS = 60.0
#: Idle memory buckets are dropped past this many keys (oldest first).
MAX_MEMORY_KEYS = 10_000


@dataclass(frozen=True)
class Decision:
    allowed: bool
    remaining: int
    #: Seconds until one call is allowed again (0 when allowed).
    retry_after: float = 0.0


def take(tokens: float, updated: float, now: float, *, capacity: int, per_second: float) -> tuple[bool, float, float]:
    """One token-bucket step. Pure: ``(allowed, tokens_after, retry_after)``.

    The bucket refills at ``per_second`` up to ``capacity`` since ``updated``; a call
    takes one token when at least one is there."""
    tokens = min(float(capacity), tokens + max(0.0, now - updated) * per_second)
    if tokens >= 1.0:
        return True, tokens - 1.0, 0.0
    wait = (1.0 - tokens) / per_second if per_second > 0 else math.inf
    return False, tokens, wait


# Atomic in Redis: refill, take, store, expire. KEYS[1]; ARGV capacity, per_second, now.
_LUA = """
local b = redis.call('HMGET', KEYS[1], 't', 'u')
local cap = tonumber(ARGV[1]); local rate = tonumber(ARGV[2]); local now = tonumber(ARGV[3])
local t = tonumber(b[1]) or cap; local u = tonumber(b[2]) or now
t = math.min(cap, t + math.max(0, now - u) * rate)
local ok = 0; local wait = 0
if t >= 1 then t = t - 1; ok = 1 else wait = (1 - t) / rate end
redis.call('HSET', KEYS[1], 't', t, 'u', now)
redis.call('EXPIRE', KEYS[1], math.ceil(cap / rate) + 60)
return {ok, tostring(t), tostring(wait)}
"""


class _Redis:
    """The shared Redis client, or None while Redis is unavailable."""

    def __init__(self) -> None:
        self._client = None
        self._down_until = 0.0

    def client(self):
        if os.environ.get("RATE_LIMIT_BACKEND", "").lower() == "memory":
            return None
        if time.monotonic() < self._down_until:
            return None
        if self._client is None:
            try:
                from redis import asyncio as redis_asyncio

                from app.core.config import settings

                if not settings.redis_url:
                    return None
                self._client = redis_asyncio.from_url(
                    settings.redis_url, socket_connect_timeout=0.25, socket_timeout=0.25,
                )
            except Exception:  # noqa: BLE001 - no Redis library or bad URL: memory it is
                self.failed()
                return None
        return self._client

    def failed(self) -> None:
        self._client = None
        self._down_until = time.monotonic() + REDIS_RETRY_SECONDS


_REDIS = _Redis()


class RateLimiter:
    def __init__(self, name: str, *, capacity: int, per_second: float) -> None:
        self.name = name
        self.capacity = capacity
        self.per_second = per_second
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def hit_memory(self, key: str, now: float | None = None) -> Decision:
        now = time.monotonic() if now is None else now
        with self._lock:
            tokens, updated = self._buckets.pop(key, (float(self.capacity), now))
            allowed, tokens, wait = take(tokens, updated, now, capacity=self.capacity, per_second=self.per_second)
            self._buckets[key] = (tokens, now)  # re-inserted last: dict order is recency
            while len(self._buckets) > MAX_MEMORY_KEYS:
                self._buckets.pop(next(iter(self._buckets)))
        return Decision(allowed, int(tokens), wait)

    async def hit(self, key: str) -> Decision:
        """Take one call from ``key``'s bucket."""
        client = _REDIS.client()
        if client is not None:
            try:
                ok, tokens, wait = await client.eval(
                    _LUA, 1, f"ratelimit:{self.name}:{key}", self.capacity, self.per_second, time.time(),
                )
                return Decision(bool(int(ok)), int(float(tokens)), float(wait))
            except Exception:  # noqa: BLE001 - Redis down: never fail the request for it
                logger.warning("Rate limiter %s: Redis unavailable, limiting in memory", self.name)
                _REDIS.failed()
        return self.hit_memory(key)

    def reset(self) -> None:
        """Forget every in-memory bucket (tests)."""
        with self._lock:
            self._buckets.clear()


def too_many_requests(decision: Decision, what: str = "requests") -> HTTPException:
    """429 with ``Retry-After`` in whole seconds."""
    seconds = max(1, math.ceil(decision.retry_after)) if math.isfinite(decision.retry_after) else 60
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"Too many {what}. Try again in {seconds} second{'s' if seconds != 1 else ''}.",
        headers={"Retry-After": str(seconds)},
    )


__all__ = ["Decision", "RateLimiter", "take", "too_many_requests"]
