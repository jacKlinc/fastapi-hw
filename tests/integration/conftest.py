import os
import uuid

import pytest
import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.db.models import Base
from app.db.session import get_db, get_async_db
from app.main import app

TEST_DB_PATH = "/tmp/test_fastapi_hw.db"
SYNC_URL = f"sqlite:///{TEST_DB_PATH}"
ASYNC_URL = f"sqlite+aiosqlite:///{TEST_DB_PATH}"


@pytest.fixture(scope="session")
def db_engine():
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    engine = create_engine(SYNC_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)


@pytest.fixture(scope="session")
def client(db_engine):
    async_engine = create_async_engine(ASYNC_URL, connect_args={"check_same_thread": False})
    factory = async_sessionmaker(async_engine, expire_on_commit=False)

    def override_get_db():
        session = Session(db_engine)
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def override_get_async_db():
        async with factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_async_db] = override_get_async_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="session")
async def async_client(client):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture(scope="session")
def auth_token(client):
    username = uuid.uuid4().hex
    password = "test_password"
    client.post("/auth/register", params={"username": username, "email": f"{username}@test.com", "password": password})
    response = client.post("/auth/token", params={"username": username, "password": password})
    return response.json()["token"]
