"""
Integration tests for GET /routes/radius/{radius}.

Fixture layout (all on the prime meridian for easy mental arithmetic):

    CENTER  (51.500, 0.0) — search origin
    INSIDE  (51.545, 0.0) — ~5 km north  → inside a 10 km search
    OUTSIDE (51.720, 0.0) — ~24 km north → outside a 10 km search, inside 50 km
"""

import pytest
from sqlalchemy import text

CENTER = (51.500, 0.0)
INSIDE = (51.545, 0.0)  # ~5 km
OUTSIDE = (51.720, 0.0)  # ~24 km


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
        pytest.param(50, True, True, id="50km_wide"),
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
