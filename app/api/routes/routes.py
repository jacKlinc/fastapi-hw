import logging
from datetime import datetime, timezone

from fastapi import status, HTTPException, Header, Depends, APIRouter, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session
from sqlalchemy import select
from pygeohash import encode

from app.core.security import decrypt_payload
from app.db.session import get_db
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
def get_route(
    request: Request,
    route_id: int,
    token: str = Header(None),
    session: Session = Depends(get_db),
):
    """Returns specific route ID"""
    decrypt_payload(token)
    stmt = select(Routes).where(Routes.id == route_id)
    route = session.execute(stmt).scalar()
    if not route:
        logger.error("Route not found: id=%s", route_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Route not found"
        )
    logger.info("Fetched route id=%s", route_id)
    return route


@limiter.limit("5/minute", per_method=True)
@router.post("/")
def create_route(
    request: Request,
    route: CreateRoute,
    token: str = Header(None),
    session: Session = Depends(get_db),
):
    """Creates route"""
    decrypt_payload(token)
    r = Routes(
        name=route.name,
        lat=route.lat,
        lon=route.lon,
        geohash=encode(route.lat, route.lon),
        created_at=datetime.now(timezone.utc),
    )
    session.add(r)
    session.commit()
    logger.info("Created route name=%s geohash=%s", r.name, r.geohash)
    return {"Result": "Success!"}
