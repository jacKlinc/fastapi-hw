import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.models import Base
from app.db.session import get_db
from app.main import app

TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="session")
def db_engine():
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture(scope="session")
def client(db_engine):
    def override_get_db():
        session = Session(db_engine)
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="session")
def auth_token(client):
    username = uuid.uuid4().hex
    password = "test_password"
    client.post("/auth/register", params={"username": username, "email": f"{username}@test.com", "password": password})
    response = client.post("/auth/token", params={"username": username, "password": password})
    return response.json()["token"]
