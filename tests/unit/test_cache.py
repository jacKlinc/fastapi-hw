"""Cache key construction and behaviour when redis misbehaves.

The endpoint-level cache-aside flow is covered in tests/integration/test_cache.py;
this covers key layout and the failure path, which is the part that decides whether
a redis outage degrades the API or takes it down.
"""

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.cache import (
    CircuitBreaker,
    RadiusCache,
    index_key,
    pagination_signature,
    radius_key,
)
from app.schemas.routes import PaginationParams

KEY = radius_key("u10hb", "offset=None:limit=100")


class BrokenRedis:
    """Every command fails, as it would with redis unreachable."""

    def __init__(self):
        self.calls = 0

    async def get(self, key):
        self.calls += 1
        raise RedisConnectionError("boom")

    def pipeline(self, transaction=False):
        self.calls += 1
        raise RedisConnectionError("boom")


class WorkingRedis:
    async def get(self, key):
        return None


def test_keys_are_namespaced():
    assert KEY == "radius:u10hb:offset=None:limit=100"
    assert index_key("u10hb") == "radiuskeys:u10hb"


@pytest.mark.parametrize(
    "params,expected",
    [
        ({"page": 2, "pageSize": 50}, "page=2:pageSize=50"),
        ({"since_id": 67, "limit": 10}, "since_id=67:limit=10"),
        ({"cursor": "Njc=", "limit": 10}, "cursor=Njc=:limit=10"),
        ({"offset": 20, "limit": 10}, "offset=20:limit=10"),
    ],
)
def test_pagination_signature(params, expected):
    assert pagination_signature(PaginationParams(**params)) == expected


def test_pagination_signature_precedence():
    """Must match get_route_within_radius's branch order: page, keyset, cursor, offset.

    If these drift apart, one window's rows get cached under another's key. The
    end-to-end guard is test_signature_matches_endpoint_branch in the integration
    tests; this pins the order on its own.
    """
    everything = {"pageSize": 5, "since_id": 3, "cursor": "Njc=", "offset": 1, "limit": 10}
    assert pagination_signature(PaginationParams(page=1, **everything)).startswith("page=")

    without_page = dict(everything, pageSize=None)
    assert pagination_signature(PaginationParams(**without_page)).startswith("since_id=")

    without_keyset = dict(without_page, since_id=None)
    assert pagination_signature(PaginationParams(**without_keyset)).startswith("cursor=")

    without_cursor = dict(without_keyset, cursor=None)
    assert pagination_signature(PaginationParams(**without_cursor)).startswith("offset=")


def test_breaker_opens_only_after_threshold():
    breaker = CircuitBreaker(threshold=2, cooldown_s=60)
    assert not breaker.is_open

    breaker.record_failure()
    assert not breaker.is_open

    breaker.record_failure()
    assert breaker.is_open

    breaker.record_success()
    assert not breaker.is_open


def test_breaker_closes_after_cooldown():
    breaker = CircuitBreaker(threshold=1, cooldown_s=0)
    breaker.record_failure()
    assert not breaker.is_open  # cooldown already elapsed


async def test_clientless_cache_is_a_no_op():
    cache = RadiusCache(None)
    assert await cache.get(KEY) is None
    await cache.set("u10hb", KEY, {"routes": []})  # must not raise
    await cache.invalidate("u10hbxxxxxxx")  # must not raise


async def test_redis_errors_are_swallowed():
    cache = RadiusCache(BrokenRedis())
    assert await cache.get(KEY) is None
    await cache.set("u10hb", KEY, {"routes": []})
    await cache.invalidate("u10hbxxxxxxx")


async def test_breaker_stops_calling_redis_after_repeated_failures():
    broken = BrokenRedis()
    cache = RadiusCache(broken)

    for _ in range(cache.breaker.threshold):
        await cache.get(KEY)
    assert broken.calls == cache.breaker.threshold

    # Breaker is open now: further calls short-circuit without touching redis
    await cache.get(KEY)
    await cache.set("u10hb", KEY, {"routes": []})
    await cache.invalidate("u10hbxxxxxxx")
    assert broken.calls == cache.breaker.threshold


async def test_success_resets_failure_count():
    cache = RadiusCache(BrokenRedis())
    await cache.get(KEY)
    assert cache.breaker.consecutive_failures == 1

    cache.client = WorkingRedis()
    await cache.get(KEY)
    assert cache.breaker.consecutive_failures == 0
