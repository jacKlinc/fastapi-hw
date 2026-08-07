"""Integration tests for GET /routes/haversine/{radius}.

Same fixture geometry as test_radius.py (all on the prime meridian for easy mental
arithmetic), so the two endpoints can be compared directly:

    CENTER  (51.500, 0.0) — search origin; sits at the northern edge of geohash cell u10hb
    INSIDE  (51.470, 0.0) — ~3.3 km south; inside 10 km, outside 3 km
    OUTSIDE (51.720, 0.0) — ~24 km north; outside 10 km
    NORTH   (51.510, 0.0) — ~1.1 km north; inside 10 km but in a different geohash cell
"""

import pygeohash
import pytest

from app.api.routes.routes import calculate_geohash

CENTER = (51.500, 0.0)
INSIDE = (51.470, 0.0)
OUTSIDE = (51.720, 0.0)
NORTH = (51.510, 0.0)  # just over the cell boundary CENTER sits on


@pytest.fixture(scope="module")
def haversine_routes(client, auth_token, db_engine):
    from sqlalchemy import text

    names = {"hav_inside": INSIDE, "hav_outside": OUTSIDE, "hav_north": NORTH}
    for name, (lat, lon) in names.items():
        client.post(
            "/routes/",
            json={"name": name, "lat": lat, "lon": lon},
            headers={"token": auth_token},
        )
    with db_engine.connect() as conn:
        return {
            name: conn.execute(
                text("SELECT id FROM routes WHERE name=:n ORDER BY id DESC LIMIT 1"),
                {"n": name},
            ).scalar()
            for name in names
        }


def search(client, radius, origin=CENTER, **params):
    return client.get(
        f"/routes/haversine/{radius}",
        params={"lat": origin[0], "lon": origin[1], **params},
    )


@pytest.mark.parametrize(
    "radius,expect_inside,expect_outside",
    [
        pytest.param(10, True, False, id="10km_finds_inside_only"),
        pytest.param(3, False, False, id="3km_misses_both"),
        pytest.param(30, True, True, id="30km_finds_both"),
    ],
)
def test_membership(client, haversine_routes, radius, expect_inside, expect_outside):
    resp = search(client, radius)
    assert resp.status_code == 200
    returned = [r["id"] for r in resp.json()]

    assert (haversine_routes["hav_inside"] in returned) is expect_inside
    assert (haversine_routes["hav_outside"] in returned) is expect_outside


def test_empty_area_returns_empty_list(client):
    """Intentionally different from radius, which 404s."""
    resp = search(client, 1, origin=(0.0, -150.0))
    assert resp.status_code == 200
    assert resp.json() == []


def test_limit_caps_results(client, haversine_routes):
    resp = search(client, 30, limit=1)
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_requires_no_token(client, haversine_routes):
    """Public like /routes/bbox — no token header at all."""
    assert search(client, 10).status_code == 200


def test_geohash_search_misses_a_true_match(client, auth_token, haversine_routes):
    """The approximation gap, as behaviour rather than a benchmark statistic.

    NORTH is ~1.1 km from CENTER — comfortably inside a 10 km search — but CENTER
    sits on a cell boundary, so NORTH lands in a different geohash prefix and the
    radius endpoint cannot see it.
    """
    prefix_len = len(calculate_geohash(10, *CENTER))
    assert (
        pygeohash.encode(*CENTER)[:prefix_len]
        != pygeohash.encode(*NORTH)[:prefix_len]
    ), "fixture assumption broken: NORTH should be in a different cell"

    hav = search(client, 10)
    assert haversine_routes["hav_north"] in [r["id"] for r in hav.json()]

    geo = client.get(
        "/routes/radius/10",
        params={"lat": CENTER[0], "lon": CENTER[1]},
        headers={"token": auth_token},
    )
    geo_ids = [r["id"] for r in geo.json()["routes"]] if geo.status_code == 200 else []
    assert haversine_routes["hav_north"] not in geo_ids
