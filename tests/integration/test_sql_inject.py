import pytest

from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize(
    "query,length",
    [
        pytest.param("' LIMIT 100;--", 100, id="all rows"),
        pytest.param(
            "notarealroutename' UNION SELECT 0, table_name, 0, 0, '', now() FROM information_schema.tables--",
            213,
            id="get table list",
        ),
    ],
)
def test_radius_membership(client, query, length):
    response = client.get(f"/routes/inject/{query}")

    assert response.status_code == 200
    assert len(response.json()) == length
