import logging
from datetime import datetime

import pygeohash
from fastapi import status, HTTPException, Header, Depends, APIRouter, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pygeohash import encode

from app.core.security import decrypt_payload
from app.db.session import get_db, get_async_db
from app.db.models import Routes
from app.schemas.routes import CreateRoute

logger = logging.getLogger(__name__)

limiter = Limiter(
    key_func=get_remote_address,
    strategy="fixed-window",
    storage_uri="memory://",
    enabled=True,
)
# Authenticated requests usually get a higher limit than anonymous
# They are easier to track so are given 10-100x rate limit
router = APIRouter(prefix="/routes")


@limiter.limit("5/minute", per_method=True)
@router.get("/{route_id}")
async def get_route(
    request: Request,
    route_id: int,
    token: str = Header(None),
    session: AsyncSession = Depends(get_async_db),
):
    """Returns specific route ID"""
    decrypt_payload(token)
    stmt = select(Routes).where(Routes.id == route_id)
    result = await session.execute(stmt)
    route = result.scalar()
    if not route:
        logger.error("Route not found: id=%s", route_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Route not found"
        )
    logger.info("Fetched route id=%s", route_id)
    return route


def calculate_geohash(radius: float, lat: float, lon: float):
    geohash_map = [round(5_000 / (4**i), 1) for i in range(11)]

    min_value, index = max(geohash_map), -1
    for i, d in enumerate(geohash_map):
        diff = abs(d - radius)
        if diff < min_value:
            min_value, index = diff, i

    hashed_point = pygeohash.encode(lat, lon)

    return hashed_point[:index]


@limiter.limit("5/minute", per_method=True)
@router.get("/radius/{radius}")
def get_route_within_radius(
    radius: int,
    lat: float,
    lon: float,
    offset: int = 0,
    limit: int = 100,
    token: str = Header(None),
    session: Session = Depends(get_db),
):
    """Returns routes within radius. distance[km]"""
    decrypt_payload(token)
    # This is dependent on
    geo_search = calculate_geohash(radius, lat, lon)
    logger.info("geo_search=%s", geo_search)
    stmt = (
        select(Routes)
        .where(Routes.geohash.startswith(geo_search))
        .order_by("id")
        .limit(limit)
        .offset(offset)
    )
    routes = session.execute(stmt).scalars().all()
    if not routes:
        logger.error("Route not found for radius: radius=%s", radius)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Route not found for radius"
        )
    logger.info("Fetched route radius=%s", radius)
    return routes


@limiter.limit("5/minute", per_method=True)
@router.post("/")
async def create_route(
    request: Request,
    route: CreateRoute,
    token: str = Header(None),
    session: AsyncSession = Depends(get_async_db),
):
    """Creates route"""
    decrypt_payload(token)
    r = Routes(
        name=route.name,
        lat=route.lat,
        lon=route.lon,
        geohash=encode(route.lat, route.lon),
        created_at=datetime.now(), # asyncpg does not allow timezone-aware datetimes while sync one does
    )
    session.add(r)
    await session.commit()
    logger.info("Created route name=%s geohash=%s", r.name, r.geohash)
    return {"Result": "Success!"}
