"""Cache-aside behaviour on GET /routes/radius/{radius}.

Uses an isolated origin so the cached cells can't collide with the fixtures in
test_radius.py. Assertions read the FakeRedis contents from conftest directly
rather than inferring hits from timing.
"""

import json

import pytest

from app.api.routes.routes import calculate_geohash
from app.core.cache import RadiusCache, get_cache, index_key, pagination_signature, radius_key
from app.main import app
from app.schemas.routes import PaginationParams

ORIGIN = (-30.0, 140.0)  # isolated: no other test seeds routes near here
FAR = (12.0, -70.0)  # different geohash cell entirely
RADIUS = 10


def cache_key(radius=RADIUS, lat=ORIGIN[0], lon=ORIGIN[1], **pagination):
    """Rebuilds the key the endpoint would use, via the same helpers it uses."""
    geo_search = calculate_geohash(radius, lat, lon)
    sig = pagination_signature(PaginationParams(limit=100, **pagination))
    return radius_key(geo_search, sig)


def search(client, token, radius=RADIUS, lat=ORIGIN[0], lon=ORIGIN[1], **params):
    return client.get(
        f"/routes/radius/{radius}",
        params={"lat": lat, "lon": lon, **params},
        headers={"token": token},
    )


def create(client, token, name, lat, lon):
    resp = client.post(
        "/routes/", json={"name": name, "lat": lat, "lon": lon}, headers={"token": token}
    )
    assert resp.status_code == 200
    return resp.json()["id"]


@pytest.fixture
def cached_search(client, auth_token, fake_cache):
    """A route at ORIGIN plus one cached search covering it."""
    create(client, auth_token, "cache_origin", *ORIGIN)
    resp = search(client, auth_token)
    assert resp.status_code == 200
    assert cache_key() in fake_cache.store
    return resp.json()


def test_search_populates_cache_and_index(cached_search, fake_cache):
    key = cache_key()
    cached = json.loads(fake_cache.store[key])
    assert [r["id"] for r in cached["routes"]] == [
        r["id"] for r in cached_search["routes"]
    ]

    geo_search = calculate_geohash(RADIUS, *ORIGIN)
    assert key in fake_cache.sets[index_key(geo_search)]


def test_second_search_served_from_cache(client, auth_token, cached_search, fake_cache):
    """Poisons the cached value: if the response reflects it, the DB was skipped."""
    key = cache_key()
    poisoned = json.loads(fake_cache.store[key])
    poisoned["routes"][0]["name"] = "FromCache"
    fake_cache.store[key] = json.dumps(poisoned)

    resp = search(client, auth_token)
    assert resp.status_code == 200
    assert resp.json()["routes"][0]["name"] == "FromCache"


def test_pagination_windows_are_separate_entries(
    client, auth_token, cached_search, fake_cache
):
    resp = search(client, auth_token, page=1, pageSize=1)
    assert resp.status_code == 200

    paged_key = cache_key(page=1, pageSize=1)
    assert paged_key in fake_cache.store
    assert paged_key != cache_key()
    assert cache_key() in fake_cache.store  # the default window survives


def test_signature_matches_endpoint_branch(client, auth_token, cached_search, fake_cache):
    """Guards the one real risk in keying: pagination_signature lives in cache.py
    while the endpoint branches on its own if/elif, so the two could disagree about
    which window a request means. Sends every style at once — whichever branch the
    endpoint takes must be the one its key claims.
    """
    resp = search(client, auth_token, page=1, pageSize=1, since_id=1, offset=3)
    assert resp.status_code == 200

    key = cache_key(page=1, pageSize=1, since_id=1, offset=3)
    assert key in fake_cache.store
    assert "page=1:pageSize=1" in key

    # The page branch caps at pageSize, which the other branches wouldn't
    assert len(resp.json()["routes"]) == 1
    assert json.loads(fake_cache.store[key])["routes"] == resp.json()["routes"]


def test_nearby_point_reuses_the_same_entry(client, auth_token, cached_search, fake_cache):
    """Same geohash cell means the same query, so it must hit the same key."""
    nearby = (ORIGIN[0] + 0.0001, ORIGIN[1] + 0.0001)
    assert calculate_geohash(RADIUS, *nearby) == calculate_geohash(RADIUS, *ORIGIN)

    key = cache_key()
    poisoned = json.loads(fake_cache.store[key])
    poisoned["routes"][0]["name"] = "SharedCell"
    fake_cache.store[key] = json.dumps(poisoned)

    resp = search(client, auth_token, lat=nearby[0], lon=nearby[1])
    assert resp.json()["routes"][0]["name"] == "SharedCell"


def test_create_in_cell_invalidates_and_new_route_is_visible(
    client, auth_token, cached_search, fake_cache
):
    key = cache_key()
    before = [r["id"] for r in cached_search["routes"]]

    new_id = create(client, auth_token, "cache_invalidator", *ORIGIN)
    assert key not in fake_cache.store

    resp = search(client, auth_token)
    assert resp.status_code == 200
    returned = [r["id"] for r in resp.json()["routes"]]
    assert new_id in returned
    assert set(before).issubset(returned)


def test_create_elsewhere_leaves_entry_intact(
    client, auth_token, cached_search, fake_cache
):
    """Invalidation is prefix-precise, not a flush."""
    key = cache_key()
    create(client, auth_token, "cache_far_away", *FAR)
    assert key in fake_cache.store


def test_empty_result_is_not_cached(client, auth_token, fake_cache):
    empty = (-45.0, 170.0)
    resp = search(client, auth_token, lat=empty[0], lon=empty[1])
    assert resp.status_code == 404
    assert cache_key(lat=empty[0], lon=empty[1]) not in fake_cache.store


def test_search_works_with_cache_disabled(client, auth_token, cached_search):
    """CACHE_ENABLED=false leaves the cache clientless — the no_cache baseline."""

    async def no_cache():
        yield RadiusCache(None)

    original = app.dependency_overrides[get_cache]
    app.dependency_overrides[get_cache] = no_cache
    try:
        resp = search(client, auth_token)
        assert resp.status_code == 200
        assert resp.json()["routes"]

        assert create(client, auth_token, "cache_disabled_route", *ORIGIN)
    finally:
        app.dependency_overrides[get_cache] = original
