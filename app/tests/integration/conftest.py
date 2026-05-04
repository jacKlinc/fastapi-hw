import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def auth_token(client):
    username = uuid.uuid4().hex
    password = "test_password"
    client.post("/auth/register", params={"username": username, "email": f"{username}@test.com", "password": password})
    response = client.post("/auth/token", params={"username": username, "password": password})
    return response.json()["token"]
