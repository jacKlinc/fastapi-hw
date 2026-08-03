"""Redis cache-aside for the radius search.

Plain string GET/SETEX with JSON payloads rather than the RedisJSON `.json()` API,
so this works against a stock redis:7-alpine with no extra modules.

Radius results are keyed by the geohash prefix the query scans plus the pagination
window, which is the whole of what the result depends on. That also makes
invalidation tractable: a new route only invalidates searches whose prefix it
starts with, found via a set-per-prefix index rather than a SCAN.

A `RadiusCache` with no client is a working no-op, which is how CACHE_ENABLED=false
and a torn-down test both behave — call sites never branch on cache availability.
"""

import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator, Awaitable, TypeVar

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.schemas.routes import PaginationParams

logger = logging.getLogger(__name__)

T = TypeVar("T")

KEY_PREFIX = "radius"
INDEX_PREFIX = "radiuskeys"

# calculate_geohash() returns prefixes of length 0-10, so a new route can only
# invalidate searches at one of 11 prefix lengths — a bounded loop, no SCAN
MAX_PREFIX_LEN = 11


def radius_key(geo_search: str, pagination_sig: str) -> str:
    """Cache key for a radius search.

    The query is `geohash LIKE '{geo_search}%'` with a pagination window, so those
    two inputs fully determine the result — lat/lon inside the same cell share an
    entry, which bounds the key space for free.
    """
    return f"{KEY_PREFIX}:{geo_search}:{pagination_sig}"


def index_key(geo_search: str) -> str:
    """Set of cache keys scanning this prefix, used to invalidate them together."""
    return f"{INDEX_PREFIX}:{geo_search}"


def pagination_signature(pagination: PaginationParams) -> str:
    """Identifies the pagination window a cached result covers.

    The branch order here must match `get_route_within_radius`'s — otherwise one
    window's rows get cached under another window's key. Locked down by
    test_pagination_signature_matches_endpoint_precedence.
    """
    if pagination.page and pagination.pageSize:
        return f"page={pagination.page}:pageSize={pagination.pageSize}"
    if pagination.since_id:
        return f"since_id={pagination.since_id}:limit={pagination.limit}"
    if pagination.cursor:
        return f"cursor={pagination.cursor}:limit={pagination.limit}"
    return f"offset={pagination.offset}:limit={pagination.limit}"


class CircuitBreaker:
    """Trips after `threshold` consecutive failures, stays open for `cooldown`.

    With redis down, every request otherwise pays the full connect timeout —
    measured at 111s per request on redis-py defaults.
    """

    def __init__(self, threshold: int = 3, cooldown_s: int = 10):
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self.consecutive_failures = 0
        self.opened_at = 0.0

    @property
    def is_open(self) -> bool:
        if self.consecutive_failures < self.threshold:
            return False
        return time.monotonic() - self.opened_at < self.cooldown_s

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        if self.consecutive_failures == self.threshold:
            self.opened_at = time.monotonic()
            logger.warning("Cache breaker open, skipping redis for %ss", self.cooldown_s)

    def record_success(self) -> None:
        if self.consecutive_failures:
            logger.info("Cache recovered after %s failures", self.consecutive_failures)
        self.consecutive_failures = 0


class RadiusCache:
    """Cache-aside store for radius searches, keyed by geohash prefix.

    Owns its redis client and breaker so tests can build an isolated instance
    instead of resetting module globals.
    """

    def __init__(self, client: Redis | None = None, breaker: CircuitBreaker | None = None):
        self.client = client
        self.breaker = breaker or CircuitBreaker()

    @property
    def available(self) -> bool:
        return self.client is not None and not self.breaker.is_open

    async def connect(self) -> None:
        """Builds the client. Called once from the app lifespan."""
        if not settings.cache_enabled:
            logger.info("Cache disabled, skipping redis connection")
            return
        self.client = Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            decode_responses=True,
            # A cache lookup must never cost more than the DB query it replaces
            socket_connect_timeout=settings.cache_timeout_seconds,
            socket_timeout=settings.cache_timeout_seconds,
        )
        logger.info("Connected to redis host=%s", settings.redis_host)

    async def aclose(self) -> None:
        if self.client is not None:
            await self.client.aclose()
            self.client = None
            logger.info("Closed redis connection")

    async def _guarded(
        self, op: str, key: str, awaitable: Awaitable[T]
    ) -> tuple[bool, T | None]:
        """Runs a redis call under a hard deadline, returning (ok, value).

        socket_connect_timeout doesn't cover DNS resolution — when the redis
        container disappears, getaddrinfo alone blocked for 45s in testing.
        Bounding the whole await is the only thing that actually caps the cost.
        """
        try:
            value = await asyncio.wait_for(
                awaitable, timeout=settings.cache_timeout_seconds
            )
        except (RedisError, TimeoutError, OSError):
            self.breaker.record_failure()
            logger.warning("Cache %s failed key=%s", op, key)
            return False, None
        self.breaker.record_success()
        return True, value

    async def get(self, key: str) -> dict | None:
        """Reads a cached search. None on miss, disabled cache, or redis failure."""
        if not self.available:
            return None
        ok, raw = await self._guarded("read", key, self.client.get(key))
        if not ok or raw is None:
            return None
        return json.loads(raw)

    async def set(self, geo_search: str, key: str, value: dict) -> None:
        """Caches a result and records it in its prefix's invalidation index.

        Value and index go in one pipeline — the index is only useful if it lands
        with the value, and this is on the request path.
        """
        if not self.available:
            return

        ttl = settings.cache_ttl_seconds
        idx = index_key(geo_search)

        async def write():
            async with self.client.pipeline(transaction=False) as pipe:
                pipe.setex(key, ttl, json.dumps(value))
                pipe.sadd(idx, key)
                # Refreshed on every write, so the index expires with its entries
                pipe.expire(idx, ttl)
                return await pipe.execute()

        await self._guarded("write", key, write())

    async def invalidate(self, geohash: str) -> None:
        """Drops every cached search that would have contained this geohash.

        A search scanning prefix P contains the new route iff P is a prefix of its
        geohash, so only the 11 prefixes of `geohash` can be affected.
        """
        if not self.available:
            return

        prefixes = [geohash[:i] for i in range(MAX_PREFIX_LEN)]

        async def read_index():
            async with self.client.pipeline(transaction=False) as pipe:
                for prefix in prefixes:
                    pipe.smembers(index_key(prefix))
                return await pipe.execute()

        ok, member_sets = await self._guarded("index read", geohash, read_index())
        if not ok or not member_sets:
            return

        stale: set[str] = set()
        for members in member_sets:
            stale.update(members or [])
        if not stale:
            return

        async def drop():
            async with self.client.pipeline(transaction=False) as pipe:
                pipe.delete(*stale)
                pipe.delete(*[index_key(prefix) for prefix in prefixes])
                return await pipe.execute()

        ok, _ = await self._guarded("invalidate", geohash, drop())
        if ok:
            logger.info(
                "Invalidated %s radius entries for geohash=%s", len(stale), geohash
            )


radius_cache = RadiusCache()


async def get_cache() -> AsyncGenerator[RadiusCache, Any]:
    """Dependency yielding the shared cache. No-ops when CACHE_ENABLED is false."""
    yield radius_cache
