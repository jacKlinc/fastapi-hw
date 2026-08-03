import uuid
import random
import string

import pytest


def test_register(client):
    def get_random_string(length):
        characters = string.ascii_letters + string.digits
        return "".join(random.choices(characters, k=length))

    response = client.post(
        "/auth/register",
        params={
            "username": uuid.uuid4().hex,
            "email": get_random_string(8),
            "password": "test_password",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"Result": "Success!"}


@pytest.fixture(scope="module")
def registered_user(client):
    username = uuid.uuid4().hex
    password = "test_password"
    client.post(
        "/auth/register",
        params={
            "username": username,
            "email": f"{username}@test.com",
            "password": password,
        },
    )
    return {"username": username, "password": password}


@pytest.mark.parametrize(
    "password,status_code", [("test_password", 200), ("notarealpassw", 401)]
)
def test_get_token(client, registered_user, password, status_code):
    response = client.post(
        "/auth/token",
        params={"username": registered_user["username"], "password": password},
    )
    assert response.status_code == status_code


def test_get_token_user_not_found(client):
    response = client.post(
        "/auth/token", params={"username": "notarealuser", "password": "notarealpassw"}
    )
    assert response.status_code == 404


@pytest.fixture(scope="module")
def created_route_id(client, auth_token, db_engine):
    from sqlalchemy import text

    response = client.post(
        "/routes/",
        json={"name": "TestRoute", "lat": 51.6, "lon": -115.2},
        headers={"token": auth_token},
    )
    assert response.status_code == 200
    with db_engine.connect() as conn:
        return conn.execute(text("SELECT id FROM routes ORDER BY id DESC LIMIT 1")).scalar()


def test_get_route(client, auth_token, created_route_id):
    response = client.get(f"/routes/{created_route_id}", headers={"token": auth_token})
    assert response.status_code == 200


def test_get_route_not_found(client, auth_token):
    response = client.get("/routes/-1", headers={"token": auth_token})
    assert response.status_code == 404


def test_create_route(client, auth_token):
    response = client.post(
        "/routes/",
        json={"name": "TestRoute", "lat": 51.6, "lon": -115.2},
        headers={"token": auth_token},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["Result"] == "Success!"
    assert isinstance(body["id"], int)
