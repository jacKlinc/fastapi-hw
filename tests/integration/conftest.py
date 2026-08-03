import os
import uuid

import pytest
import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.api.routes.routes import limiter
from app.core.cache import RadiusCache, get_cache
from app.db.models import Base
from app.db.session import get_db, get_async_db
from app.main import app

TEST_DB_PATH = "/tmp/test_fastapi_hw.db"
SYNC_URL = f"sqlite:///{TEST_DB_PATH}"
ASYNC_URL = f"sqlite+aiosqlite:///{TEST_DB_PATH}"


class FakePipeline:
    """Queues commands and applies them on execute(), like redis-py's pipeline."""

    def __init__(self, redis):
        self.redis = redis
        self.queued = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def setex(self, key, ttl, value):
        self.queued.append(("setex", (key, ttl, value)))

    def sadd(self, key, *members):
        self.queued.append(("sadd", (key, *members)))

    def smembers(self, key):
        self.queued.append(("smembers", (key,)))

    def expire(self, key, ttl):
        self.queued.append(("expire", (key, ttl)))

    def delete(self, *keys):
        self.queued.append(("delete", keys))

    async def execute(self):
        results = []
        for name, args in self.queued:
            results.append(await getattr(self.redis, name)(*args))
        self.queued.clear()
        return results


class FakeRedis:
    """Dict-backed stand-in for the subset of redis.asyncio.Redis the app uses.

    Keeps the suite off a real server without pulling in fakeredis. TTLs are
    recorded but not enforced — nothing under test depends on expiry.
    """

    def __init__(self):
        self.store: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key):
        return self.store.get(key)

    async def setex(self, key, ttl, value):
        self.store[key] = value
        self.ttls[key] = ttl

    async def sadd(self, key, *members):
        self.sets.setdefault(key, set()).update(members)

    async def smembers(self, key):
        return set(self.sets.get(key, set()))

    async def expire(self, key, ttl):
        self.ttls[key] = ttl

    async def delete(self, *keys):
        for key in keys:
            self.store.pop(key, None)
            self.sets.pop(key, None)
            self.ttls.pop(key, None)

    def pipeline(self, transaction=False):
        return FakePipeline(self)

    async def aclose(self):
        pass


@pytest.fixture(scope="session")
def fake_cache():
    return FakeRedis()


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
def client(db_engine, fake_cache):
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

    async def override_get_cache():
        yield RadiusCache(fake_cache)

    # Every test shares one client address, so the 5/minute limits would start
    # returning 429s partway through the suite. No test asserts on rate limiting.
    limiter.enabled = False

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_async_db] = override_get_async_db
    app.dependency_overrides[get_cache] = override_get_cache
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
