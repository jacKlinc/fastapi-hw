from datetime import datetime, timezone

from fastapi import status, HTTPException, Header, Depends, APIRouter
from sqlalchemy.orm import Session
from sqlalchemy import select
from pygeohash import encode

from app.core.security import decrypt_payload
from app.db.session import get_db
from app.db.models import Routes
from app.schemas.routes import CreateRoute


router = APIRouter(prefix="/routes")


@router.get("/{route_id}")
def get_route(
    route_id: int, token: str = Header(None), session: Session = Depends(get_db)
):
    """Returns specific route ID"""
    decrypt_payload(token)
    stmt = select(Routes).where(Routes.id == route_id)
    route = session.execute(stmt).scalar()
    if not route:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Route not found"
        )
    return route


@router.post("/")
def create_route(
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
    return {"Result": "Success!"}
