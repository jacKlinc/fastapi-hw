import logging
from datetime import datetime
import base64
import binascii

import pygeohash
from fastapi import status, HTTPException, Header, Depends, APIRouter, Request
from fastapi_pagination import Page
from fastapi_pagination.ext.sqlalchemy import paginate
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from pygeohash import encode

from app.core.security import decrypt_payload
from app.db.session import get_db, get_async_db
from app.db.models import Routes
from app.schemas.routes import (
    BboxOut,
    CreateRoute,
    PaginationParams,
    RouteOut,
    pagination_params,
)

logger = logging.getLogger(__name__)

BBOX_LIMIT = 500

limiter = Limiter(
    key_func=get_remote_address,
    strategy="fixed-window",
    storage_uri="memory://",
    enabled=True,
)
# Authenticated requests usually get a higher limit than anonymous
# They are easier to track so are given 10-100x rate limit
router = APIRouter(prefix="/routes")


@router.get("/bbox", response_model=BboxOut)
def get_routes_in_bbox(
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
    session: Session = Depends(get_db),
):
    """Returns routes within a lat/lon bounding box, capped at BBOX_LIMIT.

    Registered ahead of GET /{route_id} so "bbox" isn't swallowed as a route_id.
    """
    if min_lat >= max_lat or min_lon >= max_lon:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="min_lat/min_lon must be less than max_lat/max_lon",
        )

    bounds = (
        Routes.lat.between(min_lat, max_lat),
        Routes.lon.between(min_lon, max_lon),
    )
    total_count = session.execute(
        select(func.count()).select_from(Routes).where(*bounds)
    ).scalar_one()
    routes = (
        session.execute(select(Routes).where(*bounds).limit(BBOX_LIMIT))
        .scalars()
        .all()
    )

    logger.info(
        "Fetched bbox routes count=%s total_count=%s", len(routes), total_count
    )
    return {
        "routes": routes,
        "total_count": total_count,
        "capped": total_count > BBOX_LIMIT,
    }


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


@router.get("/inject/{name}")
async def get_route_inject(name, session: AsyncSession = Depends(get_async_db)):
    """Returns specific route ID"""
    query = f"SELECT * FROM routes WHERE name LIKE '%{name}%'"
    result = await session.execute(text(query))
    routes = result.scalars().all()
    if not routes:
        logger.error("Route not found: name=%s", name)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Route not found"
        )
    logger.info("Fetched %s routes", len(routes))
    return routes


def calculate_geohash(radius: float, lat: float, lon: float):
    geohash_map = [round(5_000 / (4**i), 1) for i in range(11)]

    min_value, index = max(geohash_map), -1
    for i, d in enumerate(geohash_map):
        diff = abs(d - radius)
        if diff < min_value:
            min_value, index = diff, i

    hashed_point = pygeohash.encode(lat, lon)

    return hashed_point[:index]


@router.get("/route-pag/{route_id}", response_model=Page[RouteOut])
def f_paginate(route_id: float, db: Session = Depends(get_db)):
    """Trying FastAPI's built-in pagination"""
    return paginate(db, select(Routes).where(Routes.id < route_id).order_by(Routes.id))


@limiter.limit("5/minute", per_method=True)
@router.get("/radius/{radius}")
def get_route_within_radius(
    request: Request,
    radius: int,
    lat: float,
    lon: float,
    pagination: PaginationParams = Depends(pagination_params),
    token: str = Header(None),
    session: Session = Depends(get_db),
):
    """Returns routes within radius. distance[km]"""
    decrypt_payload(token)
    # This is dependent on
    geo_search = calculate_geohash(radius, lat, lon)
    logger.info("geo_search=%s", geo_search)
    stmt = select(Routes).where(Routes.geohash.startswith(geo_search)).order_by("id")

    # page-based
    if pagination.page and pagination.pageSize:
        offset = (pagination.page - 1) * pagination.pageSize
        stmt = stmt.limit(pagination.pageSize).offset(offset)
        logger.info(
            "pagination.page=%s, pagination.pageSize=%s",
            pagination.page,
            pagination.pageSize,
        )
    # keyset
    elif pagination.since_id:
        stmt = stmt.where(Routes.id > pagination.since_id).limit(pagination.limit)
        logger.info("pagination.since_id=%s", pagination.since_id)
    # cursor
    elif pagination.cursor:
        try:
            decoded_id = int(
                base64.urlsafe_b64decode(pagination.cursor.encode()).decode()
            )
        except (ValueError, UnicodeDecodeError, binascii.Error):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid cursor"
            )
        stmt = stmt.where(Routes.id > decoded_id).limit(pagination.limit)
        logger.info("pagination.cursor=%s", pagination.cursor)
    # offset-based
    else:
        stmt = stmt.limit(pagination.limit).offset(pagination.offset)
        logger.info(
            "pagination.limit=%s, pagination.offset=%s",
            pagination.limit,
            pagination.offset,
        )

    routes = session.execute(stmt).scalars().all()
    if not routes:
        logger.error("Route not found for radius: radius=%s", radius)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Route not found for radius"
        )
    logger.info("Fetched route radius=%s", radius)
    cursor = base64.urlsafe_b64encode(str(routes[-1].id).encode()).decode()
    return {"routes": routes, "cursor": cursor}


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
        created_at=datetime.now(),  # asyncpg does not allow timezone-aware datetimes while sync one does
    )
    session.add(r)
    await session.commit()
    logger.info("Created route name=%s geohash=%s", r.name, r.geohash)
    return {"Result": "Success!"}
