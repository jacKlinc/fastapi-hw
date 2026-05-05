from typing import AsyncGenerator, Generator, Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.core.config import settings


DATABASE_URL = f"postgresql://{settings.postgres_user}:{settings.postgres_password}@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
engine = create_engine(DATABASE_URL)

# Async
a_engine = create_async_engine(
    f"postgresql+asyncpg://{settings.postgres_user}:{settings.postgres_password}@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
)
async_session_factory = async_sessionmaker(a_engine, expire_on_commit=False)


def get_db() -> Generator[Session]:
    """Creates synchronous SQL Alchemy session"""
    session = Session(engine)
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


async def get_async_db() -> AsyncGenerator[AsyncSession, Any]:
    """Creates asynchronous SQL Alchemy session"""
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
