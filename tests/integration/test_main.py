import uuid
import random
import string

import pytest


# TODO mock DB
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


@pytest.mark.parametrize(
    "params,status_code",
    [
        ({"username": "jack", "password": "jack"}, 200),
        ({"username": "notarealuser", "password": "notarealpassw"}, 404),
        ({"username": "jack", "password": "notarealpassw"}, 401),
    ],
)
def test_get_token(client, params, status_code):
    response = client.post("/auth/token", params=params)
    assert response.status_code == status_code
    assert response.json() is not None


@pytest.mark.parametrize(
    "route_id,status_code",
    [
        (8, 200),
        (-1, 404),
    ],
)
def test_get_route(client, auth_token, route_id, status_code):
    response = client.get(
        f"/routes/{route_id}",
        headers={"token": auth_token},
    )
    assert response.status_code == status_code
    assert response.json() is not None


def test_create_route(client, auth_token):
    response = client.post(
        "/routes/",
        json={"name": "TestRoute", "lat": 51.6, "lon": -115.2},
        headers={"token": auth_token},
    )
    assert response.status_code == 200
    assert response.json() == {"Result": "Success!"}
