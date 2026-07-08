"""
Integration tests for GET /routes/radius/{radius}.

Fixture layout (all on the prime meridian for easy mental arithmetic):

    CENTER  (51.500, 0.0) — search origin; sits at the northern edge of geohash cell u10hb
    INSIDE  (51.470, 0.0) — ~3.3 km south; same 5-char cell (u10hb), different 6-char → inside 10 km, outside 3 km
    OUTSIDE (51.720, 0.0) — ~24 km north; different 5-char cell (u10n0) → outside 10 km
"""

import pytest
from sqlalchemy import text

CENTER = (51.500, 0.0)
INSIDE = (51.470, 0.0)  # ~3.3 km south, same 5-char geohash cell as CENTER
OUTSIDE = (51.720, 0.0)  # ~24 km north, different geohash cell


@pytest.fixture(scope="module")
def radius_routes(client, auth_token, db_engine):
    for name, (lat, lon) in [("radius_inside", INSIDE), ("radius_outside", OUTSIDE)]:
        client.post(
            "/routes/",
            json={"name": name, "lat": lat, "lon": lon},
            headers={"token": auth_token},
        )
    with db_engine.connect() as conn:
        inside_id = conn.execute(
            text(
                "SELECT id FROM routes WHERE name='radius_inside' ORDER BY id DESC LIMIT 1"
            )
        ).scalar()
        outside_id = conn.execute(
            text(
                "SELECT id FROM routes WHERE name='radius_outside' ORDER BY id DESC LIMIT 1"
            )
        ).scalar()
    return {"inside": inside_id, "outside": outside_id}


@pytest.mark.parametrize(
    "radius,expect_inside,expect_outside",
    [
        pytest.param(10, True, False, id="10km_finds_inside_only"),
        pytest.param(3, False, False, id="3km_misses_both"),
    ],
)
def test_radius_membership(
    client, auth_token, radius_routes, radius, expect_inside, expect_outside
):
    resp = client.get(
        f"/routes/radius/{radius}",
        params={"lat": CENTER[0], "lon": CENTER[1]},
        headers={"token": auth_token},
    )
    if not expect_inside and not expect_outside:
        assert resp.status_code == 404
        return

    assert resp.status_code == 200
    returned_ids = [r["id"] for r in resp.json()]

    if expect_inside:
        assert radius_routes["inside"] in returned_ids
    else:
        assert radius_routes["inside"] not in returned_ids

    if expect_outside:
        assert radius_routes["outside"] in returned_ids
    else:
        assert radius_routes["outside"] not in returned_ids


def test_no_routes_in_area_returns_404(client, auth_token):
    resp = client.get(
        "/routes/radius/1",
        params={"lat": 0.0, "lon": -150.0},
        headers={"token": auth_token},
    )
    assert resp.status_code == 404


PAGE_ORIGIN = (10.0, 10.0)  # isolated point, unused elsewhere in the test suite


@pytest.fixture(scope="module")
def page_routes(client, auth_token, db_engine):
    for i in range(5):
        client.post(
            "/routes/",
            json={
                "name": f"page_route_{i}",
                "lat": PAGE_ORIGIN[0],
                "lon": PAGE_ORIGIN[1],
            },
            headers={"token": auth_token},
        )
    with db_engine.connect() as conn:
        return (
            conn.execute(
                text("SELECT id FROM routes WHERE name LIKE 'page_route_%' ORDER BY id")
            )
            .scalars()
            .all()
        )


@pytest.mark.parametrize(
    "params,expected_slice",
    [
        pytest.param({}, slice(0, 5), id="no_pagination_returns_all"),
        pytest.param({"limit": 2}, slice(0, 2), id="limit_only"),
        pytest.param({"offset": 2, "limit": 2}, slice(2, 4), id="offset_and_limit"),
        pytest.param({"page": 2, "pageSize": 2}, slice(2, 4), id="page_and_pageSize"),
    ],
)
def test_radius_pagination(client, auth_token, page_routes, params, expected_slice):
    resp = client.get(
        "/routes/radius/1",
        params={"lat": PAGE_ORIGIN[0], "lon": PAGE_ORIGIN[1], **params},
        headers={"token": auth_token},
    )
    assert resp.status_code == 200
    returned_ids = [r["id"] for r in resp.json()]
    assert returned_ids == page_routes[expected_slice]
